# Running trellis with the Claude Agent SDK

Two composition modes. Both keep trellis's refusals structural.

## Mode A — the SDK as a model seat (simplest)

`ClaudeSDKProvider` implements the trellis `Provider` protocol. The trellis
loop stays in charge (sense → resolve → act → verify → remember); Claude is
the reasoning seat inside it.

```python
from trellis.providers.claude_sdk import ClaudeSDKProvider
from trellis.agent import Witness

provider = ClaudeSDKProvider(model="claude-sonnet-4-5")
verifier_seat = ClaudeSDKProvider(model="claude-haiku-4-5")   # cheaper, fresher
witness = Witness(emp, provider, ledger, workspace, key,
                  verifier=ModelVerifier("checker:haiku", verifier_seat))
```

Note the two seats: the maker and the verifier are different model instances
with different ids — the haiku-verifier pattern (cheap model, fresh context,
refute-oriented prompt) that the July 2026 doctrine ranks as priority #1.

## Mode B — trellis as the SDK agent's spine (hooks)

When you want the SDK to drive (its tools, its sessions, its skills), mount
trellis at the hook points. The refusals map cleanly:

| SDK hook | trellis mount |
|----------|---------------|
| `SessionStart` | assemble the standing prompt (`prompt.assemble_prompt`) — clock injected, EMP kernel, memory map, status rail |
| `UserPromptSubmit` | annotate any retrieved/quoted material with `TimeGround.annotate` before the model sees it |
| `PreToolUse` on outbound tools (post/send/apply) | **block**, stage via `Outbox.stage`, return "staged for approval" — auto-fire is unrepresentable |
| `PostToolUse` | `LoopRun.count_tool_call()` — the tool budget |
| `Stop` | refuse the stop unless the run has a typed outcome; a completion claim with evidence goes to the verifier seat |
| `SessionEnd` | `Workspace.flush(...)` then `Workspace.epitaph(...)` — flush-before-compact, then honest death |

The SDK's own session JSONL remains its business; trellis's ledger is the
durable truth that survives it. The SDK session is hot memory; the ledger and
workspace are the estate.

## What NOT to wire

- Do not give the SDK agent a tool that calls `Outbox.approve` — approval is
  the human seat, and the outbox enforces that, but don't tempt the prompt.
- Do not pass the maker's session as the verifier's context. Fresh context is
  the point: "the bigger the task… the fresher the context window we want."
- Do not auto-install skills from anywhere. Local files, human-reviewed
  (DECISIONS.md W1).
