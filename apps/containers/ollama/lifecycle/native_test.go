package lifecycle

import (
	"context"
	"net"
	"net/http"
	"os"
	"sync/atomic"
	"testing"
	"time"
)

func TestNativeSocketIdentityAndActivity(t *testing.T) {
	previous := nativeDirectory
	directory, err := os.MkdirTemp("/tmp", "homelab-native-test-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(directory) })
	nativeDirectory = directory
	configured = &gateway{}
	defer func() { ReleaseNative(12345); nativeDirectory = previous; configured = nil }()
	path, err := ReserveNative(12345)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = ReserveNative(12345); err == nil {
		t.Fatal("duplicate native identity accepted")
	}
	listener, err := net.Listen("unix", path)
	if err != nil {
		t.Fatal(err)
	}
	var mode atomic.Int32
	server := &http.Server{Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/slots" {
			t.Error("unexpected native probe")
		}
		switch mode.Load() {
		case 0:
			_, _ = w.Write([]byte(`[{"is_processing":false}]`))
		case 1:
			_, _ = w.Write([]byte(`[{"is_processing":true}]`))
		default:
			_, _ = w.Write([]byte(`[{}]`))
		}
	})}
	go server.Serve(listener)
	defer server.Close()
	deadline := time.Now().Add(time.Second)
	for work.Load() != 0 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if idle, known := nativeQuiescent(); !idle || !known {
		t.Fatal("idle native socket not verified")
	}
	mode.Store(1)
	if idle, known := nativeQuiescent(); idle || !known {
		t.Fatal("native inference missed")
	}
	mode.Store(2)
	if idle, known := nativeQuiescent(); idle || known {
		t.Fatal("unknown native schema counted idle")
	}
	for _, address := range []string{"external:12345", "localhost:0", "localhost:65536", "localhost:not-a-port"} {
		if c, err := NativeDial(context.Background(), "tcp", address); err == nil {
			c.Close()
			t.Fatal("invalid native target accepted")
		}
	}
	server.Close()
	if idle, known := nativeQuiescent(); idle || known {
		t.Fatal("missing native socket counted idle")
	}
	ReleaseNative(12345)
	if idle, known := nativeQuiescent(); !idle || !known {
		t.Fatal("observed process retirement not reflected")
	}
}
