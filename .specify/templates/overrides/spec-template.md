# Feature Specification: [FEATURE NAME]

**Feature Branch**: `[###-feature-name]`
**Created**: [DATE]
**Status**: Draft
**Input**: User description: "$ARGUMENTS"

## User Scenarios and Testing

### User Story 1 - [Outcome] (Priority: P1)

[Describe the independently valuable user outcome without prescribing implementation.]

**Independent Test**: [Observable proof of the outcome.]

**Acceptance Scenarios**:

1. **Given** [state], **When** [action], **Then** [observable result].

### Edge Cases

- [Boundary or failure case and expected behavior.]

## Requirements

### Functional Requirements

- **FR-001**: The system MUST [specific, testable capability].

### Safety and Authority Requirements

- **SR-001**: The feature MUST identify the IaC or control-plane owner for every resource.
- **SR-002**: The feature MUST define secret materialization without exposing values.
- **SR-003**: The feature MUST identify immutable identities and permitted lifecycle transitions.
- **SR-004**: Destructive, billable, or live mutations MUST remain behind explicit rollout gates.
- **SR-005**: The feature MUST define checkpoints, recovery, and idempotent retry behavior.

### Key Entities

- **[Entity]**: [Identity, mutable state, relationships, and lifecycle.]

## Non-Goals

- [Explicitly excluded behavior.]

## Live-Mutation Disclosure

- **Performed**: [None, or exact authorized operation and evidence.]
- **Not performed**: [AWS applies, account vending, cluster reconciliation, provider creation, secret retrieval, or other relevant actions.]
- **Rollout gates**: [Current disabled/enabled state and evidence required to change it.]

## Success Criteria

### Measurable Outcomes

- **SC-001**: [Technology-independent, measurable result.]

## Assumptions

- [Explicit assumption, scope boundary, or dependency.]
