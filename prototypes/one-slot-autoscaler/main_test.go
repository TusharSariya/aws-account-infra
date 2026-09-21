package main

import (
	"context"
	pb "homelab.example/one-slot-prototype/protos"
	core "k8s.io/api/core/v1"
	"os"
	"path/filepath"
	"syscall"
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

func TestScaleUpRefusedDuringLifecycleOperation(t *testing.T) {
	s := &service{dir: t.TempDir()}
	f, err := os.OpenFile(filepath.Join(s.dir, "lifecycle.lock"), os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		t.Fatal(err)
	}
	defer f.Close()
	if err = syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		t.Fatal(err)
	}
	defer syscall.Flock(int(f.Fd()), syscall.LOCK_UN)
	if _, err = s.NodeGroupIncreaseSize(context.Background(), &pb.NodeGroupIncreaseSizeRequest{Id: group, Delta: 1}); err == nil {
		t.Fatal("raced lifecycle operation")
	}
	n, err := s.readTarget()
	if err != nil || n != 0 {
		t.Fatal("target changed", n, err)
	}
}

func TestTwoSlotsHaveIndependentStateAndIdentity(t *testing.T) {
	m := &multiService{service: &service{dir: t.TempDir()}, primary: &service{dir: t.TempDir(), slot: "primary"}}
	ctx := context.Background()
	groups, err := m.NodeGroups(ctx, &pb.NodeGroupsRequest{})
	if err != nil || len(groups.NodeGroups) != 2 {
		t.Fatal(groups, err)
	}
	if _, err = m.NodeGroupIncreaseSize(ctx, &pb.NodeGroupIncreaseSizeRequest{Id: "prototype-primary", Delta: 1}); err != nil {
		t.Fatal(err)
	}
	primary, _ := m.primary.readTarget()
	secondary, _ := m.service.readTarget()
	if primary != 1 || secondary != 0 {
		t.Fatal(primary, secondary)
	}
	r, err := m.NodeGroupForNode(ctx, &pb.NodeGroupForNodeRequest{Node: &pb.ExternalGrpcNode{ProviderID: "proxmox://prototype-primary/9107"}})
	if err != nil || r.NodeGroup.Id != "prototype-primary" {
		t.Fatal(r, err)
	}
	for _, id := range []string{"proxmox://prototype-primary/9105", "proxmox://prototype-secondary/9107", "proxmox://primary/102"} {
		r, err = m.NodeGroupForNode(ctx, &pb.NodeGroupForNodeRequest{Node: &pb.ExternalGrpcNode{ProviderID: id}})
		if err != nil || r.NodeGroup != nil {
			t.Fatal("foreign identity accepted", id)
		}
	}
	template, err := m.NodeGroupTemplateNodeInfo(ctx, &pb.NodeGroupTemplateNodeInfoRequest{Id: "prototype-primary"})
	if err != nil {
		t.Fatal(err)
	}
	n := &core.Node{}
	if err = n.Unmarshal(template.NodeBytes); err != nil {
		t.Fatal(err)
	}
	if n.Labels["prototype.homelab/pool"] != "workers" || n.Labels["prototype.homelab/csi-worker"] != "false" || n.Spec.ProviderID != "proxmox://prototype-primary/9107" {
		t.Fatal(n)
	}
}
