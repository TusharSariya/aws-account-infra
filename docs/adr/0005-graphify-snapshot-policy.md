# ADR 0005: Limit Graphify to reviewed PR snapshots

**Status**: Accepted
**Date**: 2026-08-16

## Decision

Graphify v0.9.45 with Terraform and MCP extras is used only for high-risk, point-in-time
pull-request snapshots. Raw JSON and HTML remain ignored audit attachments; a reviewer
commits only a concise map naming versions, analyzed commit, communities, critical paths,
surprises, inferred-edge review, health, and impact results.

## Consequences

The repository avoids two always-on indexes and stale generated source. Snapshot review
cost remains explicit, and reproduction depends on the pinned version and commit SHA.
