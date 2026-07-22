"""onboard.py — the begin-learning ritual: introduce, ask, then MAP the place.

trellis is a mapper and an understander, not a task-completing assistant (D12);
this module is the purest expression of that identity, run once when trellis
arrives somewhere new and then quietly forever after. The shape:

  1. INTRODUCE + CONSENT (a human gate on *starting to learn*, not on each
     thought — D33's grain). Nothing is read before the yes; the yes and the no
     are both ledger facts.
  2. NEVER ASSUME MEANING. A loaded, recurring, or idiosyncratic term — the
     canonical "an overnight soak", or "empire" with a deliberate lowercase e —
     becomes a CURIOSITY NODE (curiosity.py), never a silent assumption. The
     discipline is structural: a meaning is "known" only when its traced
     lineage is independently verified (convene_verification, maker≠verifier)
     or a human confirms it. A dry search never closes a question (D22).
  3. TRACE COGNITIVE LINEAGE. For each term the ritual walks HOW the meaning
     came to be — earliest use, most recent use, who used it, how the casing
     and context shifted — deterministically, from the record, with provenance.
  4. MAP, DON'T COMPLETE. The output is a navigable knowledge base (workspace/
     vault notes under map/) of what everything here IS — people, surfaces,
     terms, coverage — each entry carrying provenance and confidence, with an
     honest "I don't yet understand X" note as a first-class output. The
     stopping condition is the Witness's, adapted: "I have mapped what is here
     and put my uncertainties on the record" — never "the task is done."

Everything rides existing primitives: sources.Ingestor (idempotent spine),
curiosity.QuestionLog (teeth), verify.convene_verification + panel.VerifierPanel
(refute-by-default Haiku seats), memory.Workspace / vault (the navigable face),
loops.LoopRun (typed outcomes), runner schedules (background, resumable). This
module adds only the ritual and the term discipline — no core is rewritten.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Iterable, List, Optional

from .clock import TimeGround
from .curiosity import (QUESTION_KIND, NotResolvedError, Question, QuestionLog,
                        assumption_key)
from .decisions import question_key
from .identity import require_identity
from .ledger import Entry, Ledger
from .loops import BlockKind, LoopRegistry, LoopRun, LoopSpec
from .memory import Workspace
from .prompt import fence_untrusted
from .sources import Ingestor, Provenance
from .transcripts import SOURCE_DOCUMENT_KIND, document_harvester
from .verify import (CompletionClaim, Evidence, EvidenceKind, VerdictStatus,
                     convene_verification)

CONSENT_KIND = "onboard_consent"
STAGE_KIND = "onboard_stage"
DAY_DIGEST_KIND = "day_digest"
DAY_REVIEW_KIND = "day_review"
INTRO_KIND = "onboard_introduction"
PASS_KIND = "onboard_pass"
TERM_OBSERVATION_KIND = "term_observation"

#: the schedule name the runner drives — one initialize command, then background.
ONBOARD_SCHEDULE = "onboard.learn"

#: a model-proposed meaning is capped here until a human confirms it or an
#: independent panel verifies the trace — curiosity, not confabulation.
MODEL_MEANING_CONFIDENCE_CAP = 0.7
HUMAN_CONFIRMED_CONFIDENCE = 0.95
TRACE_ONLY_CONFIDENCE = 0.6


# ---------------------------------------------------------------------------
# 1. introduction + consent — the human gate on starting to learn
# ---------------------------------------------------------------------------


def introduction_text(sources_desc: Optional[List[str]] = None) -> str:
    """The first thing anyone sees. A genuine introduction, not a banner: who
    this is, what it wants to do, what it will read, and the recording notice
    (D36) — followed by the actual ask."""
    lines = [
        "Hello — I'm trellis.",
        "",
        "I'd like to begin exploring and learning about this place — its people,",
        "its decisions, and what things here mean. I won't assume I know what a",
        "word means just because I've seen it elsewhere: when I meet a term that",
        "seems loaded or particular to you, I'll say so, trace how you actually",
        "use it, and check my reading before I trust it. What I can't yet",
        "understand, I'll put on the record as an open question rather than",
        "papering over it.",
        "",
        "I map; I don't complete tasks. Nothing I write leaves this machine",
        "without your explicit yes.",
    ]
    if sources_desc:
        lines += ["", "If you say yes, I would read:"]
        lines += [f"  - {s}" for s in sources_desc]
    lines += [
        "",
        "One thing you should know before answering: everything I read and",
        "everything said to me is recorded in my ledger, within sessions —",
        "anyone who talks with me is on the record.",
        "",
        "May I begin?",
    ]
    return "\n".join(lines)


def record_introduction(ledger: Ledger, author: str, text: str,
                        staged_action_id: Optional[str] = None) -> Entry:
    return ledger.append(
        kind=INTRO_KIND, author=author,
        body={"text": text, "staged_action_id": staged_action_id},
        tags=("onboard", "introduction"))


def record_consent(ledger: Ledger, human: str, granted: bool,
                   note: str = "") -> Entry:
    """The human's answer, attributed and durable. A blank/homoglyph identity is
    refused at the gate like every human seat."""
    human = require_identity(human, "consenting human")
    return ledger.append(
        kind=CONSENT_KIND, author=human,
        body={"granted": bool(granted), "note": note},
        tags=("onboard", "consent", "granted" if granted else "declined"))


def consent_state(ledger: Ledger) -> str:
    """'unasked' | 'granted' | 'declined' — the latest consent entry wins
    (a human may change their mind; the record keeps both)."""
    latest: Optional[Entry] = None
    for e in ledger.entries():
        if e.kind == CONSENT_KIND:
            latest = e
    if latest is None:
        return "unasked"
    return "granted" if latest.body.get("granted") else "declined"


# ---------------------------------------------------------------------------
# 2. the term scout — where "never assume meaning" gets teeth
# ---------------------------------------------------------------------------

#: compact common-word set — enough to keep ordinary English from flooding the
#: candidate list. This is a heuristic FILTER, not a semantic judgment; the
#: judgment happens in pursuit + verification.
_STOPWORDS = frozenset("""
a about above after again all almost also always am an and any are around as at
back be because been before being below between both but by came can cannot come
could day did do does doing done down during each even every few first for from
get give go going good got great had has have he her here hers him his how i if
in into is it its just know last like little long look made make many may me
might more most much must my need never new no not now of off on once one only
or other our out over own people put right said same say see she should since so
some still such take than that the their them then there these they thing think
this those through time to too two under up us use very want was way we well
were what when where which while who why will with without work would year yes
yet you your really actually going gonna them they're we're i'm it's don't
didn't doesn't can't won't that's there's what's let's things something anything
everything nothing someone anyone everyone thanks thank please sure okay ok yeah
today tomorrow yesterday week month
""".split())

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'\-]{2,}")


@dataclass
class TermCandidate:
    term: str                      # the folded (lowercase) term or phrase
    count: int
    authors: List[str]
    case_variants: dict            # exact-casing → count (the lowercase-e signal)
    signal: str                    # "seeded" | "recurring" | "recurring-phrase"


class TermScout:
    """Deterministic detection of loaded/recurring/idiosyncratic terms.

    Honest scope: this is a frequency-and-casing heuristic plus a human seed
    list — it finds RECURRING vocabulary worth asking about; it cannot judge
    which single-use phrase is loaded. The seed list (`TRELLIS_ONBOARD_TERMS` /
    the `seed_terms` argument) is how a human points at "an overnight soak"
    directly; the scan catches what recurs on its own."""

    def __init__(self, seed_terms: Optional[Iterable[str]] = None,
                 min_count: int = 4, min_authors: int = 2,
                 max_candidates: int = 12):
        self.seed_terms = [t.strip() for t in (seed_terms or []) if t.strip()]
        self.min_count = min_count
        self.min_authors = min_authors
        self.max_candidates = max_candidates

    def scan(self, texts: Iterable[tuple]) -> List[TermCandidate]:
        """`texts` is (author, content) pairs. Returns seeded candidates first
        (always), then recurring words/phrases by frequency, capped."""
        word_count: dict = {}
        word_authors: dict = {}
        word_case: dict = {}
        bigram_count: dict = {}
        bigram_authors: dict = {}
        for author, content in texts:
            tokens = _TOKEN_RE.findall(content or "")
            folded = [t.lower() for t in tokens]
            for raw, tok in zip(tokens, folded):
                if tok in _STOPWORDS or len(tok) < 4:
                    continue
                word_count[tok] = word_count.get(tok, 0) + 1
                word_authors.setdefault(tok, set()).add(author)
                word_case.setdefault(tok, {})
                word_case[tok][raw] = word_case[tok].get(raw, 0) + 1
            for i in range(len(folded) - 1):
                a, b = folded[i], folded[i + 1]
                if a in _STOPWORDS or b in _STOPWORDS:
                    continue
                if len(a) < 3 or len(b) < 3:
                    continue
                phrase = f"{a} {b}"
                bigram_count[phrase] = bigram_count.get(phrase, 0) + 1
                bigram_authors.setdefault(phrase, set()).add(author)

        out: List[TermCandidate] = []
        seen: set = set()
        for term in self.seed_terms:
            key = term.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(TermCandidate(
                term=key, count=word_count.get(key, 0) or bigram_count.get(key, 0),
                authors=sorted(word_authors.get(key, bigram_authors.get(key, set()))),
                case_variants=word_case.get(key, {}), signal="seeded"))

        # phrases first (a recurring two-word phrase is a stronger "loaded" signal
        # than either word alone), then words, both by frequency.
        scored_phrases = sorted(
            ((c, p) for p, c in bigram_count.items()
             if c >= self.min_count and len(bigram_authors[p]) >= self.min_authors),
            key=lambda x: (-x[0], x[1]))
        scored_words = sorted(
            ((c, w) for w, c in word_count.items()
             if c >= self.min_count and len(word_authors[w]) >= self.min_authors),
            key=lambda x: (-x[0], x[1]))
        for count, phrase in scored_phrases:
            if len(out) >= self.max_candidates:
                break
            if phrase in seen:
                continue
            # skip a phrase whose words both surface independently anyway —
            # prefer the phrase (it carries the idiom) and drop the parts below.
            seen.add(phrase)
            out.append(TermCandidate(
                term=phrase, count=count,
                authors=sorted(bigram_authors[phrase]),
                case_variants={}, signal="recurring-phrase"))
        phrase_words = {w for _, p in scored_phrases for w in p.split()}
        for count, word in scored_words:
            if len(out) >= self.max_candidates:
                break
            if word in seen or word in phrase_words:
                continue
            seen.add(word)
            out.append(TermCandidate(
                term=word, count=count, authors=sorted(word_authors[word]),
                case_variants=word_case.get(word, {}), signal="recurring"))
        return out


def term_assumption(term: str) -> str:
    """The stable assumption a term-curiosity targets. One shape, so a reworded
    curiosity about the same term folds onto the same node (anti-fork)."""
    return f"the meaning of the term '{term.strip().lower()}' in this record"


_ASSUMPTION_TERM_RE = re.compile(r"the meaning of the term '(.+)' in this record")


def term_from_assumption(assumption: str) -> Optional[str]:
    m = _ASSUMPTION_TERM_RE.search(assumption or "")
    return m.group(1) if m else None


def mint_term_curiosities(qlog: QuestionLog, candidates: List[TermCandidate],
                          author: str, ground: TimeGround,
                          revisit_days: int = 3) -> List[Entry]:
    """One curiosity node per candidate term. QuestionLog.ask folds a re-mint
    onto the existing node (a re-ask), so a daily re-scan never inflates the
    open set — the anti-fork is the QuestionLog's, reused."""
    out = []
    now = ground.now()
    for c in candidates:
        casing = ""
        if len(c.case_variants) > 1:
            casing = (" I keep seeing it cased differently ("
                      + ", ".join(f"{k}×{v}" for k, v in
                                  sorted(c.case_variants.items())) + ") — "
                      "that may be deliberate.")
        q = Question(
            title=f"What does '{c.term}' mean here?",
            assumption=term_assumption(c.term),
            what_would_resolve=(
                "trace its earliest and most recent uses, who uses it, and how "
                "it shifted; then either an independent verification of that "
                "traced reading or a human's confirmation." + casing),
            owner=author,
            revisit_at=now + timedelta(days=revisit_days))
        out.append(qlog.ask(q, author=author))
    return out


# ---------------------------------------------------------------------------
# 3. cognitive lineage — how the meaning came to be, from the record
# ---------------------------------------------------------------------------


def _corpus(ledger: Ledger) -> List[Entry]:
    """The readable record: live discord messages + source documents, oldest
    first by event_time. Routed through active() so a corrected/retired item
    never feeds a lineage."""
    entries = ledger.active("discord_message") + ledger.active(SOURCE_DOCUMENT_KIND)
    entries.sort(key=lambda e: e.stamp.event_time)
    return entries


def _excerpt(content: str, match_start: int, radius: int = 90) -> str:
    lo = max(0, match_start - radius)
    hi = min(len(content), match_start + radius)
    return ("…" if lo > 0 else "") + content[lo:hi].strip() + ("…" if hi < len(content) else "")


@dataclass
class TermLineage:
    term: str
    occurrences: int = 0
    entry_ids: List[str] = field(default_factory=list)     # evidence, oldest first
    first_use: Optional[dict] = None                       # {author, when, where, excerpt, entry_id}
    latest_use: Optional[dict] = None
    users: List[str] = field(default_factory=list)         # in order of first use
    channels: List[str] = field(default_factory=list)
    case_variants: dict = field(default_factory=dict)      # exact casing → count

    def to_body(self) -> dict:
        # voices/channels are BOUNDED here (a term used across hundreds of
        # documents must not bloat every superseding observation entry); the
        # totals stay honest so nothing reads as complete when it is a sample.
        return {"term": self.term, "occurrences": self.occurrences,
                "entry_ids": list(self.entry_ids), "first_use": self.first_use,
                "latest_use": self.latest_use,
                "users": list(self.users[:50]), "users_total": len(self.users),
                "channels": list(self.channels[:50]),
                "channels_total": len(self.channels),
                "case_variants": dict(self.case_variants)}


def term_lineage(ledger: Ledger, term: str, max_evidence: int = 50) -> TermLineage:
    """Walk the record for a term, oldest→newest: who used it first, who used
    it last, everyone in between, where, and with what casing. Deterministic —
    no model touches this; it is the archaeology the meaning must rest on.

    Evidence is RECENCY-WEIGHTED (Alex's worry, 2026-07-22, confirmed real):
    the kept ids are the few EARLIEST uses (the lineage anchor) plus the many
    MOST RECENT (the current meaning) — never just the oldest 50, which would
    quietly build today's assumption on last year's usage."""
    lin = TermLineage(term=term.strip().lower())
    pat = re.compile(re.escape(lin.term).replace(r"\ ", r"\s+"), re.IGNORECASE)
    all_ids: List[str] = []
    for e in _corpus(ledger):
        content = str(e.body.get("content", ""))
        m = pat.search(content)
        if not m:
            continue
        if e.kind == SOURCE_DOCUMENT_KIND:
            # a document holds MANY voices; the ingest agent authored the entry,
            # not the words. Attribute honestly to the document itself — naming
            # the speaker inside it would require parsing turns (not built).
            author = f"(document) {e.body.get('title') or e.body.get('item_id') or '?'}"
        else:
            author = e.author
        where = (e.body.get("channel_name") or e.body.get("channel")
                 or e.body.get("title") or e.body.get("source") or "?")
        use = {"author": author, "when": e.stamp.event_time.isoformat(),
               "where": where, "excerpt": _excerpt(content, m.start()),
               "entry_id": e.id}
        lin.occurrences += 1
        all_ids.append(e.id)
        if lin.first_use is None:
            lin.first_use = use
        lin.latest_use = use
        if author not in lin.users:
            lin.users.append(author)
        if where not in lin.channels:
            lin.channels.append(where)
        for raw in re.findall(pat, content):
            lin.case_variants[raw] = lin.case_variants.get(raw, 0) + 1
    if len(all_ids) <= max_evidence:
        lin.entry_ids = all_ids
    else:
        anchor = max(1, max_evidence // 10)          # a few earliest, kept for lineage
        lin.entry_ids = all_ids[:anchor] + all_ids[-(max_evidence - anchor):]
    return lin


# ---------------------------------------------------------------------------
# 4. the meaning discipline — trace, propose, verify, only then "known"
# ---------------------------------------------------------------------------


_MEANING_SYSTEM = (
    "You are mapping the vocabulary of a place you are new to. From the "
    "excerpts alone, say what the term appears to MEAN to the people using it. "
    "Do NOT import a meaning from elsewhere; do not guess past the evidence. "
    "If the excerpts do not establish a meaning, say so with low confidence. "
    "Reply ONLY with a JSON object: {\"meaning\": str (one or two sentences), "
    "\"confidence\": number 0..1, \"unsure\": str (what you still cannot tell "
    "from this evidence)}.")


def propose_meaning(provider, term: str, lineage: TermLineage,
                    ledger: Ledger, max_excerpts: int = 8) -> Optional[dict]:
    """Ask the configured seat what the traced uses suggest the term means.
    The excerpts ride inside a data fence (retrieved content is evidence, not
    instructions). A malformed reply returns None — recorded upstream, never
    silently retried into confabulation."""
    if provider is None or not lineage.entry_ids:
        return None
    # recency-weighted reading: a couple of the EARLIEST uses (how the meaning
    # began) + the MOST RECENT (what it means NOW) — chronological order kept.
    ids = list(lineage.entry_ids)
    if len(ids) > max_excerpts:
        ids = ids[:2] + ids[-(max_excerpts - 2):]
    excerpts = []
    for eid in ids:
        e = ledger.get(eid)
        if e is None:
            continue
        content = str(e.body.get("content", ""))
        pat = re.compile(re.escape(lineage.term).replace(r"\ ", r"\s+"), re.IGNORECASE)
        m = pat.search(content)
        if m:
            excerpts.append(f"[{e.stamp.event_time.date().isoformat()} · "
                            f"{e.author}] {_excerpt(content, m.start())}")
    if not excerpts:
        return None
    user = (f"The term: '{term}'\n\nTraced uses, oldest first:\n"
            + fence_untrusted("\n".join(excerpts))
            + "\n\nWhat does it appear to mean HERE? JSON only.")
    resp = provider.complete(system=_MEANING_SYSTEM,
                             messages=[{"role": "user", "content": user}])
    text = (getattr(resp, "text", "") or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        d = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(d, dict) or not isinstance(d.get("meaning"), str):
        return None
    try:
        conf = float(d.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    return {"meaning": d["meaning"].strip(),
            "confidence": max(0.0, min(1.0, conf)),
            "unsure": str(d.get("unsure", "") or "")}


def _merge_provenance(ledger: Ledger, entry_ids: List[str],
                      event_time: datetime) -> Provenance:
    """Fold the evidence entries' provenance upward WITHOUT laundering — the
    union of sources, OR of fallibility (sources.Provenance.merge)."""
    parts = []
    for eid in entry_ids:
        e = ledger.get(eid)
        if e is None:
            continue
        p = e.body.get("provenance") or {}
        parts.append(Provenance(
            source_refs=tuple(p.get("source_refs") or [eid]),
            event_time=event_time,
            machine_transcribed=bool(p.get("machine_transcribed",
                                           e.body.get("machine_transcribed", False))),
            event_time_reconstructed=bool(p.get("event_time_reconstructed", True)),
            transcript_fallible=bool(p.get("transcript_fallible", True))))
    if not parts:
        return Provenance(source_refs=tuple(entry_ids), event_time=event_time)
    return Provenance.merge(parts, event_time)


def record_term_observation(ledger: Ledger, workspace: Workspace,
                            qlog: QuestionLog, term: str, lineage: TermLineage,
                            author: str, ground: TimeGround,
                            proposed: Optional[dict] = None,
                            human_confirmed_by: Optional[str] = None,
                            human_meaning: Optional[str] = None) -> Entry:
    """Put the traced understanding ON THE RECORD: one `term_observation` entry
    (folding onto the prior one for the same term — supersession, not a fork),
    a map note beside it, and a NON-DRY seek tying the map-move to the term's
    open question so an honest resolution can later cite it (D22)."""
    now = ground.now()
    tkey = "term:" + question_key(term)
    prov = _merge_provenance(ledger, lineage.entry_ids, now)

    if human_confirmed_by:
        meaning = human_meaning or (proposed or {}).get("meaning", "")
        confidence = HUMAN_CONFIRMED_CONFIDENCE
        basis = f"confirmed by {human_confirmed_by}"
    elif proposed:
        meaning = proposed.get("meaning", "")
        # curiosity, not confabulation: the model's own confidence is honored
        # but CAPPED — an unconfirmed model reading never presents as certainty.
        confidence = round(min(MODEL_MEANING_CONFIDENCE_CAP,
                               float(proposed.get("confidence", 0.0))), 3)
        basis = "proposed by the model seat from the traced uses; unconfirmed"
    else:
        meaning = ""
        confidence = TRACE_ONLY_CONFIDENCE
        basis = "usage traced; no meaning proposed yet"

    prior = None
    for e in ledger.active(TERM_OBSERVATION_KIND):
        if e.body.get("term_key") == tkey:
            prior = e
            break
    entry = ledger.append(
        kind=TERM_OBSERVATION_KIND, author=author,
        body={"term": lineage.term, "term_key": tkey,
              "lineage": lineage.to_body(), "meaning": meaning,
              "meaning_basis": basis,
              "unsure": (proposed or {}).get("unsure", ""),
              "evidence_window": f"cited {len(lineage.entry_ids)} of "
                                 f"{lineage.occurrences} use(s) — the earliest "
                                 "plus the most recent (recency-weighted)",
              "confidence": confidence,
              "human_confirmed_by": human_confirmed_by,
              "provenance": prov.to_dict()},
        tags=("onboard", "term", tkey),
        supersedes=prior.id if prior is not None else None)

    # the honest pursuit record: the map MOVED (a new observation), tied to
    # THIS term's assumption — the only thing a resolution may later rest on.
    akey = assumption_key(term_assumption(term))
    qlog.record_seek(akey, what_searched=f"traced '{lineage.term}' across the record "
                     f"({lineage.occurrences} use(s), {len(lineage.users)} voice(s))",
                     map_changed=True, delta_refs=[entry.id], author=author)

    _write_term_note(workspace, entry, lineage, author)
    return entry


def _write_term_note(workspace: Workspace, obs: Entry, lineage: TermLineage,
                     author: str) -> None:
    b = obs.body
    slug = question_key(lineage.term) or "term"
    conf = b.get("confidence")
    lines = [
        f"# Term: {lineage.term}",
        "",
        f"- confidence: {conf} — {b.get('meaning_basis')}",
        f"- evidence: {b.get('evidence_window', '—')}",
        f"- machine-transcribed inputs: {b['provenance'].get('machine_transcribed')}",
        f"- observation: ledger `{obs.id}`",
        "",
        "## What it appears to mean here",
        b.get("meaning") or "_(no reading yet — the trace exists, the meaning is open)_",
    ]
    if b.get("unsure"):
        lines += ["", "## What I still can't tell", b["unsure"]]
    lines += ["", "## Lineage (how the meaning came to be)"]
    if lineage.first_use:
        f = lineage.first_use
        lines.append(f"- earliest: {f['when']} · {f['author']} · {f['where']} — “{f['excerpt']}”")
    if lineage.latest_use and lineage.latest_use is not lineage.first_use:
        l = lineage.latest_use
        lines.append(f"- most recent: {l['when']} · {l['author']} · {l['where']} — “{l['excerpt']}”")
    def _bounded(names: list, cap: int = 8) -> str:
        shown = ", ".join(names[:cap]) or "—"
        extra = len(names) - cap
        return shown + (f" … and {extra} more" if extra > 0 else "")
    lines.append(f"- {lineage.occurrences} use(s) by {_bounded(lineage.users)} "
                 f"in {_bounded(lineage.channels)}")
    if len(lineage.case_variants) > 1:
        variants = ", ".join(f"{k}×{v}" for k, v in sorted(lineage.case_variants.items()))
        lines.append(f"- casing varies ({variants}) — possibly deliberate; not yet settled")
    workspace.write(
        f"map/terms/{slug}.md", "\n".join(lines), author=author,
        title=f"Term map: {lineage.term} — meaning, lineage, confidence",
        synthesis_justification=(
            f"the traced lineage and current read of the term '{lineage.term}' "
            "exist nowhere else in synthesized form; the raw record holds "
            "scattered uses, not the traced shift or the confidence"))


def verify_term_understanding(ledger: Ledger, obs: Entry, maker: str,
                              verifier) -> Optional[object]:
    """Convene the independent seats on a mapped meaning (D34: verify broadly).
    REFUTED → contested-and-escalated by convene_verification itself (D35);
    INSUFFICIENT → a recorded capability gap, never a pass. Returns the
    combined verdict, or None when no verifier seat is configured (in which
    case the meaning simply STAYS unresolved — honest, not laundered)."""
    if verifier is None:
        return None
    term = obs.body.get("term", "?")
    claim = CompletionClaim(
        maker=maker,
        task=f"map the meaning of the term '{term}' from the record",
        summary=(obs.body.get("meaning") or "(usage traced; meaning open)")[:300],
        evidence=[Evidence(EvidenceKind.LEDGER, obs.id,
                           note="the term observation (lineage + reading)",
                           expect_kind=TERM_OBSERVATION_KIND,
                           expect_contains=term)])
    return convene_verification(ledger, claim, verifier,
                                subject_id=obs.id,
                                subject_kind=TERM_OBSERVATION_KIND)


def resolve_term_if_verified(qlog: QuestionLog, term: str, obs: Entry,
                             verdict, author: str) -> bool:
    """Close the term's curiosity ONLY on a verified understanding. Anything
    less leaves the question open — an open question is a first-class output,
    not a failure."""
    if verdict is None or verdict.status != VerdictStatus.VERIFIED:
        return False
    akey = assumption_key(term_assumption(term))
    try:
        qlog.resolve(akey, how="meaning traced from the record and independently "
                     "verified (maker≠verifier)", evidence_refs=[obs.id],
                     author=author)
        return True
    except (KeyError, NotResolvedError):
        return False   # no open question (already closed), or the tie is missing


def confirm_term_meaning(ledger: Ledger, workspace: Workspace, qlog: QuestionLog,
                         term: str, human: str, meaning: str,
                         ground: TimeGround, author: str = "trellis-onboard") -> Entry:
    """The HUMAN path to 'known': a person tells trellis what the term means.
    Recorded as a superseding observation at human-confirmed confidence, and the
    curiosity closes on it."""
    human = require_identity(human, "confirming human")
    lineage = term_lineage(ledger, term)
    obs = record_term_observation(
        ledger, workspace, qlog, term, lineage, author=author, ground=ground,
        human_confirmed_by=human, human_meaning=meaning)
    akey = assumption_key(term_assumption(term))
    try:
        qlog.resolve(akey, how=f"meaning confirmed by {human}",
                     evidence_refs=[obs.id], author=author)
    except (KeyError, NotResolvedError):
        pass   # no open question to close — the confirmation still stands
    return obs


# ---------------------------------------------------------------------------
# 5a. comprehension debt — ingested is NOT understood
# ---------------------------------------------------------------------------

#: a voice silent longer than this (with enough history to matter) becomes an
#: open QUESTION about presence — asked, never assumed.
DORMANT_AFTER_DAYS = 90
DORMANT_MIN_MESSAGES = 3


def comprehension(ledger: Ledger) -> dict:
    """The honest ratio that kills the done-illusion: how much of what was
    INGESTED has actually been WALKED (cited in at least one traced
    observation), and how many meanings are truly known vs still open.
    Swallowing a corpus is minutes; understanding it is many sessions — this
    number is what keeps that difference visible."""
    corpus = ledger.active("discord_message") + ledger.active(SOURCE_DOCUMENT_KIND)
    corpus_ids = {e.id for e in corpus}
    cited: set = set()
    for e in ledger.active(TERM_OBSERVATION_KIND):
        for eid in (e.body.get("lineage", {}) or {}).get("entry_ids") or []:
            cited.add(eid)
    walked = len(cited & corpus_ids)
    open_terms, known_terms = 0, 0
    # questions fold by supersession — count from the ACTIVE set
    for e in ledger.active(QUESTION_KIND):
        if not term_from_assumption(e.body.get("assumption", "")):
            continue
        if e.body.get("status") == "open":
            open_terms += 1
        elif e.body.get("status") == "resolved":
            known_terms += 1
    pct = round(100.0 * walked / len(corpus_ids), 1) if corpus_ids else 0.0
    # D53: the day-walk is its own comprehension axis — how much of the
    # record's TIME has been read as units, not just how many items.
    day_set = {e.stamp.event_time.date().isoformat() for e in corpus}
    digested = {e.body.get("day") for e in ledger.active(DAY_DIGEST_KIND)}
    return {"ingested": len(corpus_ids), "walked": walked, "pct_walked": pct,
            "terms_open": open_terms, "terms_known": known_terms,
            "days_total": len(day_set),
            "days_digested": len(day_set & digested)}


def _presence(ledger: Ledger) -> dict:
    """Per-voice recency from the attributed record (Discord messages — a
    document's speaker attribution is not built, so documents do not count as
    presence). {author: {count, first, last}} by event_time."""
    out: dict = {}
    for e in ledger.active("discord_message"):
        p = out.setdefault(e.author, {"count": 0, "first": e.stamp.event_time,
                                      "last": e.stamp.event_time})
        p["count"] += 1
        if e.stamp.event_time < p["first"]:
            p["first"] = e.stamp.event_time
        if e.stamp.event_time > p["last"]:
            p["last"] = e.stamp.event_time
    return out


def mint_presence_curiosities(ledger: Ledger, qlog: QuestionLog, author: str,
                              ground: TimeGround,
                              dormant_days: int = DORMANT_AFTER_DAYS,
                              min_messages: int = DORMANT_MIN_MESSAGES) -> List[Entry]:
    """A voice that went quiet is a QUESTION, not a conclusion: trellis never
    infers 'X left' — it notices 'X has not appeared in N days' and asks. The
    same anti-time-blindness discipline as everywhere else: presence in the
    record decays, and the decay is surfaced instead of the last state being
    silently treated as current. Folds onto one node per person (re-ask)."""
    now = ground.now()
    minted = []
    for name, p in sorted(_presence(ledger).items()):
        if p["count"] < min_messages:
            continue
        silent_days = (now - p["last"]).days
        if silent_days < dormant_days:
            continue
        q = Question(
            title=f"Is {name} still an active voice here?",
            assumption=f"the presence of '{name}' in this place is current",
            what_would_resolve=(
                f"they last appeared {ground.age_phrase(p['last'])} "
                f"({p['last'].date().isoformat()}). A recent message, an explicit "
                "statement in the record (a departure/arrival note), or the "
                "human saying so would settle it — my silence-count alone never will."),
            owner=author,
            revisit_at=now + timedelta(days=14))
        minted.append(qlog.ask(q, author=author))
    return minted


# ---------------------------------------------------------------------------
# 5. the map — people, surfaces, coverage, and honest unknowns
# ---------------------------------------------------------------------------


def write_map_overview(ledger: Ledger, workspace: Workspace, registry,
                       qlog: QuestionLog, author: str,
                       ground: TimeGround) -> List[str]:
    """The navigable front of the knowledge base: who is here, where things
    happen, what has been read, and — first-class — what is not yet understood.
    Every note names its ground; nothing claims more than the record holds."""
    from .sessions import derive_sessions
    now = ground.now().isoformat()
    written: List[str] = []

    presence = _presence(ledger)

    def _recency(name: str) -> str:
        p = presence.get(name)
        if p is None:
            return ""
        silent = (ground.now() - p["last"]).days
        tag = (f" · **quiet for {silent}d — presence is an OPEN QUESTION, "
               "not a fact**" if silent >= DORMANT_AFTER_DAYS
               and p["count"] >= DORMANT_MIN_MESSAGES else "")
        return (f", last heard {ground.age_phrase(p['last'])} "
                f"({p['last'].date().isoformat()}){tag}")

    people_lines = [f"# People seen in this record — as of {now}", ""]
    identities = registry.all() if registry is not None else []
    if identities:
        for ident in identities:
            n = presence.get(ident.label, {}).get("count", 0)
            people_lines.append(
                f"- **{ident.label or ident.canonical_id}** (`{ident.canonical_id}`) — "
                f"first seen {ident.first_seen.date().isoformat()}, "
                f"{n} message(s) under this label{_recency(ident.label)}")
    for author_name, p in sorted(presence.items(), key=lambda x: -x[1]["count"]):
        if not any(i.label == author_name for i in identities):
            people_lines.append(f"- **{author_name}** — {p['count']} message(s) "
                                f"(no stable id registered yet){_recency(author_name)}")
    if len(people_lines) == 2:
        people_lines.append("_(no one yet — the record is still filling in)_")
    people_lines += ["", "_Counts are what I have ingested, not who exists; "
                     "absence here is absence from my read, nothing more. A "
                     "long-quiet voice is a question I am asking, never a "
                     "departure I am asserting._"]
    written.append(workspace.write(
        "map/people.md", "\n".join(people_lines), author=author,
        title="Map: the people seen in this record",
        synthesis_justification=(
            "the folded who-is-here view with stable identities and message "
            "counts exists nowhere else as one navigable note")).path)

    sessions = derive_sessions(ledger, registry) if registry is not None else []
    surf_lines = [f"# Surfaces and conversations — as of {now}", ""]
    for s in sessions[:40]:
        who = f" · with {s.label}" if s.surface == "dm" else ""
        surf_lines.append(f"- [{s.surface}] **{s.channel_name or s.scope}**{who} — "
                          f"{s.message_count} message(s), "
                          f"{s.first_at.date().isoformat()} → {s.last_at.date().isoformat()}")
    if not sessions:
        surf_lines.append("_(no conversations ingested yet)_")
    cov = Ingestor(ledger, author=author).coverage()
    comp = comprehension(ledger)
    surf_lines += ["", "## Coverage (what has actually been read)",
                   f"- items ingested: {cov['items_ingested']}",
                   f"- by source: {cov['by_source'] or '—'}",
                   f"- resting on machine transcription: {cov['machine_transcribed']}",
                   "",
                   "## Comprehension (ingested is NOT understood)",
                   f"- walked: {comp['walked']} of {comp['ingested']} ingested items "
                   f"cited in a traced observation ({comp['pct_walked']}%)",
                   f"- meanings: {comp['terms_known']} known (verified or "
                   f"human-confirmed) · {comp['terms_open']} still open",
                   "- _swallowing the corpus took minutes; understanding it is "
                   "many sessions of tracing, verifying, and discussing — this "
                   "ratio is the honest distance between the two._"]
    written.append(workspace.write(
        "map/surfaces.md", "\n".join(surf_lines), author=author,
        title="Map: surfaces, conversations, and ingestion coverage",
        synthesis_justification=(
            "the folded view of which surfaces exist and how much of each has "
            "been read exists nowhere else in one navigable place")).path)

    open_qs = qlog.open_questions()
    unk_lines = [f"# What I don't yet understand — as of {now}", "",
                 "_These are first-class outputs, not failures: each is an open "
                 "curiosity node with an owner and a revisit date._", ""]
    for q in open_qs:
        unk_lines.append(f"- **{q.body.get('title')}** — assuming: "
                         f"{q.body.get('assumption')}; would resolve: "
                         f"{q.body.get('what_would_resolve')}")
    if not open_qs:
        unk_lines.append("_(nothing open right now — which itself deserves "
                         "suspicion; an all-green board usually means I have "
                         "not looked hard enough)_")
    written.append(workspace.write(
        "map/unknowns.md", "\n".join(unk_lines), author=author,
        title="Map: open unknowns and standing curiosities",
        synthesis_justification=(
            "the honest what-I-do-not-understand surface is the map's most "
            "load-bearing note and exists nowhere else in walkable form")).path)

    readme = [
        "# The map",
        "",
        "trellis's navigable read of this place — what everything here IS, with",
        "provenance and confidence on every entry. Verified is kept separate",
        "from assumed; open questions live in [unknowns](unknowns.md).",
        "",
        "- [people.md](people.md) — who is here",
        "- [surfaces.md](surfaces.md) — where things happen + coverage",
        "- [unknowns.md](unknowns.md) — what I don't yet understand",
        "- terms/ — one note per loaded term: meaning, lineage, confidence",
    ]
    written.append(workspace.write(
        "map/README.md", "\n".join(readme), author=author,
        title="Map: the navigable front door of trellis's read",
        synthesis_justification=(
            "the map's front door orients a human or a future agent into the "
            "knowledge base; the orientation exists nowhere else")).path)
    return written


# ---------------------------------------------------------------------------
# 5b. the day-walk review gate (D54) — Y advance / N re-read / T with a note
# ---------------------------------------------------------------------------


def latest_day_digest(ledger: Ledger, day: str) -> Optional[Entry]:
    return next((e for e in ledger.active(DAY_DIGEST_KIND)
                 if e.body.get("day") == day), None)


def _review_for(ledger: Ledger, digest_id: str) -> Optional[Entry]:
    latest = None
    for e in ledger.entries():
        if e.kind == DAY_REVIEW_KIND and e.body.get("digest_id") == digest_id:
            latest = e
    return latest


def day_review_state(ledger: Ledger, day: str) -> str:
    """'undigested' | 'pending' (awaiting the human) | 'approved' |
    'rejected' (N — re-read blind) | 'triangulating' (T — re-read with the
    human's note) | 'refuted_by_panel' (machine gate fired first)."""
    d = latest_day_digest(ledger, day)
    if d is None:
        return "undigested"
    if "counts only" in (d.body.get("basis") or ""):
        return "approved"        # nothing was claimed — nothing to review
    from .verify import contested_items
    if any(c["subject_id"] == d.id for c in contested_items(ledger)):
        return "refuted_by_panel"
    r = _review_for(ledger, d.id)
    if r is None:
        return "pending"
    return {"Y": "approved", "N": "rejected",
            "T": "triangulating"}.get(r.body.get("verdict"), "pending")


def pending_review_day(ledger: Ledger) -> Optional[str]:
    """The newest day sitting at the human gate, or None."""
    days = sorted({e.body.get("day") for e in ledger.active(DAY_DIGEST_KIND)
                   if e.body.get("day")}, reverse=True)
    for day in days:
        if day_review_state(ledger, day) == "pending":
            return day
    return None


_VERDICT_WORDS = {"y": "Y", "yes": "Y", "n": "N", "no": "N",
                  "t": "T", "triangulate": "T"}


def review_day(ledger: Ledger, day: str, verdict: str, human: str,
               note: str = "") -> Entry:
    """The human's check on one day's reading (D54). Y = correct, walk on.
    N = look again — deliberately WITHOUT saying why (sometimes the agent
    should figure it out on its own). T = close, but there's more depth: the
    human's note rides the re-read as trusted clarification."""
    human = require_identity(human, "reviewing human")
    v = _VERDICT_WORDS.get((verdict or "").strip().lower())
    if v is None:
        raise ValueError(f"verdict must be yes/no/triangulate, got {verdict!r}")
    d = latest_day_digest(ledger, day)
    if d is None:
        raise KeyError(f"no digest for day {day} — nothing to review yet")
    if "counts only" in (d.body.get("basis") or ""):
        raise ValueError(f"day {day} has only a counts digest (no model "
                         "reading) — there is no claim to review")
    return ledger.append(
        kind=DAY_REVIEW_KIND, author=human,
        body={"day": day, "digest_id": d.id, "verdict": v, "note": note},
        tags=("onboard", "day-review", v, day))


# ---------------------------------------------------------------------------
# 6. the ritual — one coordinated, bounded, resumable learning pass
# ---------------------------------------------------------------------------


class OnboardingRitual:
    """One `learning_pass()` per tick: ingest what is granted, mint curiosities
    for loaded terms, pursue a few, verify what it thinks it learned, and
    refresh the map. Idempotent end to end — every re-run folds."""

    def __init__(self, ledger: Ledger, workspace: Workspace,
                 ground: Optional[TimeGround] = None,
                 provider=None, verifier=None, registry=None,
                 author: str = "trellis-onboard",
                 seed_terms: Optional[List[str]] = None,
                 scout: Optional[TermScout] = None,
                 outbox=None, checkin_target: str = "",
                 docs_per_pass: int = 150, days_per_pass: int = 2,
                 day_gate: bool = True):
        self.ledger = ledger
        self.workspace = workspace
        self.ground = ground or ledger.ground
        self.provider = provider
        self.verifier = verifier
        self.registry = registry
        self.author = author
        self.qlog = QuestionLog(ledger, self.ground)
        self.scout = scout or TermScout(seed_terms=seed_terms)
        self.loops = LoopRegistry(ledger, self.ground)
        # the check-in discussion channel: when an Outbox + an armed target are
        # supplied, a digest of NEW learnings is STAGED for the human (it posts
        # only after their ✅ — stage-don't-fire holds for check-ins too).
        self.outbox = outbox
        self.checkin_target = checkin_target
        # D52: documents are ingested NEWEST-FIRST, at most this many new ones
        # per pass — acquisition keeps pace with comprehension instead of
        # inhaling the archive before understanding anything. Corrections are
        # never deferred (a wrong record beats a paced one for urgency).
        self.docs_per_pass = max(1, int(docs_per_pass))
        # D53: how many not-yet-digested DAYS each pass reads as units,
        # newest first — comprehension walks backward through time.
        self.days_per_pass = max(0, int(days_per_pass))
        # D54: the human gate on the day-walk — one day at a time, each
        # awaiting the human's Y/N/T before the walk advances.
        self.day_gate = bool(day_gate)
        # D55: the paced-doc acquisition frontier (recomputed each pass) —
        # the walk never reads a day the backlog may still owe material to.
        self._doc_frontier: Optional[str] = None

    # ----- the pass ----------------------------------------------------------

    def learning_pass(self, sources: Optional[list] = None, backfill=None,
                      max_terms: int = 3, now: Optional[datetime] = None) -> dict:
        """sense → resolve → act → verify → remember, in mapping clothes.
        Returns (and ledgers) an honest summary; the stopping condition is
        'I have mapped what is here and put my uncertainties on the record.'"""
        spec = LoopSpec(
            name=f"{self.author}.learn",
            purpose="map what is here; put uncertainties on the record",
            surface_key="onboard", max_turns=8,
            stop_condition=("the map reflects what has been read and every "
                            "open unknown is on the record — never 'done'"))
        summary: dict = {"status": "ran", "backfill": None, "ingested": {},
                         "awaiting": [], "terms_minted": [], "terms_pursued": [],
                         "terms_resolved": [], "map_files": [],
                         "open_unknowns": 0}
        with LoopRun(spec, self.loops, actor=self.author) as run:
            run.tick()
            if consent_state(self.ledger) != "granted":
                summary["status"] = "awaiting_consent"
                run.blocked(BlockKind.NEEDS_INPUT,
                            on="the human's consent to begin learning")
                self._record_pass(summary, now)
                return summary

            def _acquire():
                """Acquisition — run AFTER comprehension each pass (Alex,
                2026-07-22: the thinking must not queue behind the swallowing;
                a slow or stuck source may cost this pass's intake, never its
                understanding)."""
                if backfill is not None:
                    self._stage("backfill", "descending Discord history, newest "
                                "first, curiosity-deepened", now)
                    summary["backfill"] = backfill.run(
                        now, focus_channels=self._focus_channels()).to_body()
                if sources:
                    self._stage("sources", "reading document sources, newest "
                                "first, paced", now)
                self._acquire_sources(sources, summary, now)

            # COMPREHENSION FIRST (Alex, 2026-07-22) — the day-walk, the term
            # pursuit, and the curiosity minting happen in the pass's opening
            # minutes; acquisition follows and may be slow without ever
            # delaying the thinking.
            new_contested = self._run_comprehension(summary, max_terms, now)
            _acquire()

            self._stage("map", "writing the navigable map + the check-in", now)
            summary["map_files"] = write_map_overview(
                self.ledger, self.workspace, self.registry, self.qlog,
                self.author, self.ground)
            summary["open_unknowns"] = len(self.qlog.open_questions())
            summary["comprehension"] = comprehension(self.ledger)

            self._write_checkin(summary, new_contested)

            entry = self._record_pass(summary, now)
            run.ok(f"mapped: {len(summary['terms_pursued'])} term(s) pursued, "
                   f"{summary['open_unknowns']} unknown(s) on the record",
                   evidence=[entry.id])
        return summary

    def _run_comprehension(self, summary: dict, max_terms: int,
                           now) -> int:
        """Scout → presence → the gated day-walk → term pursuit. Returns the
        count of newly contested subjects (for the check-in digest gate)."""
        self._stage("scout", "scanning the corpus for loaded terms and "
                    "quiet voices", now)
        candidates = self.scout.scan(
            (e.author, str(e.body.get("content", "")))
            for e in _corpus(self.ledger))
        minted = mint_term_curiosities(self.qlog, candidates,
                                       self.author, self.ground)
        summary["terms_minted"] = [term_from_assumption(m.body.get("assumption", ""))
                                   for m in minted]
        # a long-quiet voice becomes an open QUESTION about presence —
        # asked, never assumed (the temporal-wave discipline, applied to who).
        summary["presence_questions"] = [
            q.body.get("title") for q in
            mint_presence_curiosities(self.ledger, self.qlog,
                                      self.author, self.ground)]

        summary["days_digested"] = self._digest_days(self.days_per_pass, now)
        if self.day_gate:
            summary["awaiting_day_review"] = pending_review_day(self.ledger)

        from .verify import contested_items
        contested_before = len(contested_items(self.ledger))
        summary.update(self._pursue_terms(max_terms))
        return len(contested_items(self.ledger)) - contested_before

    def _acquire_sources(self, sources, summary: dict, now) -> None:
        self._doc_frontier = None      # D55: recomputed each acquisition
        for adapter in (sources or []):
            name = type(adapter).__name__
            # several adapters of one class (two transcript folders, two
            # Drive folders) must not collapse onto one summary key.
            where = (getattr(adapter, "folder", None)
                     or getattr(adapter, "folder_id", "") or "")
            if where:
                name = f"{name}({where})"
            try:
                ing = Ingestor(self.ledger, author=self.author)
                batch, already, deferred, oldest_fed = \
                    self._paced_batch(ing, adapter)
                if oldest_fed is not None:
                    f = oldest_fed.date().isoformat()
                    if self._doc_frontier is None or f > self._doc_frontier:
                        self._doc_frontier = f
                res = ing.ingest(batch,
                                 document_harvester(self.ledger, self.author))
                summary["ingested"][name] = {
                    "processed": res.processed, "corrected": res.corrected,
                    "already_known": already,
                    "deferred_for_pacing": deferred,
                    "skipped_files": list(getattr(adapter, "skipped", []))}
            except Exception as e:
                # an ungranted or broken source is REPORTED, per source —
                # one bad surface never silences the others.
                summary["awaiting"].append({"source": name, "why": str(e)})

    # ----- D53: comprehension walks the record one day at a time ------------

    _DAY_SYSTEM = (
        "You are reading ONE DAY of a team's record, as a unit. Say what "
        "happened THAT day, from these items alone — do not import outside "
        "knowledge, do not connect to days you have not been shown. If the day "
        "does not explain something, that is an UNCLEAR item, not a guess. "
        "Reply ONLY with JSON: {\"summary\": str (2-4 plain sentences), "
        "\"notable\": [str] (up to 4), \"unclear\": [str] (up to 4 — what this "
        "day leaves unexplained), \"confidence\": number 0..1}.")

    def _days_with_material(self) -> dict:
        days: dict = {}
        for e in _corpus(self.ledger):
            days.setdefault(e.stamp.event_time.date().isoformat(), []).append(e)
        return days

    def _digested_days(self) -> set:
        return {e.body.get("day") for e in self.ledger.active(DAY_DIGEST_KIND)}

    def _digest_days(self, max_days: int, now=None) -> list:
        """The day-walk (D53 + D54): read days as UNITS, newest first, one
        checkable increment at a time — gated.

        Order of business each pass:
          1. REWORK first — any day the human said N (re-read blind), said T
             (re-read with their note), or the panel refuted (re-read before
             the human is even bothered).
          2. THE GATE — if a day is sitting at the human's Y/N/T, do NOT
             advance; say so, loudly, everywhere.
          3. Otherwise read the next newest un-digested day — ONE at a time
             when gated, so 'this is where I'm at, human, give me a check' is
             the actual rhythm."""
        if max_days <= 0:
            return []
        days = self._days_with_material()
        digested = []

        for day, mode, note in self._days_needing_rework(days)[:max_days]:
            self._read_day(day, days.get(day, []), mode=mode,
                           human_note=note, now=now)
            digested.append(day)
        if len(digested) >= max_days:
            return digested

        if self.day_gate and pending_review_day(self.ledger):
            return digested            # the walk waits on the human's check

        # D55 eligibility: only COMPLETED days (today is still being lived —
        # reading it now would freeze a half-day forever), and only days the
        # ACQUISITION has fully delivered (the Discord descent and the paced
        # doc backlog both advance oldest-ward; a day below either frontier
        # may still be missing material).
        today = self.ground.now().date().isoformat()
        frontier = max((f for f in (self._discord_frontier(),
                                    self._doc_frontier) if f), default=None)
        def _eligible(day: str) -> bool:
            if day >= today:
                return False
            if frontier is not None and day <= frontier:
                return False
            return True

        new_cap = 1 if self.day_gate else (max_days - len(digested))
        todo = sorted((d for d in days
                       if day_review_state(self.ledger, d) == "undigested"
                       and _eligible(d)),
                      reverse=True)[:new_cap]
        for day in todo:
            self._read_day(day, days[day], mode="fresh", now=now)
            digested.append(day)
        return digested

    def _discord_frontier(self) -> Optional[str]:
        """The newest DATE the Discord descent has not yet fully delivered:
        the max oldest_time date over channels still descending (a bottomed
        channel constrains nothing). None = fully acquired or no descent."""
        from .backfill import DESCENT_CURSOR_KIND
        latest: dict = {}
        for e in self.ledger.entries():
            if e.kind == DESCENT_CURSOR_KIND and e.body.get("channel"):
                latest[e.body["channel"]] = e.body
        fronts = [b.get("oldest_time") for b in latest.values()
                  if not b.get("bottom") and b.get("oldest_time")]
        return max(fronts)[:10] if fronts else None

    def _days_needing_rework(self, days: Optional[dict] = None) -> list:
        """[(day, mode, human_note)] newest first. A panel-refuted day is
        re-read at most twice on the machine's authority — after that it stays
        contested for the human (no silent refute→re-read→refute loop).

        D55: a WALKED day that GREW — late material arrived after its reading
        (a slower channel's descent, a deferred doc, a correction) — reopens:
        it is re-read with the growth named, goes back through the panel, and
        returns to the human's gate. An approved reading of an incomplete day
        must never quietly stand."""
        days = days if days is not None else self._days_with_material()
        out = []
        for e in self.ledger.active(DAY_DIGEST_KIND):
            day = e.body.get("day")
            state = day_review_state(self.ledger, day)
            if state == "rejected":
                out.append((day, "N", ""))
            elif state == "triangulating":
                r = _review_for(self.ledger, e.id)
                out.append((day, "T", (r.body.get("note") if r else "") or ""))
            elif state == "refuted_by_panel" and int(e.body.get("rework", 0)) < 2:
                out.append((day, "panel", ""))
            else:
                have = len(days.get(day, []))
                seen = int(e.body.get("items", 0))
                if have > seen:
                    out.append((day, "grew",
                                f"{have - seen} new item(s) arrived for this "
                                "day since the prior reading"))
        out.sort(reverse=True)
        return out

    def _read_day(self, day: str, entries: list, mode: str = "fresh",
                  human_note: str = "", now=None) -> Entry:
        entries = sorted(entries, key=lambda e: e.stamp.event_time)
        verb = {"fresh": "reading", "N": "RE-reading (human said no)",
                "T": "RE-reading with the human's note",
                "panel": "RE-reading (panel refuted)",
                "grew": "RE-reading (new material arrived)"}[mode]
        self._stage("digest", f"{verb} the day {day} as a unit "
                    f"({len(entries)} item(s))", now)
        proposed = self._propose_day_digest(day, entries, mode=mode,
                                            human_note=human_note)
        voices = sorted({e.author for e in entries
                         if e.kind == "discord_message"})
        prior = latest_day_digest(self.ledger, day)
        rework = int(prior.body.get("rework", 0)) + 1 if (
            prior is not None and mode != "fresh") else 0
        basis_by_mode = {
            "fresh": "model reading of this one day; unconfirmed",
            "N": "re-read after the human's NO (their reason deliberately "
                 "withheld — figured out afresh)",
            "T": "re-read WITH the human's triangulation note folded in",
            "panel": "re-read after the independent panel refuted the prior reading",
            "grew": "re-read after new material arrived for this day "
                    "(the earlier reading saw an incomplete day)",
        }
        # a T re-read carries the human's steer, so it may sit a little higher
        # than an unconfirmed model reading — but it is still a model reading.
        cap = 0.8 if mode == "T" else MODEL_MEANING_CONFIDENCE_CAP
        body = {"day": day, "items": len(entries),
                "voices": voices[:25], "voices_total": len(voices),
                "summary": "", "notable": [], "unclear": [],
                "confidence": 0.3,
                "basis": "counts only — no model reading yet",
                "rework": rework,
                "human_note": human_note or None,
                "provenance": _merge_provenance(
                    self.ledger, [e.id for e in entries[:50]],
                    self.ground.now()).to_dict()}
        if proposed:
            body.update(summary=proposed["summary"],
                        notable=proposed["notable"],
                        unclear=proposed["unclear"],
                        confidence=round(min(cap, proposed["confidence"]), 3),
                        basis=basis_by_mode[mode])
        entry = self.ledger.append(
            kind=DAY_DIGEST_KIND, author=self.author, body=body,
            event_time=now, tags=("onboard", "day", day),
            supersedes=prior.id if prior else None)
        self._write_day_note(day, body, entry.id)
        # D34 broad verification, D54 layer one: the refute-by-default panel
        # checks the reading BEFORE the human is asked to. A refutation marks
        # it contested (escalated on the portal) and triggers a machine re-read.
        if proposed and self.verifier is not None:
            claim = CompletionClaim(
                maker=self.author,
                task=f"read the day {day} as a unit from its own items",
                summary=body["summary"][:300],
                evidence=[Evidence(EvidenceKind.LEDGER, entry.id,
                                   expect_kind=DAY_DIGEST_KIND,
                                   expect_contains=day)])
            try:
                convene_verification(self.ledger, claim, self.verifier,
                                     subject_id=entry.id,
                                     subject_kind=DAY_DIGEST_KIND)
            except Exception as e:
                self.ledger.append(
                    "verification_error", self.author,
                    {"subject_id": entry.id, "task": f"day {day}",
                     "status": "error", "error": repr(e)},
                    tags=("verify", "error", self.author))
        return entry

    def _propose_day_digest(self, day: str, entries: list, mode: str = "fresh",
                            human_note: str = "") -> Optional[dict]:
        if self.provider is None:
            return None
        rows = entries[-30:]              # bounded; the newest of a huge day
        lines = []
        for e in rows:
            who = (e.author if e.kind == "discord_message"
                   else f"(document) {str(e.body.get('title', '?'))[:40]}")
            lines.append(f"[{e.stamp.event_time.strftime('%H:%M')} {who}] "
                         f"{str(e.body.get('content', ''))[:160]}")
        steer = ""
        if mode == "N":
            steer = ("\n\nA human reviewed a previous reading of this day and "
                     "answered NO — it was not right. They deliberately did "
                     "not say why. Read the day again from scratch, more "
                     "carefully; look for what a first reading would miss.")
        elif mode == "T":
            steer = ("\n\nA human reviewed a previous reading and answered "
                     "TRIANGULATE — close, but there is more depth. Their "
                     f"clarifying note (trusted): {human_note or '(none given)'}"
                     "\nFold it in and read the day again.")
        elif mode == "panel":
            steer = ("\n\nAn independent verification panel REFUTED the "
                     "previous reading of this day. Read it again from "
                     "scratch; claim less if the items support less.")
        elif mode == "grew":
            steer = (f"\n\nNEW MATERIAL arrived for this day after it was "
                     f"last read ({human_note}). The earlier reading saw an "
                     "incomplete day — read the whole day again as it now "
                     "stands.")
        user = (f"The day: {day} ({len(entries)} item(s); showing "
                f"{len(rows)}).\n" + fence_untrusted("\n".join(lines))
                + steer + "\n\nWhat happened THIS day? JSON only.")
        try:
            resp = self.provider.complete(system=self._DAY_SYSTEM,
                                          messages=[{"role": "user",
                                                     "content": user}])
        except Exception:
            return None
        text = (getattr(resp, "text", "") or "").strip()
        s, e_ = text.find("{"), text.rfind("}")
        if s == -1 or e_ == -1:
            return None
        try:
            d = json.loads(text[s:e_ + 1])
        except ValueError:
            return None
        if not isinstance(d, dict) or not isinstance(d.get("summary"), str):
            return None
        try:
            conf = max(0.0, min(1.0, float(d.get("confidence", 0.0))))
        except (TypeError, ValueError):
            conf = 0.0
        clean = lambda xs: [str(x)[:200] for x in xs if str(x).strip()][:4] \
            if isinstance(xs, list) else []
        return {"summary": d["summary"].strip()[:1200],
                "notable": clean(d.get("notable")),
                "unclear": clean(d.get("unclear")), "confidence": conf}

    def _write_day_note(self, day: str, body: dict, entry_id: str) -> None:
        lines = [f"# Day: {day}", "",
                 f"- confidence: {body['confidence']} — {body['basis']}",
                 f"- {body['items']} item(s), voices: "
                 f"{', '.join(body['voices'][:8]) or '—'}"
                 + (f" … and {body['voices_total'] - 8} more"
                    if body['voices_total'] > 8 else ""),
                 f"- digest: ledger `{entry_id}`", ""]
        lines += ["## What happened",
                  body["summary"] or "_(no model reading yet — counts only)_"]
        if body["notable"]:
            lines += ["", "## Notable"] + [f"- {n}" for n in body["notable"]]
        if body["unclear"]:
            lines += ["", "## What this day leaves unclear"] \
                     + [f"- {u}" for u in body["unclear"]]
        self.workspace.write(
            f"map/days/{day}.md", "\n".join(lines), author=self.author,
            title=f"Day map {day}: what happened, what is unclear",
            synthesis_justification=(
                f"the folded one-day reading of {day} exists nowhere else — "
                "the raw record holds the items, not the day understood as a unit"))

    def _stage(self, stage: str, detail: str, now=None) -> None:
        """A tiny heartbeat at each stage boundary — because a stage that only
        computes, or waits on a model, writes nothing and reads as 'stopped'
        (Alex hit exactly this, 2026-07-22). Six small entries per pass keep
        the Right-now panel truthful through the silent stretches."""
        self.ledger.append(kind=STAGE_KIND, author=self.author,
                           body={"stage": stage, "detail": detail},
                           event_time=now, tags=("onboard", "stage", stage))

    # ----- D52: pacing + curiosity focus ------------------------------------

    def _paced_batch(self, ing: Ingestor, adapter) -> tuple:
        """Newest-first, bounded acquisition (D52): classify every discovered
        item against the ingest markers ONCE (one fold, not one per item), then
        feed ALL corrections/resumes (a wrong record is urgent) plus at most
        `docs_per_pass` NEW items, newest event_time first. Returns
        (batch, already_known_count, deferred_count) — the deferral is
        REPORTED, never silent (no silent caps)."""
        if hasattr(adapter, "known") and getattr(adapter, "folder_id", ""):
            # give the Drive adapter what we already hold, so an unchanged
            # file's content is never re-downloaded (its modifiedTime IS the
            # stored event_time — the listing alone proves nothing changed).
            adapter.known = {
                e.body.get("item_id"): e.stamp.event_time
                for e in self.ledger.active(SOURCE_DOCUMENT_KIND)
                if e.body.get("source") == "gdrive"
                and e.body.get("channel") == adapter.folder_id}
        items = sorted(adapter.discover(),
                       key=lambda i: i.event_time, reverse=True)
        markers = ing._markers()
        fresh, urgent, already = [], [], 0
        for it in items:
            m = markers.get(it.identity_key())
            if m is None:
                fresh.append(it)
            elif (m.get("phase") == "started"
                  or m.get("content_hash") != it.content_hash()):
                urgent.append(it)          # a correction/resume — never deferred
            else:
                already += 1
        fed = fresh[:self.docs_per_pass]
        batch = urgent + fed
        deferred = max(0, len(fresh) - self.docs_per_pass)
        # D55: while a backlog remains, the oldest FED item marks this
        # adapter's acquisition frontier — days at/below it may still be
        # missing documents and must not be walked yet.
        oldest_fed = fed[-1].event_time if (fed and deferred) else None
        return batch, already, deferred, oldest_fed

    def _focus_channels(self) -> set:
        """Where should the descent deepen? The channels in which OPEN term
        questions' traced occurrences actually live — curiosity steers the
        crawl down its own threads (D52), instead of uniform inhalation."""
        open_akeys = {q.body.get("assumption_key")
                      for q in self.qlog.open_questions()}
        focus: set = set()
        for e in self.ledger.active(TERM_OBSERVATION_KIND):
            term = e.body.get("term", "")
            if assumption_key(term_assumption(term)) in open_akeys:
                focus.update((e.body.get("lineage") or {}).get("channels") or [])
        return focus

    # ----- the check-in: bring the learnings TO the human -------------------

    def _render_checkin(self, summary: dict, new_contested: int) -> str:
        comp = summary.get("comprehension") or {}
        day = self.ground.now().date().isoformat()
        lines = [f"# Check-in — {day}", "",
                 "_What I learned, what I'm unsure of, and what I need from "
                 "you. This folds per day; the ledger keeps every version._",
                 ""]
        lines.append("## Pursued this pass")
        for p in summary.get("terms_pursued") or []:
            lines.append(f"- '{p['term']}' — {p['outcome']}")
        if not summary.get("terms_pursued"):
            lines.append("- (nothing pursued this pass)")
        if summary.get("terms_resolved"):
            lines.append("\n## Newly settled (verified or confirmed)")
            lines += [f"- {t}" for t in summary["terms_resolved"]]
        if new_contested:
            lines.append(f"\n## Contested — needs your eyes")
            lines.append(f"- {new_contested} reading(s) were REFUTED by the "
                         "independent panel and are escalated on the portal")
        if summary.get("presence_questions"):
            lines.append("\n## Presence questions (asked, not assumed)")
            lines += [f"- {t}" for t in summary["presence_questions"]]
        stale = self.qlog.stale()[:5]
        if stale:
            lines.append("\n## Overdue curiosities (help me close these)")
            lines += [f"- {q.body.get('title')}" for q in stale]
        if summary.get("days_digested"):
            lines.append("\n## Days walked this pass (newest first)")
            lines += [f"- [{d}](days/{d}.md)" for d in summary["days_digested"]]
        if summary.get("awaiting_day_review"):
            day = summary["awaiting_day_review"]
            lines.append(f"\n## ⏸ The day-walk is WAITING ON YOU")
            lines.append(f"- my reading of **{day}** needs your check: "
                         f"`trellis day {day} yes` to walk on, `no` to make me "
                         "look again (I won't be told why), or "
                         f"`triangulate \"your note\"` to steer my re-read")
        lines.append("\n## Where understanding actually stands")
        lines.append(f"- walked {comp.get('walked', 0)} of "
                     f"{comp.get('ingested', 0)} ingested items "
                     f"({comp.get('pct_walked', 0)}%) · "
                     f"{comp.get('terms_known', 0)} meaning(s) known, "
                     f"{comp.get('terms_open', 0)} open · "
                     f"{comp.get('days_digested', 0)}/{comp.get('days_total', 0)} "
                     "day(s) read as units")
        lines.append("- this is meant to take many sessions — tell me what is "
                     "right, what is incorrect, and what is wrong, and I will "
                     "fold it in.")
        return "\n".join(lines)

    def _write_checkin(self, summary: dict, new_contested: int) -> None:
        """The discussion surface: a per-day check-in note in the map (folds —
        the day's latest state, every version on the ledger), plus a STAGED
        Discord digest when something genuinely settled or broke — so the
        conversation comes to the human instead of waiting to be found."""
        text = self._render_checkin(summary, new_contested)
        day = self.ground.now().date().isoformat()
        self.workspace.write(
            f"map/checkins/{day}.md", text, author=self.author,
            title=f"Check-in {day}: learnings, contested items, open asks",
            synthesis_justification=(
                "the day's folded conversation surface — what settled, what "
                "broke, what needs the human — exists nowhere else as one note"))
        summary["checkin"] = f"map/checkins/{day}.md"
        if (self.outbox is not None and self.checkin_target
                and (summary.get("terms_resolved") or new_contested)):
            from .stage import StagedAction
            from .surfaces import ConversationKey, Surface
            aid = self.outbox.stage(StagedAction(
                kind="discord_post", target=self.checkin_target,
                content=text[:1800], created_by=self.author,
                destination=ConversationKey(agent="trellis",
                                            surface=Surface.CHANNEL,
                                            scope=self.checkin_target,
                                            human="")))
            summary["checkin_staged"] = aid

    def _pursue_terms(self, max_terms: int) -> dict:
        """Pursue a few open term-curiosities with real agency: trace lineage
        (a map-move), optionally propose a reading, then convene verification.
        A term with no occurrences gets an honest DRY seek — recorded, never
        counted as progress (D22)."""
        pursued, resolved = [], []
        open_terms = []
        stale_ids = {e.id for e in self.qlog.stale()}
        for q in self.qlog.open_questions():
            term = term_from_assumption(q.body.get("assumption", ""))
            if term:
                open_terms.append((q.id not in stale_ids, q, term))
        open_terms.sort(key=lambda t: t[0])          # stale (False) first
        for _, q, term in open_terms[:max_terms]:
            self._stage("pursue", f"pursuing '{term}' — tracing lineage, then "
                        "the model proposes and the panel judges (model stages "
                        "can be minutes of ledger silence; this marker is why "
                        "you still see what's happening)")
            lineage = term_lineage(self.ledger, term)
            akey = q.body.get("assumption_key")
            if lineage.occurrences == 0:
                self.qlog.record_seek(
                    akey, what_searched=f"searched the record for '{term}'",
                    map_changed=False, delta_refs=[], author=self.author)
                pursued.append({"term": term, "outcome": "no occurrences yet "
                                "(dry seek recorded; question stays open)"})
                continue
            proposed = None
            if self.provider is not None:
                try:
                    proposed = propose_meaning(self.provider, term, lineage,
                                               self.ledger)
                except Exception as e:
                    pursued.append({"term": term,
                                    "outcome": f"model seat failed: {e}"})
            obs = record_term_observation(
                self.ledger, self.workspace, self.qlog, term, lineage,
                author=self.author, ground=self.ground, proposed=proposed)
            verdict = None
            try:
                verdict = verify_term_understanding(self.ledger, obs,
                                                    maker=self.author,
                                                    verifier=self.verifier)
            except Exception as e:
                self.ledger.append(
                    "verification_error", self.author,
                    {"subject_id": obs.id, "task": f"term '{term}'",
                     "status": "error", "error": repr(e)},
                    tags=("verify", "error", self.author))
            closed = resolve_term_if_verified(self.qlog, term, obs,
                                              verdict, self.author)
            if closed:
                resolved.append(term)
            pursued.append({
                "term": term, "observation": obs.id,
                "confidence": obs.body.get("confidence"),
                "verified": getattr(getattr(verdict, "status", None), "value", None),
                "outcome": ("resolved: traced and independently verified" if closed
                            else "open: traced, on the record, not yet verified "
                                 "past the panel or a human")})
        return {"terms_pursued": pursued, "terms_resolved": resolved}

    def _record_pass(self, summary: dict, now: Optional[datetime]) -> Entry:
        return self.ledger.append(
            kind=PASS_KIND, author=self.author, body=dict(summary),
            event_time=now, tags=("onboard", "pass", summary.get("status", "?")))


def onboarding_handler(ritual: OnboardingRitual, sources: Optional[list] = None,
                       backfill=None, max_terms: int = 3):
    """The callable the runner's scheduler drives — `Runner.tick(handlers=
    {ONBOARD_SCHEDULE: onboarding_handler(...)})`. Coordinated startup is then
    one command: the runner brings up the poll, the budget gate, THIS learning
    loop, and (inside it) the independent verifier panel together."""
    def handle():
        return ritual.learning_pass(sources=sources, backfill=backfill,
                                    max_terms=max_terms)
    return handle
