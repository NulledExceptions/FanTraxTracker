"""Adapters: the only package allowed to perform HTTP.

- :mod:`.http` — transport: User-Agent, rate limiting, retry, disk cache, error classification
- :mod:`.official` — Fantrax official REST API (``/fxea/general/``)
- :mod:`.fxpa` — undocumented ``/fxpa/req`` message API (same pattern ``fantraxapi`` uses)
- :mod:`.auth` — session construction for each auth level (none / secret / cookie)
"""
