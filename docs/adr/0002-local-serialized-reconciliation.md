# ADR 0002: Serialize external-provider reconciliation locally

**Status**: Accepted
**Date**: 2026-08-16

## Decision

External-provider changes run from a local operator process with bounded DynamoDB leases,
an append-oriented journal, isolated provider caches, and one backend key per service.
Ordinary pull-request CI never holds provider credentials or mutates provider state.

## Consequences

Retries resume from durable checkpoints and concurrent operators fail closed. Throughput
is intentionally limited, and recovery requires journal inspection before another run.
