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
from .curiosity import NotResolvedError, Question, QuestionLog, assumption_key
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
    no model touches this; it is the archaeology the meaning must rest on."""
    lin = TermLineage(term=term.strip().lower())
    pat = re.compile(re.escape(lin.term).replace(r"\ ", r"\s+"), re.IGNORECASE)
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
        if len(lin.entry_ids) < max_evidence:
            lin.entry_ids.append(e.id)
        if lin.first_use is None:
            lin.first_use = use
        lin.latest_use = use
        if author not in lin.users:
            lin.users.append(author)
        if where not in lin.channels:
            lin.channels.append(where)
        for raw in re.findall(pat, content):
            lin.case_variants[raw] = lin.case_variants.get(raw, 0) + 1
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
    excerpts = []
    for eid in lineage.entry_ids[:max_excerpts]:
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

    counts: dict = {}
    for e in ledger.active("discord_message"):
        counts[e.author] = counts.get(e.author, 0) + 1
    people_lines = [f"# People seen in this record — as of {now}", ""]
    identities = registry.all() if registry is not None else []
    if identities:
        for ident in identities:
            n = counts.get(ident.label, 0)
            people_lines.append(
                f"- **{ident.label or ident.canonical_id}** (`{ident.canonical_id}`) — "
                f"first seen {ident.first_seen.date().isoformat()}, "
                f"{n} message(s) under this label")
    for author_name, n in sorted(counts.items(), key=lambda x: -x[1]):
        if not any(i.label == author_name for i in identities):
            people_lines.append(f"- **{author_name}** — {n} message(s) "
                                "(no stable id registered yet)")
    if len(people_lines) == 2:
        people_lines.append("_(no one yet — the record is still filling in)_")
    people_lines += ["", "_Counts are what I have ingested, not who exists; "
                     "absence here is absence from my read, nothing more._"]
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
    surf_lines += ["", "## Coverage (what has actually been read)",
                   f"- items ingested: {cov['items_ingested']}",
                   f"- by source: {cov['by_source'] or '—'}",
                   f"- resting on machine transcription: {cov['machine_transcribed']}"]
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
                 scout: Optional[TermScout] = None):
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

            if backfill is not None:
                summary["backfill"] = backfill.run(now).to_body()

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
                    res = ing.ingest(adapter.discover(),
                                     document_harvester(self.ledger, self.author))
                    summary["ingested"][name] = {
                        "processed": res.processed, "corrected": res.corrected,
                        "skipped_duplicate": res.skipped_duplicate,
                        "skipped_files": list(getattr(adapter, "skipped", []))}
                except Exception as e:
                    # an ungranted or broken source is REPORTED, per source —
                    # one bad surface never silences the others.
                    summary["awaiting"].append({"source": name, "why": str(e)})

            candidates = self.scout.scan(
                (e.author, str(e.body.get("content", "")))
                for e in _corpus(self.ledger))
            minted = mint_term_curiosities(self.qlog, candidates,
                                           self.author, self.ground)
            summary["terms_minted"] = [term_from_assumption(m.body.get("assumption", ""))
                                       for m in minted]

            summary.update(self._pursue_terms(max_terms))

            summary["map_files"] = write_map_overview(
                self.ledger, self.workspace, self.registry, self.qlog,
                self.author, self.ground)
            summary["open_unknowns"] = len(self.qlog.open_questions())

            entry = self._record_pass(summary, now)
            run.ok(f"mapped: {len(summary['terms_pursued'])} term(s) pursued, "
                   f"{summary['open_unknowns']} unknown(s) on the record",
                   evidence=[entry.id])
        return summary

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
