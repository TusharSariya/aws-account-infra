package main

import (
	"context"
	pb "homelab.example/one-slot-prototype/protos"
	core "k8s.io/api/core/v1"
	"testing"
)

func TestOnlyOneOwnedSlot(t *testing.T) {
	s := &service{dir: t.TempDir()}
	ctx := context.Background()
	if _, e := s.NodeGroupIncreaseSize(ctx, &pb.NodeGroupIncreaseSizeRequest{Id: "production", Delta: 1}); e == nil {
		t.Fatal("foreign group accepted")
	}
	if _, e := s.NodeGroupIncreaseSize(ctx, &pb.NodeGroupIncreaseSizeRequest{Id: group, Delta: 2}); e == nil {
		t.Fatal("overcapacity accepted")
	}
	if _, e := s.NodeGroupIncreaseSize(ctx, &pb.NodeGroupIncreaseSizeRequest{Id: group, Delta: 1}); e != nil {
		t.Fatal(e)
	}
	if _, e := s.NodeGroupIncreaseSize(ctx, &pb.NodeGroupIncreaseSizeRequest{Id: group, Delta: 1}); e == nil {
		t.Fatal("duplicate accepted")
	}
	r, e := s.NodeGroupTargetSize(ctx, &pb.NodeGroupTargetSizeRequest{Id: group})
	if e != nil || r.TargetSize != 1 {
		t.Fatal(r, e)
	}
	if _, e = s.NodeGroupDeleteNodes(ctx, &pb.NodeGroupDeleteNodesRequest{Id: group}); e == nil {
		t.Fatal("deletion enabled")
	}
}
func TestForeignNodesNotOwned(t *testing.T) {
	s := &service{dir: t.TempDir()}
	for _, id := range []string{"", "proxmox://prototype-secondary/9104", "proxmox://primary/102"} {
		r, e := s.NodeGroupForNode(context.Background(), &pb.NodeGroupForNodeRequest{Node: &pb.ExternalGrpcNode{ProviderID: id}})
		if e != nil || r.NodeGroup != nil {
			t.Fatal("foreign node owned", id)
		}
	}
}
func TestTemplateRoundtrip(t *testing.T) {
	s := &service{dir: t.TempDir()}
	r, e := s.NodeGroupTemplateNodeInfo(context.Background(), &pb.NodeGroupTemplateNodeInfoRequest{Id: group})
	if e != nil {
		t.Fatal(e)
	}
	n := &core.Node{}
	if e = n.Unmarshal(r.NodeBytes); e != nil {
		t.Fatal(e)
	}
	if n.Labels["prototype.homelab/slot"] != "secondary" || n.Status.Allocatable.Cpu().MilliValue() != 1800 {
		t.Fatal("incorrect scheduling template")
	}
}
