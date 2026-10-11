"""Fixed, non-sensitive errors safe to expose at operational boundaries."""


class ContractError(RuntimeError):
    pass


class UpstreamError(RuntimeError):
    pass


class AuthenticationError(UpstreamError):
    pass


class BudgetExceeded(UpstreamError):
    pass


class UnsupportedRule(ContractError):
    pass


class RateLimited(UpstreamError):
    def __init__(self, seconds):
        super().__init__("Zwift rate limited the request")
        self.seconds = seconds


class CursorRejected(ContractError):
    pass


class EventUnavailable(UpstreamError):
    """Historical event metadata is no longer available (HTTP 404)."""
