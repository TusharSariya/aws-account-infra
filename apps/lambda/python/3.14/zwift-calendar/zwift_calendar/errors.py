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
