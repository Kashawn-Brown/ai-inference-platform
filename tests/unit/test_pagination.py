"""Unit tests for the opaque keyset-pagination cursors."""

import base64
import json

import pytest

from aiinfra.gateway.pagination import decode_cursor, encode_cursor


def test_round_trips_arbitrary_keys():
    data = {"created_at": "2026-06-02T00:00:00+00:00", "id": "abc-123"}

    assert decode_cursor(encode_cursor(data)) == data


def test_encode_is_opaque_and_url_safe():
    token = encode_cursor({"item_index": 5})

    # No characters that would need escaping in a query string.
    assert "/" not in token and "+" not in token


@pytest.mark.parametrize("bad", ["not-base64!!", "", "@@@@"])
def test_decode_rejects_malformed_tokens(bad):
    with pytest.raises(ValueError):
        decode_cursor(bad)


def test_decode_rejects_non_object_payload():
    # Valid base64 of a JSON array — decodes, but isn't a cursor dict.
    list_token = base64.urlsafe_b64encode(json.dumps([1, 2]).encode()).decode()

    with pytest.raises(ValueError):
        decode_cursor(list_token)
