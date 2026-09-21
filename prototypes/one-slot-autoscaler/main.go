// Throwaway one-slot scale-up proof. Deletion and host shutdown are disabled.
package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"flag"
	"fmt"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/status"
	pb "homelab.example/one-slot-prototype/protos"
	core "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	meta "k8s.io/apimachinery/pkg/apis/meta/v1"
	"log"
	"net"
	"os"
	"path/filepath"
	"sync"
	"syscall"
)

const group = "prototype-secondary"
const providerID = "proxmox://prototype-secondary/9105"

type service struct {
	pb.UnimplementedCloudProviderServer
	mu  sync.Mutex
	dir string
}
type observed struct {
	Phase string `json:"phase"`
	Name  string `json:"name"`
	Error string `json:"error"`
}

func ng() *pb.NodeGroup {
	return &pb.NodeGroup{Id: group, MinSize: 0, MaxSize: 1, Debug: "isolated prototype VM9105 only"}
}
func (s *service) readTarget() (int32, error) {
	b, e := os.ReadFile(filepath.Join(s.dir, "desired.json"))
	if os.IsNotExist(e) {
		return 0, nil
	}
	if e != nil {
		return 0, e
	}
	var d struct {
		Target int32 `json:"target"`
	}
	e = json.Unmarshal(b, &d)
	return d.Target, e
}
func (s *service) observe() (observed, error) {
	b, e := os.ReadFile(filepath.Join(s.dir, "observed.json"))
	if os.IsNotExist(e) {
		return observed{}, nil
	}
	var o observed
	if e != nil {
		return o, e
	}
	e = json.Unmarshal(b, &o)
	return o, e
}
func (s *service) NodeGroups(context.Context, *pb.NodeGroupsRequest) (*pb.NodeGroupsResponse, error) {
	return &pb.NodeGroupsResponse{NodeGroups: []*pb.NodeGroup{ng()}}, nil
}
func (s *service) NodeGroupForNode(_ context.Context, r *pb.NodeGroupForNodeRequest) (*pb.NodeGroupForNodeResponse, error) {
	if r.Node != nil && r.Node.ProviderID == providerID {
		return &pb.NodeGroupForNodeResponse{NodeGroup: ng()}, nil
	}
	return &pb.NodeGroupForNodeResponse{}, nil
}
func (s *service) GPULabel(context.Context, *pb.GPULabelRequest) (*pb.GPULabelResponse, error) {
	return &pb.GPULabelResponse{}, nil
}
func (s *service) GetAvailableGPUTypes(context.Context, *pb.GetAvailableGPUTypesRequest) (*pb.GetAvailableGPUTypesResponse, error) {
	return &pb.GetAvailableGPUTypesResponse{}, nil
}
func (s *service) Cleanup(context.Context, *pb.CleanupRequest) (*pb.CleanupResponse, error) {
	return &pb.CleanupResponse{}, nil
}
func (s *service) Refresh(context.Context, *pb.RefreshRequest) (*pb.RefreshResponse, error) {
	return &pb.RefreshResponse{}, nil
}
func valid(id string) error {
	if id != group {
		return status.Error(codes.NotFound, "unknown owned node group")
	}
	return nil
}
func (s *service) NodeGroupTargetSize(_ context.Context, r *pb.NodeGroupTargetSizeRequest) (*pb.NodeGroupTargetSizeResponse, error) {
	if e := valid(r.Id); e != nil {
		return nil, e
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	n, e := s.readTarget()
	return &pb.NodeGroupTargetSizeResponse{TargetSize: n}, e
}
func (s *service) NodeGroupIncreaseSize(_ context.Context, r *pb.NodeGroupIncreaseSizeRequest) (*pb.NodeGroupIncreaseSizeResponse, error) {
	if e := valid(r.Id); e != nil {
		return nil, e
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	f, err := os.OpenFile(filepath.Join(s.dir, "lifecycle.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		return nil, err
	}
	defer f.Close()
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return nil, status.Error(codes.Unavailable, "slot lifecycle operation in progress")
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	n, e := s.readTarget()
	if e != nil {
		return nil, e
	}
	if r.Delta != 1 || n != 0 {
		return nil, status.Error(codes.FailedPrecondition, "one slot; only zero-to-one allowed")
	}
	tmp := filepath.Join(s.dir, "desired.tmp")
	if e = os.WriteFile(tmp, []byte("{\"target\":1}\n"), 0600); e != nil {
		return nil, e
	}
	if e = os.Rename(tmp, filepath.Join(s.dir, "desired.json")); e != nil {
		return nil, e
	}
	log.Print("accepted scale-up: prototype-secondary target=1")
	return &pb.NodeGroupIncreaseSizeResponse{}, nil
}
func (s *service) NodeGroupDecreaseTargetSize(context.Context, *pb.NodeGroupDecreaseTargetSizeRequest) (*pb.NodeGroupDecreaseTargetSizeResponse, error) {
	return nil, status.Error(codes.FailedPrecondition, "prototype preserves accepted boot; no cancellation/delete")
}
func (s *service) NodeGroupDeleteNodes(context.Context, *pb.NodeGroupDeleteNodesRequest) (*pb.NodeGroupDeleteNodesResponse, error) {
	return nil, status.Error(codes.PermissionDenied, "deletion disabled in scale-up proof")
}
func (s *service) NodeGroupNodes(_ context.Context, r *pb.NodeGroupNodesRequest) (*pb.NodeGroupNodesResponse, error) {
	if e := valid(r.Id); e != nil {
		return nil, e
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	n, e := s.readTarget()
	if e != nil {
		return nil, e
	}
	if n == 0 {
		return &pb.NodeGroupNodesResponse{}, nil
	}
	o, e := s.observe()
	if e != nil {
		return nil, e
	}
	state := pb.InstanceStatus_instanceCreating
	if o.Phase == "ready" {
		state = pb.InstanceStatus_instanceRunning
	}
	st := &pb.InstanceStatus{InstanceState: state}
	if o.Error != "" {
		st.ErrorInfo = &pb.InstanceErrorInfo{ErrorCode: "ProvisionFailed", ErrorMessage: o.Error}
	}
	return &pb.NodeGroupNodesResponse{Instances: []*pb.Instance{{Id: providerID, Status: st}}}, nil
}
func (s *service) NodeGroupTemplateNodeInfo(_ context.Context, r *pb.NodeGroupTemplateNodeInfoRequest) (*pb.NodeGroupTemplateNodeInfoResponse, error) {
	if e := valid(r.Id); e != nil {
		return nil, e
	}
	node := &core.Node{ObjectMeta: meta.ObjectMeta{Name: "prototype-slot-template", Labels: map[string]string{"kubernetes.io/hostname": "prototype-slot-template", "kubernetes.io/os": "linux", "kubernetes.io/arch": "amd64", "prototype.homelab/slot": "secondary", "topology.kubernetes.io/region": group, "topology.kubernetes.io/zone": "pve", "prototype.homelab/csi-worker": "true"}}, Spec: core.NodeSpec{ProviderID: providerID}, Status: core.NodeStatus{Capacity: core.ResourceList{core.ResourceCPU: resource.MustParse("2"), core.ResourceMemory: resource.MustParse("4Gi"), core.ResourcePods: resource.MustParse("110"), core.ResourceEphemeralStorage: resource.MustParse("18Gi")}, Allocatable: core.ResourceList{core.ResourceCPU: resource.MustParse("1800m"), core.ResourceMemory: resource.MustParse("3Gi"), core.ResourcePods: resource.MustParse("110"), core.ResourceEphemeralStorage: resource.MustParse("15Gi")}, Conditions: []core.NodeCondition{{Type: core.NodeReady, Status: core.ConditionTrue}}}}
	b, e := node.Marshal()
	return &pb.NodeGroupTemplateNodeInfoResponse{NodeBytes: b}, e
}
func main() {
	dir := flag.String("state", "", "private state directory")
	addr := flag.String("listen", "10.0.0.181:50051", "listen address")
	cert := flag.String("cert", "", "server certificate")
	key := flag.String("key", "", "server key")
	ca := flag.String("ca", "", "client CA")
	flag.Parse()
	if *dir == "" || *cert == "" || *key == "" || *ca == "" {
		log.Fatal("state and mTLS files required")
	}
	if e := os.MkdirAll(*dir, 0700); e != nil {
		log.Fatal(e)
	}
	pair, e := tls.LoadX509KeyPair(*cert, *key)
	if e != nil {
		log.Fatal(e)
	}
	roots := x509.NewCertPool()
	pem, e := os.ReadFile(*ca)
	if e != nil || !roots.AppendCertsFromPEM(pem) {
		log.Fatal("invalid client CA")
	}
	server := grpc.NewServer(grpc.Creds(credentials.NewTLS(&tls.Config{Certificates: []tls.Certificate{pair}, ClientCAs: roots, ClientAuth: tls.RequireAndVerifyClientCert, MinVersion: tls.VersionTLS12})))
	pb.RegisterCloudProviderServer(server, &service{dir: *dir})
	l, e := net.Listen("tcp", *addr)
	if e != nil {
		log.Fatal(e)
	}
	fmt.Println("prototype provider listening with mTLS", *addr)
	log.Fatal(server.Serve(l))
}
