"""Pure analytics over Fantrax payloads.

Every function here takes already-fetched JSON (dicts/lists) or the dataclasses built from it and
returns dataclasses. No I/O, no HTTP, no SQL. The parsers are deliberately tolerant: Fantrax table
payloads are UI-shaped (``header.cells`` + ``rows[].cells``), so each module keys on the header
rather than on column positions.
"""
