package lifecycle

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestGatewayAuthenticationAdmissionAndContinuation(t *testing.T) {
	var admitted []map[string]any
	controller := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer source" {
			t.Error("incorrect source credential")
		}
		var payload map[string]any
		if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
			t.Fatal(err)
		}
		admitted = append(admitted, payload)
		w.WriteHeader(200)
	}))
	defer controller.Close()
	configured = &gateway{endpoint: controller.URL, token: "source", userToken: "user", workspaceToken: "workspace", pod: "pod", tickets: map[string]*tracked{}, client: controller.Client()}
	defer func() { configured = nil }()
	calls := 0
	handler := Middleware(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++; w.WriteHeader(204) }))
	request := func(method, path, token, parent string) int {
		r := httptest.NewRequest(method, path, nil)
		if token != "" {
			r.Header.Set("Authorization", "Bearer "+token)
		}
		r.Header.Set("X-Homelab-Work", parent)
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		return w.Code
	}
	if request("POST", "/api/generate", "", "") != 401 || calls != 0 {
		t.Fatal("unauthenticated work reached backend")
	}
	if request("GET", "/healthz", "", "") != 200 || calls != 0 || len(admitted) != 0 {
		t.Fatal("health counted as work")
	}
	if request("GET", "/debug/pprof/", "user", "") != 404 {
		t.Fatal("debug route exposed")
	}
	if request("GET", "/api/tags", "user", "") != 204 || len(admitted) != 0 {
		t.Fatal("passive metadata counted")
	}
	if request("POST", "/api/generate", "user", strings.Repeat("a", 32)) != 204 {
		t.Fatal("work rejected")
	}
	if admitted[0]["parent"] != nil {
		t.Fatal("external user forged continuation")
	}
	if request("POST", "/api/pull", "workspace", strings.Repeat("b", 32)) != 204 {
		t.Fatal("workspace rejected")
	}
	if admitted[1]["parent"] != strings.Repeat("b", 32) {
		t.Fatal("workspace continuation lost")
	}
	for _, item := range configured.tickets {
		if !item.ending {
			t.Fatal("returned work not retained for async completion")
		}
	}
}

func TestRejectedAdmissionNeverCallsBackendAndRetainsAmbiguousTicket(t *testing.T) {
	controller := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(503) }))
	defer controller.Close()
	configured = &gateway{endpoint: controller.URL, token: "source", userToken: "user", workspaceToken: "workspace", tickets: map[string]*tracked{}, client: controller.Client()}
	defer func() { configured = nil }()
	handler := Middleware(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { t.Fatal("rejected work reached backend") }))
	r := httptest.NewRequest("POST", "/api/pull", nil)
	r.Header.Set("Authorization", "Bearer user")
	w := httptest.NewRecorder()
	handler.ServeHTTP(w, r)
	if w.Code != 503 || len(configured.tickets) != 1 {
		t.Fatal("ambiguous admission was discarded")
	}
	for _, item := range configured.tickets {
		if !item.ending {
			t.Fatal("failed begin cannot be reconciled")
		}
	}
}

func TestAsyncWorkIsRecordedBeforeExecution(t *testing.T) {
	entered, release, done := make(chan struct{}), make(chan struct{}), make(chan struct{})
	Go(func() { close(entered); <-release; close(done) })
	<-entered
	if work.Load() != 1 {
		t.Fatal("async work not tracked")
	}
	close(release)
	<-done
	// Hold tests synchronous retirement without depending on goroutine teardown timing.
	finish := Hold()
	before := work.Load()
	finish()
	if work.Load() >= before {
		t.Fatal("completed hold retained")
	}
}

func TestIdentityChallengeUsesOnlySourceCredentialAndDoesNotAdmitWork(t *testing.T) {
	configured = &gateway{token: "source", userToken: "user", workspaceToken: "workspace", process: strings.Repeat("b", 32), tickets: map[string]*tracked{}}
	defer func() { configured = nil }()
	handler := Middleware(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { t.Fatal("identity reached model backend") }))
	challenge := strings.Repeat("a", 32)
	for _, token := range []string{"", "user", "workspace", "source"} {
		r := httptest.NewRequest("GET", "/activity-identity?challenge="+challenge, nil)
		r.Header.Set("Authorization", "Bearer "+token)
		w := httptest.NewRecorder()
		handler.ServeHTTP(w, r)
		if token != "source" {
			if w.Code != 401 {
				t.Fatalf("credential %q obtained process identity", token)
			}
			continue
		}
		var payload map[string]string
		if w.Code != 200 || json.Unmarshal(w.Body.Bytes(), &payload) != nil {
			t.Fatal("source probe failed")
		}
		mac := hmac.New(sha256.New, []byte("source"))
		mac.Write([]byte(challenge + ":" + configured.process))
		if payload["process_id"] != configured.process || payload["signature"] != hex.EncodeToString(mac.Sum(nil)) {
			t.Fatal("challenge signature mismatch")
		}
	}
	if len(configured.tickets) != 0 {
		t.Fatal("identity probe counted as work")
	}
}
