package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
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

func makeGodotProject(t *testing.T) string {
	t.Helper()
	root := t.TempDir()
	if err := os.WriteFile(filepath.Join(root, "project.godot"),
		[]byte("config_version=5\n\n[application]\n\nconfig/name=\"Scan Game\"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, "art"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "art", "hero.png"),
		[]byte("png-bytes"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "art", "hero.png.import"),
		[]byte("[remap]\n\nimporter=\"texture\"\ntype=\"CompressedTexture2D\"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return root
}

func TestScan(t *testing.T) {
	s := testServer(t)
	project := makeGodotProject(t)
	plain := t.TempDir()

	tests := []struct {
		name     string
		query    string
		wantCode int
	}{
		{"valid project", project, 200},
		{"not a godot project", plain, 404},
		{"missing path", "", 400},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			code, body := get(t, s, "/api/scan?path="+tc.query)
			if code != tc.wantCode {
				t.Fatalf("expected %d, got %d (%v)", tc.wantCode, code, body)
			}
			if tc.wantCode != 200 {
				return
			}
			assets, ok := body["assets"].([]any)
			if !ok || len(assets) == 0 {
				t.Fatalf("expected assets, got %v", body)
			}
			paths := map[string]bool{}
			for _, a := range assets {
				entry := a.(map[string]any)
				paths[entry["path"].(string)] = true
				if entry["path"] == "res://art/hero.png" && entry["has_import"] != true {
					t.Fatalf("hero.png should report has_import: %v", entry)
				}
			}
			if !paths["res://art/hero.png"] {
				t.Fatalf("hero.png missing: %v", paths)
			}
			if body["project_name"] != "Scan Game" {
				t.Fatalf("bad project_name: %v", body)
			}
		})
	}
}

func writeTestPNG(t *testing.T, dir, name string) string {
	t.Helper()
	raw, err := base64.StdEncoding.DecodeString(
		"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestThumbnailPNG(t *testing.T) {
	if _, err := exec.LookPath("ffmpeg"); err != nil {
		if _, err2 := exec.LookPath("magick"); err2 != nil {
			t.Skip("no thumbnail engine (ffmpeg/magick) on PATH")
		}
	}
	s := testServer(t)
	src := writeTestPNG(t, t.TempDir(), "hero.png")
	payload, _ := json.Marshal(map[string]string{"source": src})
	req := httptest.NewRequest(http.MethodPost, "/api/thumbnail", bytes.NewReader(payload))
	rec := httptest.NewRecorder()
	s.routes().ServeHTTP(rec, req)
	if rec.Code != 200 {
		t.Fatalf("thumbnail: %d %s", rec.Code, rec.Body.String())
	}
	if ct := rec.Header().Get("Content-Type"); ct != "image/png" {
		t.Fatalf("content-type = %q", ct)
	}
	if magic := rec.Body.Bytes()[:8]; string(magic) != "\x89PNG\r\n\x1a\n" {
		t.Fatalf("not a PNG: %q", magic)
	}
}

func TestThumbnailErrors(t *testing.T) {
	s := testServer(t)
	for _, tc := range []struct {
		name string
		body string
		want int
	}{
		{"missing source", `{"source": ""}`, 400},
		{"no such file", `{"source": "/nonexistent/x.png"}`, 404},
	} {
		t.Run(tc.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/api/thumbnail",
				strings.NewReader(tc.body))
			rec := httptest.NewRecorder()
			s.routes().ServeHTTP(rec, req)
			if rec.Code != tc.want {
				t.Fatalf("got %d, want %d (%s)", rec.Code, tc.want, rec.Body.String())
			}
		})
	}
}
