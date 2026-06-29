"""Unit tests for backend/auth_utils.py.

Pure logic — no database, no FastAPI dependency injection.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import pytest
from jose import jwt

# Ensure deterministic JWT secret for tests
os.environ.setdefault("JWT_SECRET", "unit-test-secret")

from auth_utils import (  # noqa: E402
    JWT_ALGORITHM,
    create_access_token,
    decode_access_token,
    hash_password,
    new_verification_token,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_then_verify_roundtrip(self):
        h = hash_password("hunter2")
        assert verify_password("hunter2", h) is True

    def test_wrong_password_rejected(self):
        h = hash_password("hunter2")
        assert verify_password("hunter3", h) is False

    def test_empty_password_raises_on_hash(self):
        with pytest.raises(ValueError):
            hash_password("")

    def test_empty_password_rejected_on_verify(self):
        h = hash_password("hunter2")
        assert verify_password("", h) is False

    def test_truncates_at_72_bytes(self):
        # bcrypt's hard limit is 72 bytes — we should silently truncate, not crash
        long_pw = "a" * 200
        h = hash_password(long_pw)
        assert verify_password(long_pw, h) is True
        # And a different password with the same first 72 chars matches —
        # that's bcrypt behaviour, not a bug we own.
        assert verify_password("a" * 72 + "different", h) is True

    def test_malformed_hash_returns_false_not_exception(self):
        assert verify_password("anything", "not-a-real-hash") is False
        assert verify_password("anything", "") is False

    def test_two_hashes_of_same_password_differ(self):
        # bcrypt salts every hash — same plaintext should never produce same hash
        assert hash_password("hunter2") != hash_password("hunter2")


class TestJWT:
    def test_create_then_decode_roundtrip(self):
        token = create_access_token(user_id=42, email="alice@test.local")
        payload = decode_access_token(token)
        assert payload["sub"] == "42"
        assert payload["email"] == "alice@test.local"
        assert "iat" in payload and "exp" in payload
        assert payload["exp"] > payload["iat"]

    def test_create_with_extra_claims(self):
        token = create_access_token(1, "x@y", extra={"role": "admin"})
        payload = decode_access_token(token)
        assert payload["role"] == "admin"

    def test_tampered_signature_rejected(self):
        token = create_access_token(1, "x@y")
        # Flip the last char to corrupt the signature
        bad = token[:-1] + ("a" if token[-1] != "a" else "b")
        with pytest.raises(Exception):
            decode_access_token(bad)

    def test_expired_token_rejected(self):
        # Forge an expired token using the SAME secret so signing checks pass
        from auth_utils import JWT_SECRET

        expired = jwt.encode(
            {
                "sub": "1",
                "email": "x@y",
                "iat": int((datetime.utcnow() - timedelta(hours=2)).timestamp()),
                "exp": int((datetime.utcnow() - timedelta(hours=1)).timestamp()),
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        with pytest.raises(Exception):
            decode_access_token(expired)

    def test_token_signed_with_different_secret_rejected(self):
        bogus = jwt.encode({"sub": "1"}, "different-secret", algorithm=JWT_ALGORITHM)
        with pytest.raises(Exception):
            decode_access_token(bogus)


class TestVerificationToken:
    def test_token_is_url_safe(self):
        t = new_verification_token()
        # URL-safe base64: only A-Z, a-z, 0-9, -, _
        import re

        assert re.fullmatch(r"[A-Za-z0-9_-]+", t), f"non-urlsafe char in token: {t}"

    def test_tokens_are_unique(self):
        seen = {new_verification_token() for _ in range(500)}
        assert len(seen) == 500, "collision in 500 tokens"

    def test_high_entropy(self):
        # 48 bytes urlsafe → ~64 chars
        assert len(new_verification_token()) >= 60
