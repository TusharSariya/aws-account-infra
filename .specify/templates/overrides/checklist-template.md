# [CHECKLIST TYPE] Checklist: [FEATURE NAME]

**Purpose**: [Review scope]
**Created**: [DATE]
**Feature**: [Link to spec.md]

`[x]` means a reviewer confirmed the requirement-quality criterion; it does not claim
that implementation or a live operation completed.

## Authority and Infrastructure

- [ ] CHK001 IaC ownership and mutation authority are unambiguous.
- [ ] CHK002 State ownership and recovery paths are testable.

## Security and Lifecycle

- [ ] CHK003 Secret resolution, redaction, rotation, and state exposure are specified.
- [ ] CHK004 Immutable identities and allowed lifecycle transitions are explicit.
- [ ] CHK005 Rollout gates default closed and require named evidence.

## Verification and Disclosure

- [ ] CHK006 Requirements map to file, test, or commit evidence.
- [ ] CHK007 Partial, deferred, and blocked work has a reason and enabling condition.
- [ ] CHK008 Live mutations performed and not performed are disclosed explicitly.

## Notes

- Add reviewer findings inline and retain unresolved items unchecked.
