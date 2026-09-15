package lifecycle

import (
	"errors"
	"net/http"
	"os"
	"strings"
)

// ClientDo adds workspace credentials only to the fixed local admission gateway.
// A copy of the client disables redirects without mutating shared client state.
func ClientDo(client *http.Client, request *http.Request) (*http.Response, error) {
	if os.Getenv("HOMELAB_MODEL_TOKEN_FILE") == "" {
		return client.Do(request)
	}
	host := request.URL.Hostname()
	if request.URL.Scheme != "http" || request.URL.Port() != "11434" ||
		(host != "127.0.0.1" && host != "localhost" && host != "ollama.homelab-models.svc") {
		return client.Do(request)
	}
	if os.Getenv("HOMELAB_MODEL_TOKEN_FILE") != "/credentials/model-workspace-token" {
		return nil, errors.New("fixed workspace credential path required")
	}
	data, err := os.ReadFile("/credentials/model-workspace-token")
	if err != nil || len(strings.TrimSpace(string(data))) < 43 {
		return nil, errors.New("workspace model credential unavailable")
	}
	request = request.Clone(request.Context())
	request.Header.Set("Authorization", "Bearer "+strings.TrimSpace(string(data)))
	if parent := os.Getenv("HOMELAB_WORK_ID"); parent != "" {
		request.Header.Set("X-Homelab-Work", parent)
	}
	copy := *client
	copy.CheckRedirect = func(*http.Request, []*http.Request) error { return errors.New("gateway redirect rejected") }
	return copy.Do(request)
}
