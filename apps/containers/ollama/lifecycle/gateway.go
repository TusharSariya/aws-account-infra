// Package lifecycle is embedded in the pinned Ollama server, before every API route.
package lifecycle

import (
	"bytes"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"
)

type tracked struct{ ending bool }
type gateway struct {
	mu                                                       sync.Mutex
	endpoint, token, userToken, workspaceToken, pod, process string
	tickets                                                  map[string]*tracked
	client                                                   *http.Client
}

var configured *gateway

func Configure() error {
	endpoint := os.Getenv("HOMELAB_LIFECYCLE_URL")
	if endpoint != "http://ai-lifecycle.homelab-platform.svc:8080" {
		return errors.New("fixed lifecycle endpoint required")
	}
	read := func(name string) (string, error) {
		value, err := os.ReadFile("/credentials/" + name)
		if err != nil || len(strings.TrimSpace(string(value))) < 43 {
			return "", errors.New("independent gateway credentials required")
		}
		return strings.TrimSpace(string(value)), nil
	}
	token, err := read("lifecycle-token")
	if err != nil {
		return err
	}
	user, err := read("model-user-token")
	if err != nil {
		return err
	}
	workspace, err := read("model-workspace-token")
	if err != nil {
		return err
	}
	if token == user || user == workspace || workspace == token {
		return errors.New("separate gateway credentials required")
	}
	if os.Getenv("POD_UID") == "" {
		return errors.New("Pod identity required")
	}
	if err = os.MkdirAll(nativeDirectory, 0700); err != nil {
		return err
	}
	var process [16]byte
	if _, err := rand.Read(process[:]); err != nil {
		return err
	}
	configured = &gateway{process: hex.EncodeToString(process[:]), endpoint: endpoint, token: token, userToken: user, workspaceToken: workspace, pod: os.Getenv("POD_UID"), tickets: map[string]*tracked{}, client: &http.Client{Timeout: 5 * time.Second, CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return errors.New("redirect rejected") }}}
	go configured.loop()
	return nil
}

func (g *gateway) call(operation string, payload map[string]any) error {
	payload["pod_uid"] = g.pod
	payload["process_id"] = g.process
	body, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	req, err := http.NewRequest("POST", g.endpoint+"/activity/ollama/"+operation, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+g.token)
	req.Header.Set("Content-Type", "application/json")
	resp, err := g.client.Do(req)
	if err != nil {
		return errors.New("activity controller unavailable")
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return errors.New("activity admission rejected")
	}
	return nil
}

func authorized(value, key string) bool {
	return subtle.ConstantTimeCompare([]byte(value), []byte("Bearer "+key)) == 1
}
func failure(w http.ResponseWriter, code int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": message})
}

func Middleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		g := configured
		if g == nil {
			failure(w, 503, "gateway unavailable")
			return
		}
		if r.Method == "GET" && r.URL.Path == "/activity-identity" {
			challenge := r.URL.Query().Get("challenge")
			if !authorized(r.Header.Get("Authorization"), g.token) || !regexp.MustCompile("^[a-f0-9]{32}$").MatchString(challenge) {
				failure(w, 401, "source authentication required")
				return
			}
			signature := hmac.New(sha256.New, []byte(g.token))
			signature.Write([]byte(challenge + ":" + g.process))
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Cache-Control", "no-store")
			_ = json.NewEncoder(w).Encode(map[string]string{"process_id": g.process, "signature": hex.EncodeToString(signature.Sum(nil))})
			return
		}
		if r.Method == "GET" && r.URL.Path == "/healthz" {
			w.WriteHeader(200)
			return
		}
		workspace := authorized(r.Header.Get("Authorization"), g.workspaceToken)
		if !workspace && !authorized(r.Header.Get("Authorization"), g.userToken) {
			failure(w, 401, "authentication required")
			return
		}
		if r.URL.Path != "/" && !strings.HasPrefix(r.URL.Path, "/api/") && !strings.HasPrefix(r.URL.Path, "/v1/") {
			failure(w, 404, "unsupported model API path")
			return
		}
		passive := (r.Method == "GET" || r.Method == "HEAD") && (r.URL.Path == "/" || r.URL.Path == "/api/version" || r.URL.Path == "/api/tags" || r.URL.Path == "/api/ps")
		if passive {
			next.ServeHTTP(w, r)
			return
		}
		parent := ""
		// Only inference can extend already-admitted work while draining.
		// Downloads, uploads and model mutations always require fresh admission.
		inference := r.URL.Path == "/api/generate" || r.URL.Path == "/api/chat" || r.URL.Path == "/api/embed" || r.URL.Path == "/api/embeddings" || r.URL.Path == "/v1/chat/completions" || r.URL.Path == "/v1/completions" || r.URL.Path == "/v1/embeddings" || r.URL.Path == "/v1/responses"
		if workspace && inference {
			parent = r.Header.Get("X-Homelab-Work")
		}
		var random [16]byte
		if _, err := rand.Read(random[:]); err != nil {
			failure(w, 503, "activity identity unavailable")
			return
		}
		ticket := hex.EncodeToString(random[:])
		g.mu.Lock()
		if len(g.tickets) >= 128 {
			g.mu.Unlock()
			failure(w, 429, "activity tracking full")
			return
		}
		g.tickets[ticket] = &tracked{}
		payload := map[string]any{"ticket": ticket, "parent": nil, "deadline": float64(time.Now().UnixNano())/1e9 + 25}
		if parent != "" {
			payload["parent"] = parent
		}
		err := g.call("begin", payload)
		if err != nil {
			g.tickets[ticket].ending = true
			g.mu.Unlock()
			failure(w, 503, "new model work is not admitted")
			return
		}
		g.mu.Unlock()
		// Keep tracking after HTTP cancellation until asynchronous handlers/downloads
		// and native inference are observed quiescent. Never block request cancellation.
		defer func() { g.mu.Lock(); g.tickets[ticket].ending = true; g.mu.Unlock() }()
		next.ServeHTTP(w, r)
	})
}

func (g *gateway) loop() {
	for {
		g.mu.Lock()
		idle, known := nativeQuiescent()
		if idle && known {
			for ticket, item := range g.tickets {
				if item.ending && g.call("finish", map[string]any{"ticket": ticket}) == nil {
					delete(g.tickets, ticket)
				}
			}
		}
		tickets := make([]string, 0, len(g.tickets))
		for ticket := range g.tickets {
			tickets = append(tickets, ticket)
		}
		_ = g.call("heartbeat", map[string]any{"tickets": tickets, "known": known})
		g.mu.Unlock()
		time.Sleep(3 * time.Second)
	}
}
