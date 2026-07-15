#!/usr/bin/env python3
"""A complete witness cycle, offline — no API key, no network.

This demonstrates the whole trellis working at once: EMP loading (with the
soul refusal live), age-annotated sensing, Y/N/T opinions with lineage, the
bounded loop, external verification, the staged outbox, and the epitaph.

Run:  python3 examples/run_witness.py
Swap MockProvider for ClaudeSDKProvider or OpenAICompatProvider to go live —
nothing else changes.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trellis.agent import Event, Witness
from trellis.clock import TimeGround
from trellis.emp import load_emp
from trellis.ledger import Ledger
from trellis.memory import Workspace
from trellis.providers.mock import MockProvider
from trellis.surfaces import ConversationKey, Surface

HERE = Path(__file__).parent
STATE = HERE / ".state"


def main():
    ground = TimeGround()
    ledger = Ledger(STATE / "ledger.jsonl", ground)
    workspace = Workspace(STATE / "workspace", ledger)
    emp = load_emp(HERE / "witness-emp.md")
    key = ConversationKey("witness:witness", Surface.CHANNEL, "chiefs-of-staffs", "")

    # The model seat. Scripted here; swap in a real provider to go live.
    provider = MockProvider(id="mock-model")
    provider.enqueue_text(json.dumps([
        {
            "subject": "treat the April 'eliminate time-blindness' framing as superseded",
            "verdict": "Y",
            "rationale": "Brett's July statement reframes time-blindness as a "
                         "potential asset; newer supersedes older and the read "
                         "should follow the July framing",
            "emp_lineage": "EMP:principles[5]",
        },
        {
            "subject": "adopt the shared canvas question (Obsidian vs Drive) as settled",
            "verdict": "T",
            "rationale": "the July 11 ruling defers it in favor of verification, "
                         "but the underlying fork is still live",
            "emp_lineage": "EMP:ends[0]",
            "povs": [
                {"holder": "brett", "position": "energy goes to verification, not portals",
                 "basis": "DAPS 2026-07-11 §3.19"},
                {"holder": "clare", "position": "Drive is the wrong portal",
                 "basis": "2026-07-10 discussion"},
                {"holder": "sarah", "position": "Obsidian vault is her working system",
                 "basis": "standing practice"},
            ],
            "owner": "alex",
            "revisit_days": 14,
            "missing": "whether verification tooling changes the portal answer",
        },
    ]))

    now = ground.now()
    events = [
        Event("brett", "time blindness is a liability we must eliminate",
              now - timedelta(days=84)),
        Event("brett", "if you stare at that liability long enough, you might "
                       "just find some ways to turn it into an asset",
              now - timedelta(days=1)),
        Event("clare", "the shared canvas question keeps coming back",
              now - timedelta(hours=3)),
    ]

    print("— witness cycle —")
    outcome = witness_run(emp, provider, ledger, workspace, key, events, ground)
    print(f"outcome: {outcome.value}")

    print("\n— the read (written beside the agent) —")
    print(workspace.read("read/current-read.md"))

    print("\n— decisions on the record —")
    for e in ledger.current("decision"):
        print(f"  [{e.body['verdict']}] {e.body['subject']}  "
              f"(lineage: {e.body['emp_lineage']})")

    print("\n— verification (by a non-maker) —")
    for e in ledger.entries():
        if e.kind == "verification":
            print(f"  {e.body['status']} — verifier {e.author!r} on maker "
                  f"{e.body['maker']!r}")

    # The witness wants to post a digest. It can only stage it.
    print("\n— staging outbound (nothing fires) —")
    w = _last_witness
    aid = w.propose_outbound("discord_post", "#chiefs-of-staffs",
                             "Read updated: July framing of time-blindness "
                             "adopted; canvas question is a live T owned by Alex.")
    print(f"  staged action {aid}; pending human approval: "
          f"{len(w.outbox.pending())} action(s)")

    # Session ends honestly.
    workspace.flush("example-session", w.id, survivors=[])
    workspace.epitaph(
        "example-session", w.id,
        what_happened="one witness cycle over three events; two opinions recorded",
        what_was_learned="the July reframe supersedes April; canvas fork still live",
        open_threads=["approve or deny the staged digest",
                      "resolve the canvas T by its revisit date"])
    print("\n— epitaph written; the agent dies, the record survives —")


_last_witness = None

def witness_run(emp, provider, ledger, workspace, key, events, ground):
    global _last_witness
    w = Witness(emp, provider, ledger, workspace, key, ground=ground)
    _last_witness = w
    return w.witness_cycle(events)


if __name__ == "__main__":
    main()
