# trellis — a walkthrough you can read aloud

*Written 2026-07-22 for sharing with the team. Tab by tab, in sidebar order.*

## What this is, in one breath

trellis is a **mapper, not an assistant**. It reads the team's record — Discord
history, meeting transcripts, the Drive folders we grant it — and slowly builds
a checked understanding of what everything here *is*: the people, the days, the
loaded words like "empire." It never assumes a meaning; it traces how we
actually use a word, proposes a reading, has a panel of independent verifier
models try to *refute* that reading, and then brings it to a human for a
**Yes / No / Triangulate**. Everything it does lands in one append-only ledger —
nothing is ever deleted or rewritten, corrections are layered on top with
attribution — and **it cannot send a single message to anyone without a human
clicking approve**. The portal is the window into all of that, live.

The pace is deliberate: it swallowed the record in hours, but understanding is
earned in small, checkable pieces — a few terms per pass, one day of history at
a time, each piece verified by machines and then gated by us.

---

## Overview

The one-screen pulse. Top panel — **"Right now"** — is literally what the agent
is doing this second, with a stage label (SWALLOWING when it's reading sources
in bulk, TRACING when it's following a term through the record, VERIFYING while
the panel votes, THINKING during a model call, QUIET when it's honestly
resting) and a live tail of its last ledger writes, streaming. The chips count
the record: total events, decisions, how many **days of history it has read as
units** versus how many exist — the honest "how much does it actually
understand" number. Below: **"Waiting on you"** — anything needing a human
(staged messages, a day awaiting its check), because nothing outward or
irreversible happens without us. The green dot top-right pulses on every ledger
write: the record, visibly breathing.

## The Map

What the *room* decided versus what the *agent* thinks about it. Every decision
it observes in the record becomes two linked entries — the room's ruling
(attributed to the people who made it) and the agent's own opinion of it — so
its read never quietly overwrites ours. Sparse until the witness loop has been
running a while; it fills as decisions accumulate.

## Assumptions

The contemplating mind, made watchable — and the page I'd show first. Three
sections, top to bottom:

- **Needs your Y/N/T** — readings it has finished and brought to us. Each card
  leads with *its own attempt*: "my read (confidence 0.6, unconfirmed): …",
  what it's still unsure about, and how much evidence it read ("cited 50 of
  8,846 uses"). Three buttons: **Yes** (one click, seals the meaning at human
  confidence), **No** (it goes back and digs on its own — your reason is
  deliberately withheld from it), **Triangulate** (your one-line note steers a
  deeper re-read).
- **Back in my hands** — cards you already answered; it shows your verdict and
  re-reads before returning.
- **On my mind** — its own research agenda. Nothing there needs a human; it
  brings each one up when a reading is ready. You never answer anything cold.

The design point: the *agent* does the cognitive work and deepens with every
visit; humans only render verdicts.

## Day walk

History, read one day at a time, newest first — comprehension as a visible
timeline. Each card is one day's reading: what happened, what was notable, what
that day *leaves unclear*, with a confidence. A day only advances past two
gates: the verifier panel first (it refuted the very first day-reading and was
*right* — it caught 655 documents mis-dated to their upload day), then a human
Yes / No / Triangulate. It never reads today (a day still being lived isn't a
unit yet), never reads a day whose material hasn't fully arrived, and reopens
any day that later grows. The walk moves at the speed of our yeses — which is
the point.

## Ingestion

Coverage and gaps: what's been taken in, from where (Discord, Drive, local
transcripts, the principles library), and how much rests on machine
transcription — Gemini notes and Whisper output are flagged as fallible at the
source, and that fallibility travels into every conclusion built on them.
Swallowed-versus-understood is kept honest here: ingesting is minutes;
understanding is the day walk and the term work.

## Sessions

Every conversation on the record — who, where, what was said, DMs individuated
per person under stable identities (a display-name change can't fork a
conversation). This is the transparency contract: anyone who talks with trellis
is on the record, and this page is where that record is legible. It shows DM
content, so it's the one page that always requires sign-in.

## Decisions

Every Yes / No / Triangulate on the ledger — the atomic unit of the whole
system. Click one and walk its lineage: what it rests on, what superseded what,
back to the principles it expresses. "An unresolved Triangulate is a hidden no"
— overdue ones light up rather than rot quietly.

## Reflection

Once a day the agent looks at itself in the mirror of its own record — where it
got confused, what burned it — and those burns ride its next day's context so
it doesn't relearn them cold. Functional self-knowledge, no soul theater.

## Improvement

The agent may *propose* changes to how it works — it can never apply one. Every
proposal needs an independent verifier's verdict AND a human's ratification
before it takes effect. Recursive self-improvement with two locks on the door.

## Loops

The background jobs and their health. Every loop is bounded and must end in a
typed outcome — silence is structurally impossible: a job that dies without
reporting gets marked as a protocol violation by the harness itself. "Is it
actually running?" is a query here, never a hope.

## Verification

The spine: **the maker never grades its own work.** Everything the agent claims
to have learned is checked by a separate, cheaper model panel — four lenses
(correctness, freshness, attribution, reproducibility), each prompted to
*refute*. One refutation sinks a claim; a panel that can't tell says so instead
of passing it. This page shows who checked whom and how it went — including the
refutations, which are the receipts that the checking is real. Today it caught
a mis-dated document batch, a false "the meaning pivoted in April" claim, and
several overreaches. Trust here is earned per-verdict and compounds.

## Agents

Everyone on the record — humans and agents — with how much of each maker's work
has been independently verified. The trust ledger, per identity.

## Activity

The raw event feed, newest first, copy-pasteable. When any other page makes you
curious, this is the unfiltered truth under it.

---

## The three sentences that summarize the whole thing

It **records everything and hides nothing** — append-only, attributed,
corrections layered, never deletions. It **assumes nothing** — meanings, days,
and decisions are traced from the record, attacked by independent verifiers,
and gated by humans, with its uncertainty published as a first-class output.
And it **touches nothing** — every outward message stays staged until a human
approves it, every self-change needs a human's ratification, and its Google and
Discord access are explicit, revocable grants.
