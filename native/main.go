// Command assetmgrd is the native Asset-Manager host binary.
//
// It serves the browser web UI and a JSON API, and executes all behaviour
// through the Python action host (`python3 -m assetmgr.cli --json`), which
// remains the single source of truth. Local-only by default: it binds
// loopback unless -addr says otherwise.
package main

import (
	"bytes"
	"embed"
	"encoding/json"
	"flag"
	"fmt"
	"io/fs"
	"log"
	"net/http"
	"os"
	"os/exec"
)

//go:embed all:web
var webFS embed.FS

// Server bridges HTTP to the Python host CLI.
type Server struct {
	Python  string // python interpreter, e.g. "python3"
	Home    string // repo root holding the assetmgr/ package
	Actions string // default --root for action discovery
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// cli runs `python -m assetmgr.cli <sub> <args...> --json` and returns the
// decoded stdout document plus the process exit code.
func (s *Server) cli(sub string, args ...string) (json.RawMessage, int, error) {
	argv := append([]string{"-m", "assetmgr.cli", sub}, args...)
	argv = append(argv, "--json")
	cmd := exec.Command(s.Python, argv...)
	cmd.Dir = s.Home
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr
	err := cmd.Run()
	code := 0
	if exitErr, ok := err.(*exec.ExitError); ok {
		code = exitErr.ExitCode()
	} else if err != nil {
		return nil, 0, err
	}
	var raw json.RawMessage
	if uerr := json.Unmarshal(bytes.TrimSpace(stdout.Bytes()), &raw); uerr != nil {
		return nil, code, fmt.Errorf("bad JSON from host CLI: %v (stderr: %s)", uerr, stderr.String())
	}
	return raw, code, nil
}

func writeRaw(w http.ResponseWriter, status int, raw json.RawMessage) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(raw)
}

func writeErr(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": msg})
}

func decodeBody(w http.ResponseWriter, r *http.Request, dst any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	if err := json.NewDecoder(r.Body).Decode(dst); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid JSON body")
		return false
	}
	return true
}

type projectInitReq struct {
	Directory string `json:"directory"`
	Name      string `json:"name"`
	Force     bool   `json:"force"`
}

type runReq struct {
	ActionID string `json:"action_id"`
	Path     string `json:"path"`
}

func (s *Server) routes() *http.ServeMux {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /api/info", func(w http.ResponseWriter, r *http.Request) {
		raw, _, err := s.cli("info")
		if err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		writeRaw(w, http.StatusOK, raw)
	})

	mux.HandleFunc("GET /api/actions", func(w http.ResponseWriter, r *http.Request) {
		raw, _, err := s.cli("actions", "--root", s.Actions,
			"--scope", r.URL.Query().Get("scope"))
		if err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		writeRaw(w, http.StatusOK, raw)
	})

	mux.HandleFunc("GET /api/validate", func(w http.ResponseWriter, r *http.Request) {
		root := r.URL.Query().Get("root")
		if root == "" {
			root = s.Actions
		}
		raw, _, err := s.cli("validate", "--root", root)
		if err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		writeRaw(w, http.StatusOK, raw)
	})

	mux.HandleFunc("POST /api/project-init", func(w http.ResponseWriter, r *http.Request) {
		var req projectInitReq
		if !decodeBody(w, r, &req) {
			return
		}
		if req.Directory == "" || req.Name == "" {
			writeErr(w, http.StatusBadRequest, "directory and name are required")
			return
		}
		args := []string{req.Directory, "--name", req.Name}
		if req.Force {
			args = append(args, "--force")
		}
		raw, _, err := s.cli("project-init", args...)
		if err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		writeRaw(w, http.StatusOK, raw)
	})

	mux.HandleFunc("POST /api/run", func(w http.ResponseWriter, r *http.Request) {
		var req runReq
		if !decodeBody(w, r, &req) {
			return
		}
		if req.ActionID == "" {
			writeErr(w, http.StatusBadRequest, "action_id is required")
			return
		}
		raw, code, err := s.cli("run", req.ActionID, "--root", s.Actions, "--path", req.Path)
		if err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		switch code {
		case 0:
			writeRaw(w, http.StatusOK, raw)
		case 2:
			writeRaw(w, http.StatusNotFound, raw)
		default:
			writeRaw(w, http.StatusInternalServerError, raw)
		}
	})

	mux.HandleFunc("GET /api/status", func(w http.ResponseWriter, r *http.Request) {
		raw, code, err := s.cli("status", "--path", r.URL.Query().Get("path"))
		if err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		if code != 0 {
			writeRaw(w, http.StatusNotFound, raw)
			return
		}
		writeRaw(w, http.StatusOK, raw)
	})

	mux.HandleFunc("GET /api/scan", func(w http.ResponseWriter, r *http.Request) {
		path := r.URL.Query().Get("path")
		if path == "" {
			writeErr(w, http.StatusBadRequest, "path is required")
			return
		}
		raw, code, err := s.cli("project-scan", path)
		if err != nil {
			writeErr(w, http.StatusInternalServerError, err.Error())
			return
		}
		if code != 0 {
			writeRaw(w, http.StatusNotFound, raw)
			return
		}
		writeRaw(w, http.StatusOK, raw)
	})

	sub, err := fs.Sub(webFS, "web")
	if err != nil {
		log.Fatalf("embedded web UI missing: %v", err)
	}
	mux.Handle("/", http.FileServer(http.FS(sub)))
	return mux
}

func main() {
	addr := flag.String("addr", envOr("ASSETMGR_ADDR", "127.0.0.1:8080"), "listen address")
	python := flag.String("python", envOr("ASSETMGR_PYTHON", "python3"), "python interpreter")
	home := flag.String("home", envOr("ASSETMGR_HOME", "."), "repo root holding assetmgr/")
	actions := flag.String("actions", envOr("ASSETMGR_ACTIONS", ""), "action root (default $home/actions)")
	flag.Parse()
	if *actions == "" {
		*actions = *home + "/actions"
	}
	s := &Server{Python: *python, Home: *home, Actions: *actions}
	log.Printf("assetmgrd serving %s (home=%s actions=%s)", *addr, *home, *actions)
	log.Fatal(http.ListenAndServe(*addr, s.routes()))
}
