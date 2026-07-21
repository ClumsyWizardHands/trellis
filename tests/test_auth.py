"""Authenticated principal (Codex Critical 1): authority is verified, not claimed.

Pins that an authenticated Principal can only come from verifying the secret, that
sessions are tamper-evident and expiring, and that a wrong/forged credential never
authenticates."""

import time

import pytest

from trellis.auth import Authenticator, AuthError, Principal


def _auth():
    return Authenticator("alex", "s3cr3t-token")


def test_right_token_authenticates_wrong_does_not():
    a = _auth()
    p = a.authenticate("s3cr3t-token")
    assert p.authenticated and p.same_as("alex") and p.same_as("ALEX")
    for bad in ("", "wrong", "s3cr3t-toke", None):
        with pytest.raises(AuthError):
            a.authenticate(bad)


def test_a_bare_principal_is_not_authenticated():
    assert Principal("alex").authenticated is False   # only Authenticator mints True


def test_session_roundtrips_and_names_the_human():
    a = _auth()
    cookie = a.issue_session(a.authenticate("s3cr3t-token"))
    p = a.verify_session(cookie)
    assert p is not None and p.authenticated and p.same_as("alex")


def test_a_tampered_session_is_refused():
    a = _auth()
    cookie = a.issue_session(a.authenticate("s3cr3t-token"))
    b64, sig = cookie.rsplit(".", 1)
    # forge the signature, or edit the payload — both must fail
    assert a.verify_session(b64 + "." + ("0" * len(sig))) is None
    import base64
    forged_payload = base64.urlsafe_b64encode(b"mallory.9999999999").decode()
    assert a.verify_session(forged_payload + "." + sig) is None
    assert a.verify_session("garbage") is None
    assert a.verify_session(None) is None


def test_a_session_signed_by_another_secret_is_refused():
    a, b = _auth(), Authenticator("alex", "different-secret")
    cookie = b.issue_session(b.authenticate("different-secret"))
    assert a.verify_session(cookie) is None            # a's secret rejects b's signature


def test_session_expires():
    a = Authenticator("alex", "s")
    a.SESSION_TTL = 0                                   # instant expiry
    cookie = a.issue_session(a.authenticate("s"))
    time.sleep(0.01)
    assert a.verify_session(cookie) is None


def test_ephemeral_authenticator_prints_a_token(monkeypatch):
    monkeypatch.delenv("TRELLIS_APPROVER_SECRET", raising=False)
    monkeypatch.setenv("TRELLIS_HUMAN", "alex")
    a, token = Authenticator.from_env_or_ephemeral()
    assert token and a.authenticate(token).same_as("alex")   # the printed token logs in


def test_configured_secret_needs_no_printed_token(monkeypatch):
    monkeypatch.setenv("TRELLIS_APPROVER_SECRET", "configured")
    monkeypatch.setenv("TRELLIS_HUMAN", "alex")
    a, token = Authenticator.from_env_or_ephemeral()
    assert token is None and a.authenticate("configured").same_as("alex")
