# ADR 0004: Use RepoWise as the primary local index

**Status**: Accepted
**Date**: 2026-08-16

## Decision

RepoWise v0.43.0 is the sole continuously refreshed local repository index. It runs with
no prose, telemetry, saved keys, editor mutation, generated agent files, or hooks. Its
ignored `.repowise/` database supplies architecture, Terraform, co-change, health,
dead-code, change-risk, and freshness context through user-local MCP registration.

## Consequences

Queries are fast and local, but developers must explicitly initialize and update the
index. Generated pages and risk scores are advisory and cannot replace reviewed source.
