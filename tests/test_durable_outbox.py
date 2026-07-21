"""The durable outbox (D26 · Codex Critical 3): refusal #5 survives a crash, and
nothing fires twice.

Pins: the outbox reconstructs from the ledger alone (survives a restart with the
FULL payload); fire() is idempotent (a crash-then-retry never double-sends); an
ambiguous executor outcome lands `unknown` and only a human reconciles it; the web
and the outbox share one store (no split-brain)."""

import pytest

from trellis.ledger import Ledger
from trellis.stage import (ActionStatus, DoubleFireError, FireOutcomeUnknown,
                           Outbox, StagedAction, UnapprovedFireError)


def _fresh_outbox(ledger_path, ground):
    """A brand-new process's view: a fresh Outbox over the same ledger file."""
    return Outbox(Ledger(ledger_path, ground), ground)


def test_survives_a_restart_with_full_payload(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("discord_post", "#chiefs",
                                 "the full morning digest, all 900 characters " * 20,
                                 created_by="witness"))
    box.approve(aid, human="alex")
    # DROP the process — a brand-new Outbox reconstructs from the ledger alone
    box2 = _fresh_outbox(path, ground)
    a = box2.get(aid)
    assert a is not None
    assert a.status == ActionStatus.APPROVED           # approval survived the restart
    assert a.content.startswith("the full morning digest")  # FULL payload, not a preview
    assert len(a.content) > 280
    # and it is fireable in the new process
    fired = []
    box2.fire(aid, executor=lambda x: fired.append(x.id))
    assert fired == [aid]


def test_web_approval_is_seen_by_a_fresh_outbox_no_split_brain(tmp_path, ground):
    """The web writes an `approved` staged_action event to the ledger; a fresh
    outbox reading the same store sees it (the split-brain Codex found)."""
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("email_send", "x@y", "draft", created_by="witness"))
    # simulate the web UI's approval write (web/app.py::_record_decision)
    Ledger(path, ground).append(
        kind="staged_action", author="alex",
        body={"action_id": aid, "event": "approved", "status": "approved", "via": "web-ui"},
        tags=("outbox", "approved"))
    box2 = _fresh_outbox(path, ground)
    assert box2.get(aid).status == ActionStatus.APPROVED   # the outbox sees the web's yes


def test_no_double_fire_on_retry_after_a_crash(tmp_path, ground):
    """The remote accepted but the local call 'crashed' — a retry must NOT resend."""
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("discord_post", "#c", "one message", created_by="witness"))
    box.approve(aid, human="alex")
    sends = []
    # the executor sends to the world, then the local process 'crashes' right after
    def flaky(a):
        sends.append(a.idempotency_key)
        raise RuntimeError("local process died after the remote accepted")
    with pytest.raises(FireOutcomeUnknown):
        box.fire(aid, executor=flaky)
    assert len(sends) == 1
    assert box.get(aid).status == ActionStatus.UNKNOWN     # ambiguous, not 'approved'
    # a fresh process retries fire() — it must REFUSE (a firing intent is on record)
    box2 = _fresh_outbox(path, ground)
    with pytest.raises((DoubleFireError, UnapprovedFireError)):
        box2.fire(aid, executor=lambda a: sends.append(a.idempotency_key))
    assert len(sends) == 1                                  # NOT sent twice


def test_unknown_is_reconciled_by_a_human(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("discord_post", "#c", "m", created_by="witness"))
    box.approve(aid, human="alex")
    with pytest.raises(FireOutcomeUnknown):
        box.fire(aid, executor=lambda a: (_ for _ in ()).throw(RuntimeError("blip")))
    assert box.get(aid).status == ActionStatus.UNKNOWN
    # a human checks the world: it DID go out → mark fired, never resend
    box.reconcile(aid, human="alex", fired=True, note="found it in #c")
    assert box.get(aid).status == ActionStatus.FIRED
    # reconciliation is human-gated: the staging agent can't do it
    aid2 = box.stage(StagedAction("discord_post", "#c", "m2", created_by="witness"))
    box.approve(aid2, human="alex")
    with pytest.raises(FireOutcomeUnknown):
        box.fire(aid2, executor=lambda a: (_ for _ in ()).throw(RuntimeError("blip")))
    with pytest.raises(UnapprovedFireError):
        box.reconcile(aid2, human="   ", fired=True)


def test_reconcile_not_sent_returns_to_approved_and_can_fire_once(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("discord_post", "#c", "m", created_by="witness"))
    box.approve(aid, human="alex")
    with pytest.raises(FireOutcomeUnknown):
        box.fire(aid, executor=lambda a: (_ for _ in ()).throw(RuntimeError("blip")))
    # a human checks: it did NOT go out → back to approved, and the reconcile CLEARS
    # the in-flight block so exactly one clean retry is allowed
    box.reconcile(aid, human="alex", fired=False, note="not in the channel")
    assert box.get(aid).status == ActionStatus.APPROVED
    sent = []
    box.fire(aid, executor=lambda a: sent.append(a.id))
    assert sent == [aid] and box.get(aid).status == ActionStatus.FIRED
    # and now it is fired — a further fire is refused (no double-send)
    with pytest.raises(DoubleFireError):
        box.fire(aid, executor=lambda a: sent.append(a.id))
    assert sent == [aid]


def test_cannot_fire_unapproved_or_denied(tmp_path, ground):
    path = tmp_path / "l.jsonl"
    box = Outbox(Ledger(path, ground), ground)
    aid = box.stage(StagedAction("discord_post", "#c", "m", created_by="witness"))
    with pytest.raises(UnapprovedFireError):
        box.fire(aid, executor=lambda a: None)             # never approved
    box.deny(aid, human="alex", reason="no")
    with pytest.raises(UnapprovedFireError):
        box.fire(aid, executor=lambda a: None)             # denied
