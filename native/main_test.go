package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func testServer(t *testing.T) *Server {
	t.Helper()
	root, err := filepath.Abs("..")
	if err != nil {
		t.Fatal(err)
	}
	return &Server{Python: "python3", Home: root, Actions: filepath.Join(root, "actions")}
}

func get(t *testing.T, s *Server, path string) (int, map[string]any) {
	t.Helper()
	req := httptest.NewRequest(http.MethodGet, path, nil)
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, req)
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("GET %s: bad JSON: %v (%s)", path, err, rec.Body.String())
	}
	return rec.Code, body
}

func post(t *testing.T, s *Server, path string, payload any) (int, map[string]any) {
	t.Helper()
	buf, _ := json.Marshal(payload)
	req := httptest.NewRequest(http.MethodPost, path, bytes.NewReader(buf))
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, req)
	var body map[string]any
	if err := json.Unmarshal(rec.Body.Bytes(), &body); err != nil {
		t.Fatalf("POST %s: bad JSON: %v (%s)", path, err, rec.Body.String())
	}
	return rec.Code, body
}

func TestInfo(t *testing.T) {
	code, body := get(t, testServer(t), "/api/info")
	if code != 200 || body["name"] != "asset-manager" {
		t.Fatalf("info: %d %v", code, body)
	}
}

func TestActionsList(t *testing.T) {
	code, body := get(t, testServer(t), "/api/actions")
	if code != 200 {
		t.Fatalf("actions: %d %v", code, body)
	}
	found := false
	for _, a := range body["actions"].([]any) {
		if a.(map[string]any)["id"] == "example::hello-world" {
			found = true
		}
	}
	if !found {
		t.Fatalf("example action missing: %v", body)
	}
}

func TestValidate(t *testing.T) {
	code, body := get(t, testServer(t), "/api/validate")
	if code != 200 || body["valid"] != true {
		t.Fatalf("validate: %d %v", code, body)
	}
}

func TestRunUnknownIs404(t *testing.T) {
	code, _ := post(t, testServer(t), "/api/run",
		map[string]string{"action_id": "no::such"})
	if code != 404 {
		t.Fatalf("expected 404, got %d", code)
	}
}

func TestRunHelloWorld(t *testing.T) {
	target := filepath.Join(t.TempDir(), "shot.png")
	if err := os.WriteFile(target, []byte("x"), 0o644); err != nil {
		t.Fatal(err)
	}
	code, body := post(t, testServer(t), "/api/run",
		map[string]string{"action_id": "example::hello-world", "path": target})
	if code != 200 {
		t.Fatalf("run: %d %v", code, body)
	}
	if !strings.Contains(body["output"].(string), "Hello World") {
		t.Fatalf("missing action output: %v", body)
	}
}

func TestStatusNotACheckoutIs404(t *testing.T) {
	code, _ := get(t, testServer(t), "/api/status?path="+t.TempDir())
	if code != 404 {
		t.Fatalf("expected 404, got %d", code)
	}
}

func TestProjectInit(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "film")
	code, body := post(t, testServer(t), "/api/project-init",
		map[string]string{"directory": dir, "name": "film"})
	if code != 200 {
		t.Fatalf("project-init: %d %v", code, body)
	}
	marker := body["marker"].(string)
	if !strings.HasSuffix(marker, "film.approj") {
		t.Fatalf("bad marker: %v", body)
	}
	if _, err := os.Stat(marker); err != nil {
		t.Fatalf("marker not created: %v", err)
	}
}

func TestProjectInitRequiresFields(t *testing.T) {
	code, _ := post(t, testServer(t), "/api/project-init",
		map[string]string{"name": "x"})
	if code != 400 {
		t.Fatalf("expected 400, got %d", code)
	}
}
