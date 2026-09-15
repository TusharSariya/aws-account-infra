package main
import (
 "encoding/json"
 "fmt"
 "os"
 "github.com/google/cel-go/cel"
 "k8s.io/apiserver/pkg/cel/library"
)
type Expression struct {Name string `json:"name"`; Expression string `json:"expression"`}
type Case struct {Name string `json:"name"`; Object any `json:"object"`; OldObject any `json:"oldObject"`; Request any `json:"request"`; Allowed bool `json:"allowed"`}
type Input struct {Variables []Expression `json:"variables"`; Validations []Expression `json:"validations"`; Cases []Case `json:"cases"`}
func main() {
 raw,err:=os.ReadFile(os.Args[1]);must(err); var in Input;must(json.Unmarshal(raw,&in))
 env,err:=cel.NewEnv(cel.Variable("object",cel.DynType),cel.Variable("oldObject",cel.DynType),cel.Variable("request",cel.DynType),cel.Variable("variables",cel.DynType),library.Lists(),library.Quantity());must(err)
 eval:=func(expr string,vars map[string]any)any {ast,issues:=env.Compile(expr);if issues.Err()!=nil {panic(issues.Err())};prog,err:=env.Program(ast);must(err);value,_,err:=prog.Eval(vars);must(err);return value.Value()}
 for _,test:=range in.Cases {
  derived:=map[string]any{}; vars:=map[string]any{"object":test.Object,"oldObject":test.OldObject,"request":test.Request,"variables":derived}
  for _,v:=range in.Variables {derived[v.Name]=eval(v.Expression,vars)}
  allowed:=true
  for _,v:=range in.Validations {if eval(v.Expression,vars)!=true {allowed=false}}
  if allowed!=test.Allowed {panic(fmt.Sprintf("%s allowed=%v expected=%v",test.Name,allowed,test.Allowed))};fmt.Println("PASS:",test.Name)
 }
}
func must(err error) {if err!=nil {panic(err)}}
