"""Exception hierarchy for all Fantrax interaction.

Every error raised by the adapter layer derives from :class:`FantraxError` so
callers can catch at the ingest-domain boundary without knowing which transport
or endpoint failed.
"""

from __future__ import annotations


class FantraxError(Exception):
    """Base class for all application errors."""


class ConfigError(FantraxError):
    """Missing or invalid configuration."""


class EdgeRejectedError(FantraxError):
    """Request rejected by Fantrax's edge protection (HTTP 403 / Cloudflare 1010).

    Almost always a missing or blocked ``User-Agent`` header. Distinct from
    :class:`AuthError` because retrying with credentials will not help.
    """


class AuthError(FantraxError):
    """The endpoint requires authentication we do not have (secret ID or session)."""


class RateLimitError(FantraxError):
    """HTTP 429. Retryable with backoff."""


class TransientError(FantraxError):
    """HTTP 5xx or network failure. Retryable with backoff."""


class EndpointChangedError(FantraxError):
    """The response shape no longer matches what we validate against."""


class DataIntegrityError(FantraxError):
    """Data passed validation but violates an invariant we rely on."""
