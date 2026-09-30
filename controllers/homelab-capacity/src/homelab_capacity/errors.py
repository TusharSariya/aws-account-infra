"""Recovery categories carry sanitized diagnostics, never captured object bodies."""


class RetryObservation(RuntimeError):
    """Re-read state before retrying an idempotent, guarded reconciliation."""


class UncertainShutdown(RuntimeError):
    """A shutdown may have committed; observe completion without repeating it."""
