"""Go-live hardening (surface B): privacy-surface integrity.

Regression tests for three confirmed defects fixed in trellis/surfaces.py:
  * Codex#4  — declassify() accepted an UNAUTHENTICATED approver string, so any
               agent could mint a DM→public token by naming itself.
  * FableL2  — declassification tokens never expired, were infinitely reusable,
               and declassify() never checked flow DIRECTION.
  * Codex#6  — storage_key() was not injective ("-" was both legal field data
               and the missing-value sentinel), risking cross-conversation merges.
"""

from datetime import timedelta

import pytest

from trellis.auth import Principal
from trellis.surfaces import (ConversationKey, PrivacyBoundaryError, Surface,
                              ThreadRef, can_flow, declassify, flow_with_token)


def _key(surface, human="alex", scope="c1", agent="witness:a", thread=None):
    return ConversationKey(agent=agent, surface=surface, scope=scope,
                           human=human, thread=thread)


# ----- Codex#4: declassification is a HUMAN authority, not a caller name ------

def test_agent_cannot_mint_a_declassification_token(ledger):
    """The audit's exact repro: an agent names itself as approver."""
    dm, ch = _key(Surface.DM, human="sarah"), _key(Surface.CHANNEL, human="")
    with pytest.raises(PrivacyBoundaryError):
        declassify(ledger, dm, ch, "witness-agent", reason="agent decided")


def test_unauthenticated_principal_is_refused(ledger):
    dm, ch = _key(Surface.DM, human="sarah"), _key(Surface.CHANNEL, human="")
    with pytest.raises(PrivacyBoundaryError):
        declassify(ledger, dm, ch, Principal("alex", authenticated=False),
                   reason="looks human but never authenticated")


def test_authenticated_human_can_declassify(ledger):
    dm, ch = _key(Surface.DM, human="sarah"), _key(Surface.CHANNEL, human="")
    token = declassify(ledger, dm, ch, Principal("alex", authenticated=True),
                       reason="sarah asked for this excerpt to be posted")
    assert token
    assert flow_with_token(ledger, dm, ch, token) is True


def test_empty_reason_is_refused(ledger):
    dm, ch = _key(Surface.DM, human="sarah"), _key(Surface.CHANNEL, human="")
    with pytest.raises(PrivacyBoundaryError, match="reason"):
        declassify(ledger, dm, ch, Principal("alex", authenticated=True), reason="  ")


# ----- FableL2: tokens expire, are single-use, and only cross DECLASSIFYING ---

def test_token_expires(ledger, clock):
    dm, ch = _key(Surface.DM, human="sarah"), _key(Surface.CHANNEL, human="")
    token = declassify(ledger, dm, ch, Principal("alex", authenticated=True),
                       reason="excerpt ok", ttl=timedelta(minutes=30))
    clock.advance(hours=1)                       # past the token's expiry
    assert flow_with_token(ledger, dm, ch, token) is False


def test_token_is_single_use(ledger):
    dm, ch = _key(Surface.DM, human="sarah"), _key(Surface.CHANNEL, human="")
    token = declassify(ledger, dm, ch, Principal("alex", authenticated=True),
                       reason="one excerpt, once")
    assert flow_with_token(ledger, dm, ch, token) is True    # first use consumes it
    assert flow_with_token(ledger, dm, ch, token) is False   # not reusable


def test_declassify_refuses_a_non_declassifying_direction(ledger):
    # channel (public) -> dm (private) is toward MORE private; can_flow already
    # allows it, so it is not a declassification and must be refused.
    ch, dm = _key(Surface.CHANNEL, human=""), _key(Surface.DM, human="sarah")
    assert can_flow(ch, dm) is True
    with pytest.raises(PrivacyBoundaryError, match="MORE PUBLIC"):
        declassify(ledger, ch, dm, Principal("alex", authenticated=True),
                   reason="wrong direction")


def test_declassify_refuses_same_privacy_level(ledger):
    a, b = _key(Surface.DM, human="sarah"), _key(Surface.DM, human="brett")
    with pytest.raises(PrivacyBoundaryError, match="MORE PUBLIC"):
        declassify(ledger, a, b, Principal("alex", authenticated=True),
                   reason="not more public")


# ----- Codex#6: storage_key() is injective (no "-"/None sentinel collisions) --

def test_empty_human_and_dash_human_do_not_collide():
    broadcast = _key(Surface.CHANNEL, human="")
    dash = _key(Surface.CHANNEL, human="-")
    assert broadcast.storage_key() != dash.storage_key()


def test_no_thread_and_dash_thread_do_not_collide():
    none = _key(Surface.THREAD, thread=None)
    dash = _key(Surface.THREAD, thread=ThreadRef(id="-", parent_channel="c1"))
    assert none.storage_key() != dash.storage_key()


def test_thread_parent_is_part_of_the_key():
    a = _key(Surface.THREAD, thread=ThreadRef(id="t", parent_channel="a"))
    b = _key(Surface.THREAD, thread=ThreadRef(id="t", parent_channel="b"))
    assert a.storage_key() != b.storage_key()   # same id, different parent → distinct


def test_surface_substring_preserved_for_downstream_asserts():
    # test_ingest.py asserts "__dm__" in the key; test_isolation.py asserts the
    # key starts with the agent. Keep those load-bearing substrings intact.
    k = ConversationKey("trellis", Surface.DM, "chan", "sarah").storage_key()
    assert k.startswith("trellis__")
    assert "__dm__" in k


def test_key_stays_filesystem_safe():
    import re
    k = _key(Surface.THREAD, human="x%y", scope="a/b_c",
             thread=ThreadRef(id="t__z", parent_channel="p")).storage_key()
    assert re.fullmatch(r"[A-Za-z0-9%._~-]+", k)
