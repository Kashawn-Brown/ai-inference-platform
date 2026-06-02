"""Opaque keyset-pagination cursors.

A cursor is just the sort key of the last row on a page, JSON-encoded and
base64'd so callers treat it as an opaque token rather than something to
construct by hand. Keyset (not offset) pagination keeps pages stable as rows
are inserted and stays cheap on the indexed sort columns.
"""

import base64
import binascii
import json


def encode_cursor(data: dict) -> str:
    raw = json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(token: str) -> dict:
    """Decode a cursor token. Raises ValueError on a malformed token."""
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
        data = json.loads(raw)
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise ValueError("malformed cursor") from exc
    if not isinstance(data, dict):
        raise ValueError("malformed cursor")
    return data
