"""Unit tests for bcrypt password hashing helpers."""

from __future__ import annotations

import pytest

from common.security.password import hash_password, verify_password


pytestmark = pytest.mark.unit


def test_hash_password_returns_bcrypt_value():
    h = hash_password("Hunter12345!")
    assert h.startswith("$2"), "expected a bcrypt hash"
    # Bcrypt hashes have a fixed length around 60 chars.
    assert 55 < len(h) < 80


def test_verify_password_succeeds_for_correct_secret():
    h = hash_password("Hunter12345!")
    assert verify_password("Hunter12345!", h) is True


def test_verify_password_fails_for_wrong_secret():
    h = hash_password("Hunter12345!")
    assert verify_password("Hunter12345?", h) is False


def test_two_hashes_of_same_password_differ_but_both_verify():
    """Salt randomness — same secret should produce two distinct hashes."""

    pw = "Pa55w0rd!Strong"
    a = hash_password(pw)
    b = hash_password(pw)
    assert a != b
    assert verify_password(pw, a)
    assert verify_password(pw, b)
