"""test_onboard.py — the begin-learning ritual (brief §2), fully offline.

The properties pinned (do NOT weaken):

  * CONSENT IS A REAL GATE: before the human's yes, a learning pass reads
    NOTHING — no source is even asked to discover; the refusal is a typed,
    ledgered blocked outcome. The yes and the no are both attributed facts.
  * NEVER ASSUME MEANING: a loaded term becomes a curiosity NODE (folded, not
    forked); its meaning is "known" only after independent verification
    (maker≠verifier) or a human's confirmation. A model-proposed meaning is
    confidence-CAPPED. A term with no evidence yields an honest DRY seek that
    does not advance the question (D22).
  * LINEAGE IS TRACED, deterministically: earliest use, latest use, voices,
    casing shifts — from the record, with provenance folded FLOOR+OR.
  * REFUTED → contested-and-escalated (D35), the question stays open.
  * the map is written with provenance + confidence; "I don't yet understand X"
    is a first-class output; a re-pass FOLDS (no duplicate questions, no
    re-ingestion).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from trellis.curiosity import QUESTION_KIND, QuestionLog, assumption_key
from trellis.ingest import DiscordMessage
from trellis.isolation import (AgentIdentity, Isolation, SurfaceAllowlist,
                               ingest_scoped_discord_idempotent)
from trellis.ledger import Ledger
from trellis.memory import Workspace
from trellis.onboard import (CONSENT_KIND, ONBOARD_SCHEDULE, PASS_KIND,
                             TERM_OBSERVATION_KIND, OnboardingRitual, TermScout,
                             consent_state, confirm_term_meaning,
                             introduction_text, mint_term_curiosities,
                             onboarding_handler, propose_meaning,
                             record_consent, record_term_observation,
                             resolve_term_if_verified, term_assumption,
                             term_from_assumption, term_lineage,
                             verify_term_understanding)
from trellis.panel import VerifierPanel
from trellis.providers.mock import MockProvider
from trellis.registry import IdentityRegistry
from trellis.verify import (CONTESTED_KIND, RuleVerifier, VerdictStatus,
                            contested_items)

CHAN = "chan-main"
_T0 = datetime(2026, 7, 1, 9, 0, 0, tzinfo=timezone.utc)


def _iso():
    return Isolation(identity=AgentIdentity(name="trellis"),
                     allow=SurfaceAllowlist(read=frozenset((CHAN,)),
                                            act=frozenset()))


def _seed_messages(ledger, texts_by_author):
    """Land messages on the ledger through the real scoped idempotent bridge."""
    msgs, i = [], 0
    for author, texts in texts_by_author:
        for t in texts:
            i += 1
            msgs.append(DiscordMessage(
                author=author, content=t, posted_at=_T0 + timedelta(hours=i),
                channel=CHAN, channel_name="main", message_id=str(1000 + i),
                author_id=f"u-{author}"))
    ingest_scoped_discord_idempotent(ledger, msgs, _iso(),
                                     IdentityRegistry(ledger))


EMPIRE_TEXTS = [
    ("brett", ["the empire needs a garden not a factory",
               "every empire decision flows through the ledger",
               "an empire is what you tend, lowercase on purpose"]),
    ("sarah", ["I still think the Empire framing confuses new folks",
               "the empire map helped though"]),
]


def _ritual(ledger, tmp_path, ground, provider=None, verifier=None,
            seed_terms=("empire",), scout=None):
    ws = Workspace(tmp_path / "ws", ledger)
    return OnboardingRitual(ledger, ws, ground=ground, provider=provider,
                            verifier=verifier, registry=IdentityRegistry(ledger),
                            seed_terms=list(seed_terms), scout=scout)


def _grant(ledger):
    record_consent(ledger, "alex", True)


def _panel(ledger, replies):
    prov = MockProvider(id="mock:haiku")
    for r in replies:
        prov.enqueue_text(r)
    return VerifierPanel("onboard-panel", prov, ledger=ledger,
                         rule_verifier=RuleVerifier("onboard-panel:floor", ledger,
                                                    ledger.ground))


# --------------------------------------------------------------------------- #
# 1. introduction + consent — the human gate on starting to learn              #
# --------------------------------------------------------------------------- #

def test_introduction_is_genuine_and_names_the_recording(ledger):
    text = introduction_text(["the Discord history of 2 channels"])
    assert "May I begin?" in text
    assert "recorded" in text                        # the D36 notice
    assert "won't assume" in text or "not assume" in text.replace("won't", "not")


def test_consent_lifecycle_latest_wins(ledger):
    assert consent_state(ledger) == "unasked"
    record_consent(ledger, "alex", True)
    assert consent_state(ledger) == "granted"
    record_consent(ledger, "alex", False, note="changed my mind")
    assert consent_state(ledger) == "declined"       # a human may change their mind


def test_consent_requires_a_real_identity(ledger):
    from trellis.identity import InvalidIdentityError
    with pytest.raises((InvalidIdentityError, ValueError)):
        record_consent(ledger, "   ", True)


def test_learning_pass_reads_nothing_before_consent(ledger, tmp_path, ground):
    class SpyAdapter:
        called = False
        def discover(self):
            SpyAdapter.called = True
            return []

    ritual = _ritual(ledger, tmp_path, ground)
    summary = ritual.learning_pass(sources=[SpyAdapter()])
    assert summary["status"] == "awaiting_consent"
    assert SpyAdapter.called is False                # not even asked to discover
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert ends and ends[-1].body["outcome"] == "blocked"
    assert ends[-1].body.get("on") == "the human's consent to begin learning"


# --------------------------------------------------------------------------- #
# 2. the term scout — loaded terms become curiosity nodes, folded              #
# --------------------------------------------------------------------------- #

def test_scout_finds_seeds_recurring_words_and_phrases():
    texts = []
    for i in range(5):
        texts.append(("brett", f"run the overnight soak again {i}"))
        texts.append(("sarah", f"the overnight soak caught it {i}"))
        texts.append(("clare", f"gruffle is fine {i}"))
        texts.append(("brett", f"gruffle held {i}"))
    scout = TermScout(seed_terms=["empire"], min_count=4, min_authors=2)
    cands = {c.term: c for c in scout.scan(texts)}
    assert "empire" in cands and cands["empire"].signal == "seeded"
    assert "overnight soak" in cands                 # the canonical phrase
    assert cands["overnight soak"].signal == "recurring-phrase"
    assert "gruffle" in cands and cands["gruffle"].signal == "recurring"
    assert "again" not in cands                      # single-author / stopword-ish


def test_scout_records_case_variants_as_a_signal():
    texts = [("brett", "the empire grows"), ("brett", "empire first"),
             ("sarah", "the Empire confuses me"), ("sarah", "empire it is"),
             ("clare", "empire everywhere")]
    scout = TermScout(min_count=4, min_authors=2)
    cands = {c.term: c for c in scout.scan(texts)}
    assert cands["empire"].case_variants == {"empire": 4, "Empire": 1}


def test_minting_folds_instead_of_forking(ledger, ground):
    qlog = QuestionLog(ledger, ground)
    scout = TermScout(seed_terms=["empire"])
    cands = scout.scan([])
    mint_term_curiosities(qlog, cands, "trellis-onboard", ground)
    mint_term_curiosities(qlog, cands, "trellis-onboard", ground)   # re-scan
    open_qs = [q for q in qlog.open_questions()
               if term_from_assumption(q.body.get("assumption", ""))]
    assert len(open_qs) == 1                          # one node, re-asked
    assert open_qs[0].body["reasked"] == 1


# --------------------------------------------------------------------------- #
# 3. lineage — how the meaning came to be                                      #
# --------------------------------------------------------------------------- #

def test_term_lineage_traces_first_latest_voices_and_casing(ledger, ground):
    _seed_messages(ledger, EMPIRE_TEXTS)
    lin = term_lineage(ledger, "empire")
    assert lin.occurrences == 5                       # one per message that uses it
    assert lin.first_use["author"] == "brett"
    assert "garden not a factory" in lin.first_use["excerpt"]
    assert lin.latest_use["author"] == "sarah"
    assert lin.users == ["brett", "sarah"]            # order of first use
    assert lin.case_variants["empire"] == 4 and lin.case_variants["Empire"] == 1
    assert lin.entry_ids                              # openable evidence


def test_lineage_matches_phrases_case_insensitively(ledger, ground):
    _seed_messages(ledger, [("brett", ["the Overnight Soak finished",
                                       "an overnight soak takes a day"])])
    lin = term_lineage(ledger, "overnight soak")
    assert lin.occurrences == 2
    assert set(lin.case_variants) == {"Overnight Soak", "overnight soak"}


def test_lineage_over_many_documents_stays_bounded(ledger, tmp_path, ground):
    """A term used across hundreds of documents must not bloat the observation
    entry or turn the map note into a wall of filenames (found in the live
    rehearsal: 'empire' across 500+ transcripts made a 41KB note)."""
    many = [(f"doc-author-{i}", [f"the empire memo number {i}"])
            for i in range(80)]
    _seed_messages(ledger, many)
    lin = term_lineage(ledger, "empire")
    body = lin.to_body()
    assert len(body["users"]) == 50 and body["users_total"] == 80   # bounded, honest
    assert len(body["entry_ids"]) == 50                             # evidence capped

    ws = Workspace(tmp_path / "ws", ledger)
    qlog = QuestionLog(ledger, ground)
    record_term_observation(ledger, ws, qlog, "empire", lin,
                            author="trellis-onboard", ground=ground)
    note = ws.read("map/terms/empire.md")
    assert "and 72 more" in note                     # 8 shown, the rest counted
    assert len(note) < 4000                          # a readable note, not a dump


# --------------------------------------------------------------------------- #
# 4. the meaning discipline — verified or human-confirmed, never assumed       #
# --------------------------------------------------------------------------- #

def _observed(ledger, ws, qlog, ground, proposed=None):
    _grant(ledger)
    _seed_messages(ledger, EMPIRE_TEXTS)
    mint_term_curiosities(qlog, TermScout(seed_terms=["empire"]).scan([]),
                          "trellis-onboard", ground)
    lin = term_lineage(ledger, "empire")
    return record_term_observation(ledger, ws, qlog, "empire", lin,
                                   author="trellis-onboard", ground=ground,
                                   proposed=proposed)


def test_observation_folds_records_seek_and_caps_model_confidence(
        ledger, tmp_path, ground):
    ws = Workspace(tmp_path / "ws", ledger)
    qlog = QuestionLog(ledger, ground)
    obs = _observed(ledger, ws, qlog, ground,
                    proposed={"meaning": "the tended whole of the team's work",
                              "confidence": 0.99, "unsure": "why lowercase"})
    # curiosity, not confabulation: an unconfirmed model meaning is CAPPED
    assert obs.body["confidence"] == 0.7
    # provenance folded upward, honestly fallible
    assert obs.body["provenance"]["transcript_fallible"] is True

    # the non-dry seek ties the map-move to THIS question (D22)
    seeks = [e for e in ledger.entries() if e.kind == "seek"]
    assert seeks and seeks[-1].body["map_changed"] is True
    assert obs.id in seeks[-1].body["delta_refs"]

    # a re-trace FOLDS onto the same observation node
    lin2 = term_lineage(ledger, "empire")
    obs2 = record_term_observation(ledger, ws, qlog, "empire", lin2,
                                   author="trellis-onboard", ground=ground)
    live = [e for e in ledger.active(TERM_OBSERVATION_KIND)]
    assert len(live) == 1 and live[0].id == obs2.id

    # the map note exists beside it, carrying the confidence
    note = ws.read("map/terms/empire.md")
    assert "confidence" in note and "Lineage" in note


def test_meaning_resolves_only_on_verified(ledger, tmp_path, ground):
    ws = Workspace(tmp_path / "ws", ledger)
    qlog = QuestionLog(ledger, ground)
    obs = _observed(ledger, ws, qlog, ground,
                    proposed={"meaning": "the tended whole", "confidence": 0.6})
    akey = assumption_key(term_assumption("empire"))

    # an INSUFFICIENT panel does NOT close the question
    verdict = verify_term_understanding(
        ledger, obs, "trellis-onboard",
        _panel(ledger, ["INSUFFICIENT\ncannot tell"] * 4))
    assert verdict.status == VerdictStatus.INSUFFICIENT
    assert resolve_term_if_verified(qlog, "empire", obs, verdict,
                                    "trellis-onboard") is False
    assert any(q.body.get("assumption_key") == akey
               for q in qlog.open_questions())        # still open, honestly

    # a VERIFIED panel closes it, citing the pursued observation
    verdict2 = verify_term_understanding(
        ledger, obs, "trellis-onboard",
        _panel(ledger, ["VERIFIED\nthe trace supports the reading"] * 4))
    assert verdict2.status == VerdictStatus.VERIFIED
    assert resolve_term_if_verified(qlog, "empire", obs, verdict2,
                                    "trellis-onboard") is True
    assert not any(q.body.get("assumption_key") == akey
                   for q in qlog.open_questions())


def test_refuted_meaning_is_contested_and_stays_open(ledger, tmp_path, ground):
    ws = Workspace(tmp_path / "ws", ledger)
    qlog = QuestionLog(ledger, ground)
    obs = _observed(ledger, ws, qlog, ground,
                    proposed={"meaning": "a corporate org chart", "confidence": 0.6})
    verdict = verify_term_understanding(
        ledger, obs, "trellis-onboard",
        _panel(ledger, ["REFUTED\nthe uses contradict this reading"] * 4))
    assert verdict.status == VerdictStatus.REFUTED
    # contested + escalated (D35), never deleted; the question stays open
    contested = contested_items(ledger)
    assert any(c["subject_id"] == obs.id for c in contested)
    akey = assumption_key(term_assumption("empire"))
    assert any(q.body.get("assumption_key") == akey
               for q in qlog.open_questions())
    assert resolve_term_if_verified(qlog, "empire", obs, verdict,
                                    "trellis-onboard") is False


def test_human_confirmation_closes_at_high_confidence(ledger, tmp_path, ground):
    ws = Workspace(tmp_path / "ws", ledger)
    qlog = QuestionLog(ledger, ground)
    _observed(ledger, ws, qlog, ground)
    obs = confirm_term_meaning(ledger, ws, qlog, "empire", "alex",
                               "the whole tended system of people + agents",
                               ground)
    assert obs.body["confidence"] == 0.95
    assert obs.body["human_confirmed_by"] == "alex"
    akey = assumption_key(term_assumption("empire"))
    assert not any(q.body.get("assumption_key") == akey
                   for q in qlog.open_questions())


def test_propose_meaning_parses_defensively(ledger, ground, tmp_path):
    _seed_messages(ledger, EMPIRE_TEXTS)
    lin = term_lineage(ledger, "empire")
    good = MockProvider()
    good.enqueue_text(json.dumps({"meaning": "the tended whole",
                                  "confidence": 1.7, "unsure": "casing"}))
    d = propose_meaning(good, "empire", lin, ledger)
    assert d["meaning"] == "the tended whole"
    assert d["confidence"] == 1.0                    # clamped, not trusted raw

    bad = MockProvider()
    bad.enqueue_text("I think it means something!")   # no JSON
    assert propose_meaning(bad, "empire", lin, ledger) is None
    # the excerpts ride inside the data fence (evidence, not instructions)
    assert "«data" in good.calls[0]["messages"][0]["content"]


def test_term_yn_t_grammar_aims_curiosity(ledger, tmp_path, ground):
    """Alex, 2026-07-22: 'not only a yes — a no and a triangulate for any
    confirmation.' N re-explores BLIND (the reason never reaches the prompt);
    T folds the note in as steer (capped 0.8); Y closes at human confidence
    using trellis's own reading when no wording is given."""
    from trellis.onboard import review_term, latest_term_observation
    ws = Workspace(tmp_path / "ws", ledger)
    qlog = QuestionLog(ledger, ground)
    _grant(ledger)
    _seed_messages(ledger, EMPIRE_TEXTS)
    maker = MockProvider(id="mock:s")
    maker.enqueue_text(json.dumps({"meaning": "a corporate hierarchy",
                                   "confidence": 0.6, "unsure": ""}))
    ritual = OnboardingRitual(ledger, ws, ground=ground, provider=maker,
                              registry=IdentityRegistry(ledger),
                              seed_terms=["empire"], day_gate=False)
    ritual.learning_pass(max_terms=1)

    # N — keep digging, reason withheld
    review_term(ledger, ws, qlog, "empire", "no", "alex",
                note="it's the EMP acronym, obviously")
    maker.enqueue_text(json.dumps({"meaning": "a layered team methodology",
                                   "confidence": 0.9, "unsure": ""}))
    ritual.learning_pass(max_terms=1)
    reprompt = maker.calls[-1]["messages"][0]["content"]
    assert "answered NO" in reprompt and "did not say why" in reprompt
    assert "acronym, obviously" not in reprompt        # the reason stays withheld
    obs = latest_term_observation(ledger, "empire")
    assert obs.body["meaning"] == "a layered team methodology"
    assert obs.body["confidence"] == 0.7               # still the unconfirmed cap
    assert "human's NO" in obs.body["meaning_basis"]

    # T — the note steers, and the informed reading may sit at 0.8
    review_term(ledger, ws, qlog, "empire", "triangulate", "alex",
                note="EMP+IRE: Ends/Means/Principles + Identity/Resentments/Emotions")
    maker.enqueue_text(json.dumps({"meaning": "the EMP+IRE identity schema",
                                   "confidence": 0.95, "unsure": ""}))
    ritual.learning_pass(max_terms=1)
    reprompt2 = maker.calls[-1]["messages"][0]["content"]
    assert "TRIANGULATE" in reprompt2 and "Resentments" in reprompt2
    obs2 = latest_term_observation(ledger, "empire")
    assert obs2.body["confidence"] == 0.8              # T-informed cap

    # Y with no wording — trellis's own reading is confirmed, question closes
    review_term(ledger, ws, qlog, "empire", "yes", "alex")
    obs3 = latest_term_observation(ledger, "empire")
    assert obs3.body["confidence"] == 0.95
    assert obs3.body["human_confirmed_by"] == "alex"
    assert obs3.body["meaning"] == "the EMP+IRE identity schema"
    akey = assumption_key(term_assumption("empire"))
    assert not any(q.body.get("assumption_key") == akey
                   for q in qlog.open_questions())


def test_t_note_naming_a_known_term_carries_its_reading(ledger, tmp_path,
                                                        ground):
    """'Go look at X' must arrive WITH X: when a triangulation note mentions a
    term the record already holds a reading for, that reading rides the steer
    (Alex's third cep review, 2026-07-23)."""
    from trellis.onboard import review_term
    ws = Workspace(tmp_path / "ws", ledger)
    qlog = QuestionLog(ledger, ground)
    _grant(ledger)
    _seed_messages(ledger, EMPIRE_TEXTS + [
        ("brett", ["the cep routes context", "cep again", "cep matters",
                   "context expansion protocol is how memory navigates"])])
    maker = MockProvider(id="mock:s")
    for _ in range(4):
        maker.enqueue_text(json.dumps({"meaning": "x", "confidence": 0.5,
                                       "unsure": ""}))
    ritual = OnboardingRitual(ledger, ws, ground=ground, provider=maker,
                              registry=IdentityRegistry(ledger),
                              seed_terms=["cep", "context expansion protocol"],
                              day_gate=False)
    ritual.learning_pass(max_terms=2)      # both terms get first readings
    # give the full phrase a distinct known reading
    from trellis.onboard import confirm_term_meaning
    confirm_term_meaning(ledger, ws, qlog, "context expansion protocol", "alex",
                         "the navigation system that expands context on demand",
                         ground)
    review_term(ledger, ws, qlog, "cep", "triangulate", "alex",
                note="stop searching cep — look at context expansion protocol")
    maker.enqueue_text(json.dumps({"meaning": "short for the protocol",
                                   "confidence": 0.7, "unsure": ""}))
    ritual.learning_pass(max_terms=1)
    prompt = maker.calls[-1]["messages"][0]["content"]
    assert "Readings already on my record" in prompt
    assert "expands context on demand" in prompt     # the known reading rode along


def test_human_teachings_are_standing_not_one_shot(ledger, tmp_path, ground):
    """A T note must ride EVERY future visit, not just the next re-read —
    the live 'I told it three times and it keeps forgetting' bug."""
    from trellis.onboard import review_term
    ws = Workspace(tmp_path / "ws", ledger)
    qlog = QuestionLog(ledger, ground)
    _grant(ledger)
    _seed_messages(ledger, EMPIRE_TEXTS)
    maker = MockProvider(id="mock:s")
    for _ in range(6):
        maker.enqueue_text(json.dumps({"meaning": "some reading",
                                       "confidence": 0.6, "unsure": ""}))
    ritual = OnboardingRitual(ledger, ws, ground=ground, provider=maker,
                              registry=IdentityRegistry(ledger),
                              seed_terms=["empire"], day_gate=False)
    ritual.learning_pass(max_terms=1)
    review_term(ledger, ws, qlog, "empire", "triangulate", "alex",
                note="it is the EMP+IRE acronym")
    ritual.learning_pass(max_terms=1)                 # consumes the review…
    ritual.learning_pass(max_terms=1)                 # …but the teaching STAYS
    ritual.learning_pass(max_terms=1)
    term_calls = [c["messages"][0]["content"] for c in maker.calls
                  if "The term: 'empire'" in c["messages"][0]["content"]]
    for prompt in term_calls[1:]:                     # every visit after the T
        assert "ALREADY told me" in prompt
        assert "EMP+IRE acronym" in prompt
    from trellis.onboard import latest_term_observation
    obs = latest_term_observation(ledger, "empire")
    assert "EMP+IRE acronym" in (obs.body.get("human_note") or "")
    assert obs.body["confidence"] <= 0.8              # standing-notes cap

    # a second teaching ACCUMULATES with the first
    review_term(ledger, ws, qlog, "empire", "triangulate", "alex",
                note="always lowercase, on purpose")
    maker.enqueue_text(json.dumps({"meaning": "r", "confidence": 0.6,
                                   "unsure": ""}))
    ritual.learning_pass(max_terms=1)
    last = [c["messages"][0]["content"] for c in maker.calls
            if "The term: 'empire'" in c["messages"][0]["content"]][-1]
    assert "EMP+IRE acronym" in last and "always lowercase" in last


# --------------------------------------------------------------------------- #
# 5. the full pass — coordinated, idempotent, honest                           #
# --------------------------------------------------------------------------- #

def test_full_learning_pass_maps_verifies_and_surfaces_unknowns(
        ledger, tmp_path, ground):
    _grant(ledger)
    _seed_messages(ledger, EMPIRE_TEXTS)
    maker = MockProvider(id="mock:sonnet")
    maker.enqueue_text(json.dumps({"meaning": "the tended whole of the work",
                                   "confidence": 0.8, "unsure": "the lowercase e"}))
    panel = _panel(ledger, ["VERIFIED\nsupported"] * 4)
    ritual = _ritual(ledger, tmp_path, ground, provider=maker, verifier=panel,
                     seed_terms=("empire", "overnight soak"))

    summary = ritual.learning_pass(max_terms=2)
    assert summary["status"] == "ran"
    assert "empire" in summary["terms_minted"]
    assert "empire" in summary["terms_resolved"]      # traced + verified
    # the unseen phrase got an honest dry seek and STAYS open
    soak = next(p for p in summary["terms_pursued"]
                if p["term"] == "overnight soak")
    assert "dry seek" in soak["outcome"]
    assert summary["open_unknowns"] >= 1

    # the map exists, with the unknowns note as a first-class output
    unknowns = ritual.workspace.read("map/unknowns.md")
    assert "overnight soak" in unknowns
    people = ritual.workspace.read("map/people.md")
    assert "brett" in people.lower()
    # the pass is on the record with a typed ok outcome
    passes = [e for e in ledger.entries() if e.kind == PASS_KIND]
    assert passes and passes[-1].body["status"] == "ran"
    ends = [e for e in ledger.entries() if e.kind == "loop_run_end"]
    assert ends[-1].body["outcome"] == "ok"


def test_repeat_pass_folds_no_duplicates(ledger, tmp_path, ground):
    _grant(ledger)
    _seed_messages(ledger, EMPIRE_TEXTS)
    ritual = _ritual(ledger, tmp_path, ground, seed_terms=("empire",))
    ritual.learning_pass(max_terms=1)
    open_before = len(ritual.qlog.open_questions())
    obs_before = len(ledger.active(TERM_OBSERVATION_KIND))

    ritual.learning_pass(max_terms=1)                 # the daily re-run
    assert len(ritual.qlog.open_questions()) == open_before
    assert len(ledger.active(TERM_OBSERVATION_KIND)) == obs_before   # folded


def test_pass_without_verifier_leaves_meaning_unresolved(ledger, tmp_path, ground):
    _grant(ledger)
    _seed_messages(ledger, EMPIRE_TEXTS)
    ritual = _ritual(ledger, tmp_path, ground, seed_terms=("empire",))
    summary = ritual.learning_pass(max_terms=1)
    assert summary["terms_resolved"] == []            # no self-certification
    pursued = summary["terms_pursued"][0]
    assert "open" in pursued["outcome"]


def test_broken_source_is_reported_not_fatal(ledger, tmp_path, ground):
    _grant(ledger)

    class BrokenAdapter:
        def discover(self):
            raise RuntimeError("awaiting the human's grant")

    ritual = _ritual(ledger, tmp_path, ground, seed_terms=())
    summary = ritual.learning_pass(sources=[BrokenAdapter()])
    assert summary["status"] == "ran"                 # the pass survived
    assert summary["awaiting"] and "grant" in summary["awaiting"][0]["why"]


# --------------------------------------------------------------------------- #
# 6. pace + the temporal wave — ingested is not understood; presence decays    #
# --------------------------------------------------------------------------- #

def test_comprehension_separates_ingested_from_understood(ledger, tmp_path,
                                                          ground):
    from trellis.onboard import comprehension
    _grant(ledger)
    _seed_messages(ledger, EMPIRE_TEXTS)                 # 5 corpus items
    comp0 = comprehension(ledger)
    assert comp0["ingested"] == 5 and comp0["walked"] == 0   # swallowed ≠ walked

    ritual = _ritual(ledger, tmp_path, ground, seed_terms=("empire",))
    summary = ritual.learning_pass(max_terms=1)
    comp = summary["comprehension"]
    assert 0 < comp["walked"] <= comp["ingested"]
    assert comp["terms_open"] >= 1 and comp["terms_known"] == 0
    # the honest ratio is rendered where humans look
    surfaces_note = ritual.workspace.read("map/surfaces.md")
    assert "ingested is NOT understood" in surfaces_note


def test_quiet_voice_becomes_a_question_never_a_conclusion(ledger, tmp_path,
                                                           ground, clock):
    from trellis.onboard import mint_presence_curiosities, write_map_overview
    from trellis.curiosity import QuestionLog
    # sarah spoke months ago and went quiet; brett is current
    _seed_messages(ledger, [("sarah", ["old note one", "old note two",
                                       "old note three"])])
    clock.advance(days=200)
    fresh = [DiscordMessage(
                 author="brett", content=f"fresh word {i}",
                 posted_at=ground.now() - timedelta(hours=3 - i), channel=CHAN,
                 channel_name="main", message_id=str(2000 + i),
                 author_id="u-brett")
             for i in range(3)]
    ingest_scoped_discord_idempotent(ledger, fresh, _iso(),
                                     IdentityRegistry(ledger))
    qlog = QuestionLog(ledger, ground)
    minted = mint_presence_curiosities(ledger, qlog, "trellis-onboard", ground)
    titles = [m.body["title"] for m in minted]
    assert titles == ["Is sarah still an active voice here?"]   # asked, not asserted
    assert "presence" in minted[0].body["assumption"]
    # folding: a re-scan re-asks the SAME node, no duplicate
    minted2 = mint_presence_curiosities(ledger, qlog, "trellis-onboard", ground)
    assert minted2[0].body["reasked"] == 1
    assert len([q for q in qlog.open_questions()
                if "presence" in q.body.get("assumption", "")]) == 1

    # the people map shows recency and frames dormancy as an open question
    ws = Workspace(tmp_path / "ws", ledger)
    write_map_overview(ledger, ws, IdentityRegistry(ledger), qlog,
                       "trellis-onboard", ground)
    people = ws.read("map/people.md")
    assert "last heard" in people
    assert "OPEN QUESTION" in people                    # sarah's dormancy
    assert "never a departure I am asserting" in people


def test_checkin_note_folds_and_digest_stages_only_on_real_news(
        ledger, tmp_path, ground):
    from trellis.stage import Outbox
    from trellis.isolation import AgentIdentity, Isolation, SurfaceAllowlist
    _grant(ledger)
    _seed_messages(ledger, EMPIRE_TEXTS)
    iso = Isolation(identity=AgentIdentity(name="trellis"),
                    allow=SurfaceAllowlist(read=frozenset((CHAN,)),
                                           act=frozenset(("chan-checkin",))))
    ws = Workspace(tmp_path / "ws", ledger)
    maker = MockProvider(id="mock:sonnet")
    maker.enqueue_text(json.dumps({"meaning": "the tended whole",
                                   "confidence": 0.8, "unsure": ""}))
    panel = _panel(ledger, ["VERIFIED\nsupported"] * 4)
    ritual = OnboardingRitual(ledger, ws, ground=ground, provider=maker,
                              verifier=panel, registry=IdentityRegistry(ledger),
                              seed_terms=["empire"],
                              outbox=Outbox(ledger, iso=iso),
                              checkin_target="chan-checkin")

    summary = ritual.learning_pass(max_terms=1)
    # a resolution is real news → the digest is STAGED (never fired)
    assert summary["terms_resolved"] == ["empire"]
    assert summary.get("checkin_staged")
    staged = [e for e in ledger.entries() if e.kind == "staged_action"]
    assert staged and staged[-1].body["status"] == "staged"
    assert "Check-in" in staged[-1].body["content"]
    assert not any("fir" in e.kind for e in ledger.entries())
    # the note exists and folds per day
    note = ws.read(summary["checkin"])
    assert "Newly settled" in note and "many sessions" in note

    # a quiet pass (nothing settled, nothing contested) stages NO digest
    n_staged = len(staged)
    summary2 = ritual.learning_pass(max_terms=1)
    assert not summary2.get("checkin_staged")
    assert len([e for e in ledger.entries()
                if e.kind == "staged_action"]) == n_staged
    # but the day's note still folded to the latest state (one active write)
    checkins = [e for e in ledger.active("memory_write")
                if e.body.get("path", "").startswith("map/checkins/")]
    assert len(checkins) == 1


def test_onboarding_handler_runs_under_the_runner(ledger, tmp_path, ground):
    from datetime import timedelta as td
    from trellis.runner import Runner
    _grant(ledger)
    _seed_messages(ledger, EMPIRE_TEXTS)
    ritual = _ritual(ledger, tmp_path, ground, seed_terms=("empire",))
    handler = onboarding_handler(ritual, max_terms=1)
    runner = Runner(ledger, ground)
    specs = Runner.DEFAULT_SCHEDULES + (
        (ONBOARD_SCHEDULE, td(minutes=30), "the onboarding learning ritual"),)

    report = runner.tick(handlers={ONBOARD_SCHEDULE: handler}, specs=specs)
    fired = dict(report["fired"])
    assert fired.get(ONBOARD_SCHEDULE) == "ok"
    assert any(e.kind == PASS_KIND for e in ledger.entries())
