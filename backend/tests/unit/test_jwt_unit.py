"""Unit tests for :mod:`common.security.jwt`.

Pure-Python — no DB, no Redis, no HTTP.
"""

from __future__ import annotations

import time
import uuid

import pytest

from common.security.jwt import create_refresh_token, create_token, decode_token


pytestmark = pytest.mark.unit


def test_create_and_decode_access_token_round_trip():
    sub = str(uuid.uuid4())
    token = create_token(sub)
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == sub
    assert "exp" in payload


def test_decode_invalid_token_returns_none():
    assert decode_token("not.a.jwt") is None
    assert decode_token("") is None


def test_refresh_token_carries_type_claim():
    sub = str(uuid.uuid4())
    token = create_refresh_token(sub)
    payload = decode_token(token)
    assert payload is not None
    assert payload["sub"] == sub
    assert payload.get("type") == "refresh"


def test_access_and_refresh_tokens_are_distinct():
    sub = str(uuid.uuid4())
    a = create_token(sub)
    r = create_refresh_token(sub)
    assert a != r


def test_tampered_token_fails_to_decode():
    token = create_token("user-1")
    # Flip the last character of the signature segment.
    head, payload, sig = token.split(".")
    bad = ".".join(
        [head, payload, sig[:-1] + ("A" if sig[-1] != "A" else "B")]
    )
    assert decode_token(bad) is None


def test_token_expiry_is_in_the_future():
    payload = decode_token(create_token("user-x"))
    assert payload is not None
    assert payload["exp"] > int(time.time())
