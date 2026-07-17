"""Phase A — the ingestion spine: idempotent, resumable, correction-aware.

Every determinism finding the plan's stress-test raised is pinned here."""

from datetime import timedelta

from trellis.sources import Ingestor, Provenance, RawItem


def _item(content, item_id="m1", channel="chiefs", source="discord", clock=None,
          machine=False, kind="message"):
    return RawItem(source=source, channel=channel, content=content,
                   event_time=clock.t if clock else None, item_id=item_id,
                   machine_transcribed=machine, kind=kind)


def _harvester_factory(ledger, author="witness"):
    """A stub harvester that writes one derived entry per item and returns its id."""
    def h(item, prov):
        e = ledger.append("derived", author,
                          {"from": item.identity_key(), "content": item.content,
                           "prov": prov.to_dict()})
        return [e.id]
    return h


# ----- identity & content keys -------------------------------------------

def test_idless_items_do_not_collapse(clock):
    """The round's HIGH: message_id='' must not collapse every id-less message
    into one key."""
    a = _item("first thing said", item_id="", clock=clock)
    clock.advance(minutes=1)
    b = _item("a totally different thing", item_id="", clock=clock)
    assert a.identity_key() != b.identity_key()


def test_same_id_different_content_shares_identity_but_not_content_hash(clock):
    a = _item("original text", item_id="msg-42", clock=clock)
    b = _item("corrected text", item_id="msg-42", clock=clock)
    assert a.identity_key() == b.identity_key()        # same item...
    assert a.content_hash() != b.content_hash()        # ...different version


# ----- idempotency, resume, correction -----------------------------------

def test_reingest_is_a_noop(ledger, clock):
    ing = Ingestor(ledger)
    h = _harvester_factory(ledger)
    items = [_item("brett said pricing is settled", clock=clock)]
    r1 = ing.ingest(items, h)
    r2 = ing.ingest(items, h)                          # same items again
    assert r1.processed == 1 and r1.derived_total == 1
    assert r2.processed == 0 and r2.skipped_duplicate == 1
    # exactly one active derived entry — no double count
    assert len([e for e in ledger.active("derived")]) == 1


def test_correction_retires_prior_and_reharvests(ledger, clock):
    ing = Ingestor(ledger)
    h = _harvester_factory(ledger)
    ing.ingest([_item("draft with a typo", item_id="msg-7", clock=clock)], h)
    r = ing.ingest([_item("clean corrected text", item_id="msg-7", clock=clock)], h)
    assert r.corrected == 1
    active = [e for e in ledger.active("derived")]
    assert len(active) == 1 and active[0].body["content"] == "clean corrected text"
    # the prior derived is retired, not deleted (audit intact)
    assert len([e for e in ledger.entries() if e.kind == "derived"]) == 2


def test_resume_after_partial_ingest(ledger, clock):
    """A crash between 'started' and 'complete' must resume cleanly, not double."""
    ing = Ingestor(ledger)
    item = _item("a decision mid-harvest", item_id="msg-9", clock=clock)
    # simulate a crash: write a 'started' marker + a partial derived, no complete
    partial = ledger.append("derived", "witness", {"from": item.identity_key(),
                                                    "content": "PARTIAL"})
    ledger.append("ingest_marker", "ingest",
                  {"identity_key": item.identity_key(), "phase": "started",
                   "content_hash": item.content_hash(), "derived_ids": [partial.id],
                   "source": "discord", "channel": "chiefs"})
    assert ing.status_of(item) == "resume"
    r = ing.ingest([item], _harvester_factory(ledger))
    assert r.resumed == 1
    active = [e for e in ledger.active("derived")]
    assert len(active) == 1 and active[0].body["content"] == "a decision mid-harvest"


# ----- provenance ---------------------------------------------------------

def test_machine_transcription_is_flagged_and_never_launders(clock):
    p_shaky = Provenance(source_refs=("k1",), event_time=clock.t,
                         machine_transcribed=True)
    p_clean = Provenance(source_refs=("k2",), event_time=clock.t,
                         machine_transcribed=False)
    merged = Provenance.merge([p_clean, p_shaky], event_time=clock.t)
    # a summary over a shaky input carries the shakiness — no laundering
    assert merged.machine_transcribed is True
    assert set(merged.source_refs) == {"k1", "k2"}
    assert merged.transcript_fallible is True


def test_transcript_time_is_marked_reconstructed(ledger, clock):
    ing = Ingestor(ledger)
    captured = {}
    def h(item, prov):
        captured["prov"] = prov
        return []
    ing.ingest([_item("meeting words", kind="transcript", clock=clock)], h)
    assert captured["prov"].event_time_reconstructed is True


def test_coverage_reports_honestly(ledger, clock):
    ing = Ingestor(ledger)
    h = _harvester_factory(ledger)
    ing.ingest([_item("a", item_id="1", clock=clock),
                _item("b", item_id="2", source="transcript", machine=True, clock=clock)], h)
    cov = ing.coverage()
    assert cov["items_ingested"] == 2 and cov["machine_transcribed"] == 1
    assert cov["by_source"] == {"discord": 1, "transcript": 1}
