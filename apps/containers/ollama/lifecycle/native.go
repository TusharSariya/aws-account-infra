package lifecycle

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"sync"
	"sync/atomic"
	"time"
)

var nativeDirectory = "/tmp/homelab-native"

var work atomic.Int64
var nativeMu sync.Mutex
var nativePorts = map[int]bool{}

// Go records asynchronous work before scheduling it, closing the handler-return race.
func Go(f func())  { work.Add(1); go func() { defer work.Add(-1); f() }() }
func Hold() func() { work.Add(1); return func() { work.Add(-1) } }
func nativeSocket(port int) string {
	return filepath.Join(nativeDirectory, fmt.Sprintf("runner-%d.sock", port))
}

func ReserveNative(port int) (string, error) {
	if configured == nil {
		return "127.0.0.1", nil
	} // Upstream isolated unit tests do not start Serve.
	if port < 1 || port > 65535 {
		return "", errors.New("invalid native endpoint")
	}
	lock, err := os.OpenFile(nativeSocket(port)+".lock", os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0600)
	if err != nil {
		return "", err
	}
	_ = lock.Close()
	nativeMu.Lock()
	nativePorts[port] = true
	nativeMu.Unlock()
	return nativeSocket(port), nil
}
func ReleaseNative(port int) {
	if configured == nil {
		return
	}
	nativeMu.Lock()
	delete(nativePorts, port)
	nativeMu.Unlock()
	_ = os.Remove(nativeSocket(port))
	_ = os.Remove(nativeSocket(port) + ".lock")
}

// NativeDial removes the native TCP listener from the shared Pod network.
func NativeDial(ctx context.Context, network, address string) (net.Conn, error) {
	dialer := net.Dialer{Timeout: 2 * time.Second}
	if configured == nil {
		return dialer.DialContext(ctx, network, address)
	}
	host, text, err := net.SplitHostPort(address)
	if err != nil {
		return nil, err
	}
	if host != "127.0.0.1" && host != "localhost" {
		return nil, errors.New("unexpected native host")
	}
	port, err := strconv.Atoi(text)
	if err != nil || port < 1 || port > 65535 {
		return nil, errors.New("invalid native port")
	}
	return dialer.DialContext(ctx, "unix", nativeSocket(port))
}

func nativeQuiescent() (bool, bool) {
	nativeMu.Lock()
	ports := make([]int, 0, len(nativePorts))
	for port := range nativePorts {
		ports = append(ports, port)
	}
	nativeMu.Unlock()
	idle := work.Load() == 0
	client := http.Client{Timeout: 2 * time.Second, Transport: &http.Transport{DialContext: NativeDial, DisableKeepAlives: true}}
	for _, port := range ports {
		resp, err := client.Get(fmt.Sprintf("http://127.0.0.1:%d/slots", port))
		if err != nil {
			return false, false
		}
		var slots []struct {
			Processing *bool `json:"is_processing"`
		}
		decode := json.NewDecoder(resp.Body).Decode(&slots)
		_ = resp.Body.Close()
		if resp.StatusCode != 200 || decode != nil || len(slots) == 0 {
			return false, false
		}
		for _, slot := range slots {
			if slot.Processing == nil {
				return false, false
			}
			if *slot.Processing {
				idle = false
			}
		}
	}
	return idle, true
}
