# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]

## Summary

[Primary requirement and chosen technical approach.]

## Technical Context

**Languages and tools**: [Versions and pinned dependencies]
**Storage and state**: [State locations and sensitivity]
**Testing**: [Deterministic checks and live verification boundaries]
**Constraints**: [Availability, security, performance, and compatibility constraints]

## Constitution Check

- [ ] Declarative ownership and authority boundaries are explicit.
- [ ] Secret values cannot enter source, logs, diffs, arguments, or agent context.
- [ ] Immutable identities and forward lifecycle transitions are defined.
- [ ] Live, billable, and destructive rollout gates default closed.
- [ ] Recovery, checkpoints, idempotency, and test evidence are planned.

## Architecture and Authority Boundaries

| Domain | Authority | State owner | Mutation boundary | Recovery path |
| --- | --- | --- | --- | --- |
| [domain] | [owner] | [state] | [who/where] | [procedure] |

## Secret Handling

[Runtime resolution, redaction, state sensitivity, and rotation responsibilities.]

## Identity, Lifecycle, and Rollout Gates

[Immutable keys, allowed transitions, disabled defaults, and evidence required to enable gates.]

## Project Structure

```text
[Concrete feature documentation, source, IaC, and test paths]
```

## Verification and Recovery

[Static checks, isolated tests, live checks requiring separate approval, rollback, and resume points.]

## Complexity Tracking

| Exception | Why needed | Simpler alternative rejected because |
| --- | --- | --- |
| None | N/A | N/A |
