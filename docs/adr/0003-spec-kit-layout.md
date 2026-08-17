# ADR 0003: Reserve root specs for Spec Kit

**Status**: Accepted
**Date**: 2026-08-16

## Decision

Numbered feature intent lives at `specs/NNN-feature-name/`. OpenAPI contracts live at
`contracts/openapi/`; design notes remain under `docs/superpowers/specs/`. Spec Kit
v0.16.4 with Codex skills and shell scripts is pinned in root and in the golden service
template. Local template overrides impose infrastructure safety requirements.

## Consequences

Product intent and HTTP contracts no longer collide. Existing SDK paths must move once,
and newly vended repositories receive the same auditable lifecycle.
