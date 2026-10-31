"""Stable diagnostics exposed by the phase-1 compatibility runtime."""


class HACompatError(RuntimeError):
    code = "HA_COMPAT_RUNTIME_ERROR"

    def __init__(self, message: str, *, symbol: str | None = None) -> None:
        super().__init__(message)
        self.symbol = symbol


class UnsupportedAPI(HACompatError):
    code = "HA_COMPAT_UNSUPPORTED_API"


class InvalidIntegration(HACompatError):
    code = "HA_COMPAT_INVALID_INTEGRATION"


class DuplicateEntry(HACompatError):
    code = "HA_COMPAT_DUPLICATE_ENTRY"


class IntegrationSetupError(HACompatError):
    code = "HA_COMPAT_SETUP_ERROR"

    def __init__(self, message: str, *, domain: str, phase: str, symbol: str | None = None) -> None:
        super().__init__(message, symbol=symbol)
        self.domain = domain
        self.phase = phase
