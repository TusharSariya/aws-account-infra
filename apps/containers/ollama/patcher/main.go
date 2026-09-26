// Apply activity hooks only to reviewed functions in the checksum-pinned source.
package main

import (
	"fmt"
	"go/ast"
	"go/format"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

type edit struct {
	start, end int
	value      string
}

func main() {
	if len(os.Args) != 2 {
		panic("source directory required")
	}
	hooks := map[string]map[string]int{
		"server/routes.go":   {"GenerateHandler": 1, "PullHandler": 1, "PushHandler": 1, "ChatHandler": 1, "handleNativeChat": 1},
		"server/create.go":   {"CreateHandler": 1},
		"server/download.go": {"downloadBlob": 1},
		"server/sched.go":    {"useLoadedRunner": 1, "load": 2},
	}
	for path, expected := range hooks {
		filename := filepath.Join(os.Args[1], path)
		data, err := os.ReadFile(filename)
		if err != nil {
			panic(err)
		}
		fs := token.NewFileSet()
		tree, err := parser.ParseFile(fs, filename, data, parser.ParseComments)
		if err != nil {
			panic(err)
		}
		edits := []edit{}
		for _, decl := range tree.Decls {
			fn, ok := decl.(*ast.FuncDecl)
			if !ok {
				continue
			}
			count, wanted := expected[fn.Name.Name]
			if !wanted {
				continue
			}
			found := 0
			ast.Inspect(fn.Body, func(node ast.Node) bool {
				statement, ok := node.(*ast.GoStmt)
				if !ok {
					return true
				}
				found++
				edits = append(edits, edit{fs.Position(statement.Go).Offset, fs.Position(statement.Call.Pos()).Offset, "lifecycle.Go(func() { "}, edit{fs.Position(statement.End()).Offset, fs.Position(statement.End()).Offset, " })"})
				return true
			})
			if found != count {
				panic(fmt.Sprintf("%s %s: expected %d hooks, found %d", path, fn.Name.Name, count, found))
			}
			if fn.Name.Name == "load" {
				offset := fs.Position(fn.Body.Lbrace).Offset + 1
				edits = append(edits, edit{offset, offset, "\n defer lifecycle.Hold()()\n"})
			}
			delete(expected, fn.Name.Name)
		}
		if len(expected) != 0 {
			panic("reviewed function missing")
		}
		sort.Slice(edits, func(i, j int) bool { return edits[i].start > edits[j].start })
		for _, change := range edits {
			data = append(append(append([]byte{}, data[:change.start]...), []byte(change.value)...), data[change.end:]...)
		}
		text := string(data)
		if strings.Count(text, "import (") != 1 {
			panic("unexpected imports")
		}
		text = strings.Replace(text, "import (", "import (\n\"github.com/ollama/ollama/lifecycle\"", 1)
		formatted, err := format.Source([]byte(text))
		if err != nil {
			panic(err)
		}
		if err = os.WriteFile(filename, formatted, 0644); err != nil {
			panic(err)
		}
	}
	replace("server/routes.go", "func Serve(ln net.Listener) error {", "func Serve(ln net.Listener) error {\n if err := lifecycle.Configure(); err != nil { return err }", 1)
	replace("server/routes.go", "Handler: nil,", "Handler: lifecycle.Middleware(http.DefaultServeMux),", 1)
	replace("llm/llama_server.go", "import (", "import (\n \"github.com/ollama/ollama/lifecycle\"", 1)
	replace("llm/llama_server.go", "DisableKeepAlives: true,", "DisableKeepAlives: true,\n DialContext: lifecycle.NativeDial,", 1)
	replace("llm/llama_server.go", "\t// Build CLI flags", "\thost, err := lifecycle.ReserveNative(port)\n if err != nil { return nil, 0, err }\n\t// Build CLI flags", 1)
	replace("llm/llama_server.go", "\"--host\", \"127.0.0.1\",", "\"--host\", host,", 1)
	// The lifecycle quiescence probe reads /slots; llama-server only serves it with --slots.
	replace("llm/llama_server.go", "\"--no-webui\",", "\"--no-webui\",\n\t\t\"--slots\",", 1)
	replace("llm/llama_server.go", "if err = cmd.Start(); err != nil {", "if err = cmd.Start(); err != nil {\n lifecycle.ReleaseNative(port)", 1)
	replace("llm/llama_server.go", "go func(cmd *exec.Cmd, done chan struct{}) {", "go func(cmd *exec.Cmd, done chan struct{}, port int) {", 1)
	replace("llm/llama_server.go", "\t\terr := cmd.Wait()\n\t\ts.doneErr = err", "\t\terr := cmd.Wait()\n lifecycle.ReleaseNative(port)\n\t\ts.doneErr = err", 1)
	replace("llm/llama_server.go", "}(s.cmd, s.done)", "}(s.cmd, s.done, port)", 1)
	replace("api/client.go", "import (", "import (\n \"github.com/ollama/ollama/lifecycle\"", 1)
	replace("api/client.go", "c.http.Do(request)", "lifecycle.ClientDo(c.http, request)", 2)

}

func replace(path, before, after string, count int) {
	filename := filepath.Join(os.Args[1], path)
	data, err := os.ReadFile(filename)
	if err != nil {
		panic(err)
	}
	text := string(data)
	if strings.Count(text, before) != count {
		panic("Pinned source anchor mismatch: " + path)
	}
	text = strings.ReplaceAll(text, before, after)
	formatted, err := format.Source([]byte(text))
	if err != nil {
		panic(err)
	}
	if err = os.WriteFile(filename, formatted, 0644); err != nil {
		panic(err)
	}
}
