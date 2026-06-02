"""Latency benchmarks for the full auth flow.

Covers JWT signing, password hashing/verification, and an end-to-end
register → login → me request via the HTTP API.
"""

from __future__ import annotations

import os
import uuid

import pytest

from common.security.jwt import create_token, decode_token
from common.security.password import hash_password, verify_password
from tests._support.benchmark import measure


pytestmark = [pytest.mark.latency, pytest.mark.api]


JWT_ITERS = int(os.environ.get("BENCH_JWT_ITERATIONS", "200"))
# Bcrypt is slow on purpose; cap at a smaller number so the suite stays brisk.
BCRYPT_ITERS = int(os.environ.get("BENCH_BCRYPT_ITERATIONS", "5"))
HTTP_ITERS = int(os.environ.get("BENCH_AUTH_ITERATIONS", "10"))


def test_latency_jwt_create():
    sub = str(uuid.uuid4())
    for _ in range(JWT_ITERS):
        with measure("jwt", "create_token"):
            create_token(sub)


def test_latency_jwt_decode():
    sub = str(uuid.uuid4())
    token = create_token(sub)
    for _ in range(JWT_ITERS):
        with measure("jwt", "decode_token"):
            assert decode_token(token) is not None


def test_latency_bcrypt_hash_and_verify():
    for _ in range(BCRYPT_ITERS):
        with measure("auth", "bcrypt hash_password"):
            h = hash_password("Hunter12345!")
        with measure("auth", "bcrypt verify_password"):
            assert verify_password("Hunter12345!", h)


def test_latency_register_login_me(client):
    """Full HTTP auth round-trip benchmark."""

    for _ in range(HTTP_ITERS):
        suffix = uuid.uuid4().hex[:10]
        email = f"latency+{suffix}@example.com"
        password = "Hunter12345!"
        with measure("auth", "POST /auth/register"):
            r = client.post(
                "/api/v1/auth/register",
                json={
                    "full_name": "Bench User",
                    "email": email,
                    "password": password,
                    "organization": f"Bench Org {suffix}",
                },
            )
            assert r.status_code == 200

        with measure("auth", "POST /auth/login"):
            r = client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": password},
            )
            assert r.status_code == 200
            token = r.json()["access_token"]

        with measure("auth", "GET /auth/me"):
            r = client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
