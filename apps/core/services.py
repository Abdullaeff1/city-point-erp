"""Shared service-layer conventions for City Point ERP."""


class DomainError(Exception):
    """Business rule violation (map to 400/409 in APIs later)."""


class Service:
    """Marker base for domain services (stateless callables preferred)."""

    @staticmethod
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise DomainError(message)
