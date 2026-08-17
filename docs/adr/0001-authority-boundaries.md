# ADR 0001: Split mutation authority by control plane

**Status**: Accepted
**Date**: 2026-08-16

## Decision

OpenTofu owns AWS and external-provider resources, Ansible owns Kubernetes platform and
tenant lifecycle, Helmfile owns add-on releases, Argo CD owns only its allowlisted tenant
objects, GitHub Actions validates and plans, and protected environments or local
operators perform live mutations.

## Consequences

Every resource has one state owner and recovery path. Cross-plane automation must stop at
an explicit handoff, which adds operator steps but prevents two reconcilers from fighting.
