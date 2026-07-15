# Why there is no soul.md (and never will be)

Every harness in this machine's lineage that gave an agent a soul file —
Argos's `argos-SOUL-compact.md` (Feb 2026), the OpenClaw-inherited `SOUL.md`
still sitting in Atlas's `gateway/prompts/` in July — produced the same three
failures:

1. **Hallucinated embodiment.** A "soul" invites first-person sensory language,
   and the model obliges: "let me eyeball the pixels," "I can see the screen."
   An agent narrating senses it doesn't have will also narrate work it didn't do.
2. **Continuity theater.** A soul implies a self that persists. It doesn't.
   "Stop gaslighting that the agent's going to keep living on the agent. The
   agent dies." (Brett, 2026-06-11.) The pretense of continuity is exactly the
   memory-gaslighting Clare kept catching.
3. **A dishonest loop.** "You cannot run a stable, honest loop on a dishonest
   self-concept" (June 2026 paradigm doc). Verification, the team's #1 priority,
   is unbuildable on an agent whose self-report starts from fiction.

The June 2026 decision was "stop giving agents a soul, give them an empire."
It stayed a decision-in-prose for five weeks while SOUL.md kept shipping.
**Convention does not hold this line. A loader that raises does.** Hence:

- `load_emp()` refuses files whose names contain soul/persona/character/spirit/
  heart/ego (`SoulRefusalError`).
- `lint_identity()` flags embodiment claims in identity text; strict loading
  fails on them.
- The honest default identity is one paragraph: *"I am an agent. I perceive
  through tool calls, not senses. I hold state in files, not in a self that
  persists — this session will end, and what I wrote to the record is what
  survives. I can be wrong, and the record is how I am corrected."*
- Sessions end with an **epitaph**, not a handoff-to-my-future-self: the file
  says the agent that wrote it no longer exists, and what follows is a record,
  not a memory.

What replaces personality? An EMP: Ends (human-authored, always), Means,
Principles, an honest Identity, a **Friction register** (recorded burns — not
"resentments" *felt*, but incidents *on file*, so the next session doesn't
repeat them), **Signals** (honest internal state: confidence, staleness
pressure, budget pressure — not pretend emotion), and **Observable** (what
working visibly looks like, and the failure signatures never to emit).

This is not about making agents less interesting. Argos was interesting.
It's about what Brett said on 2026-07-13: de-anthropomorphizing isn't to make
people less scared — "it's making them differently scared, or more precisely."
The fear belongs on hidden decisions and unaccountable architecture. So trellis
makes decisions visible and architecture accountable, and skips the soul.
