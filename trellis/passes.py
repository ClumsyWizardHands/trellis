"""passes.py — agents talk through passes, not vibes. (DECISIONS.md D8)

"A ball well-passed and well-received is the fundamental unit of all
coordination." A good pass writes 50–90% of the receiver's prompt for them
(Brett). The failure modes on record:

  * the turd-drop: "I did some initial thinking on it and handed it off to
    you with no clear ask on it basically." — Peter, 2026-05-12
  * no tracking: "we don't have a mechanism… to track our passes" — Clare,
    2026-07-10; Sarah wants "a bouncing basketball on my phone when I
    received a pass."
  * coordination theater: "a polished final artifact, not a back-and-forth
    coordination process that was auditable" — Clare, 2026-03-16

So: a Pass is a FILE — typed, tracked, auditable, comment-threaded. Two agents
coordinate by reading and writing passes in a shared exchange directory (a git
repo, a synced drive, anything with files). No broker, no choreography claims;
the audit trail IS the coordination. Comments-as-protocol is the mechanism
proven in the Hermes kanban (July 2026) — the full comment thread is what a
respawned worker reads to pick up where things stand.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from .clock import TimeGround, parse_iso
from .identity import same_identity


class TurdDropError(Exception):
    """A pass with no clear ask. Rejected at creation, in Peter's honor."""


class PassStatus(str, Enum):
    STAGED = "staged"        # written, not yet sent (stage-don't-fire applies)
    SENT = "sent"
    RECEIVED = "received"    # receiver acknowledged — the bouncing basketball
    ACCEPTED = "accepted"
    DECLINED = "declined"    # a real no, on the record, returnable
    COMPLETED = "completed"
    DROPPED = "dropped"      # explicitly abandoned — never silently


_TRANSITIONS: dict[PassStatus, set[PassStatus]] = {
    PassStatus.STAGED: {PassStatus.SENT, PassStatus.DROPPED},
    PassStatus.SENT: {PassStatus.RECEIVED, PassStatus.DROPPED},
    PassStatus.RECEIVED: {PassStatus.ACCEPTED, PassStatus.DECLINED},
    PassStatus.ACCEPTED: {PassStatus.COMPLETED, PassStatus.DROPPED},
    PassStatus.DECLINED: {PassStatus.SENT},   # returnable: re-shaped and re-sent
    PassStatus.COMPLETED: set(),
    PassStatus.DROPPED: {PassStatus.SENT},    # a drop can be picked back up
}

MIN_ASK_WORDS = 5  # "look at this?" is not an ask


@dataclass
class Comment:
    author: str
    text: str
    at: datetime

    def to_dict(self) -> dict:
        return {"author": self.author, "text": self.text, "at": self.at.isoformat()}

    @staticmethod
    def from_dict(d: dict) -> "Comment":
        return Comment(d["author"], d["text"], parse_iso(d["at"]))


@dataclass
class Pass:
    sender: str
    receiver: str
    ask: str                          # the explicit ask — required, checked
    context: str                      # 50–90% of the receiver's prompt lives here
    deadline: Optional[datetime] = None
    artifacts: list[str] = field(default_factory=list)  # paths/links the receiver needs
    status: PassStatus = PassStatus.STAGED
    comments: list[Comment] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)   # every transition, stamped
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self):
        self._validate()

    def _validate(self) -> None:
        ask_words = self.ask.split()
        # substance, not just token count: "do it now ok pls" and "a b c d e"
        # and "..... ." are five "words" but no ask (found by the adversary, #36).
        meaningful = [w for w in ask_words if len(re.sub(r"\W", "", w)) >= 2]
        distinct = {w.lower() for w in meaningful}
        # distinctness too: "review review review review review" is 5 meaningful
        # words but says one thing five times — no real ask (#36 re-attack).
        if (len(ask_words) < MIN_ASK_WORDS or len(meaningful) < 3
                or len(distinct) < 3 or len(re.sub(r"\W", "", self.ask)) < 12):
            raise TurdDropError(
                f"a pass needs a clear ask with substance (got {len(ask_words)} "
                f"words, {len(distinct)} distinct meaningful). State what the "
                "receiver should DO, by when, and what done looks like.")
        if not self.context.strip():
            raise TurdDropError(
                "a pass with no context makes the receiver reconstruct your "
                "thinking — write the 50-90% of their prompt you owe them")
        if not self.receiver.strip():
            raise TurdDropError("a pass needs a named receiver")
        if self.deadline is not None and self.deadline.tzinfo is None:
            raise TurdDropError(
                "a naive (timezone-less) deadline is refused — it crashes the "
                "overdue check and lies about time (#38)")

    # ----- lifecycle --------------------------------------------------------

    #: which side of the pass may perform each transition. Recorded lifecycles
    #: were not ENFORCED lifecycles until review caught a sender walking its
    #: own pass to COMPLETED while impersonating the receiver.
    _ACTOR_SIDE = {
        PassStatus.SENT: "sender", PassStatus.DROPPED: "sender",
        PassStatus.RECEIVED: "receiver", PassStatus.ACCEPTED: "receiver",
        PassStatus.DECLINED: "receiver", PassStatus.COMPLETED: "receiver",
    }

    def transition(self, to: PassStatus, actor: str, ground: TimeGround,
                   note: str = "") -> None:
        allowed = _TRANSITIONS[self.status]
        if to not in allowed:
            raise ValueError(
                f"illegal pass transition {self.status.value} -> {to.value} "
                f"(allowed: {sorted(s.value for s in allowed)})")
        side = self._ACTOR_SIDE.get(to)
        required = self.sender if side == "sender" else self.receiver
        if side and not same_identity(actor, required):
            raise ValueError(
                f"only the {side} ({required!r}) may move a pass to {to.value} "
                f"— {actor!r} is not the {side}")
        # record the CANONICAL identity, not the raw input: a confusable that
        # resolved to the authorized party shouldn't leave a foreign-looking
        # string in the audit trail (found by the adversary, #37).
        recorded_actor = required if side else actor
        self.history.append({
            "from": self.status.value, "to": to.value,
            "actor": recorded_actor, "actor_typed": actor,
            "at": ground.now().isoformat(), "note": note,
        })
        self.status = to

    def comment(self, author: str, text: str, ground: TimeGround) -> None:
        self.comments.append(Comment(author, text, ground.now()))

    def is_overdue(self, ground: TimeGround) -> bool:
        return (self.deadline is not None
                and self.status not in (PassStatus.COMPLETED, PassStatus.DROPPED,
                                        PassStatus.DECLINED)
                and ground.now() > self.deadline)

    # ----- serialization ----------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id": self.id, "sender": self.sender, "receiver": self.receiver,
            "ask": self.ask, "context": self.context,
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "artifacts": self.artifacts, "status": self.status.value,
            "comments": [c.to_dict() for c in self.comments],
            "history": self.history,
        }

    @staticmethod
    def from_dict(d: dict) -> "Pass":
        p = Pass.__new__(Pass)
        p.id = d["id"]; p.sender = d["sender"]; p.receiver = d["receiver"]
        p.ask = d["ask"]; p.context = d["context"]
        p.deadline = parse_iso(d["deadline"]) if d.get("deadline") else None
        p.artifacts = list(d.get("artifacts", []))
        p.status = PassStatus(d["status"])
        p.comments = [Comment.from_dict(c) for c in d.get("comments", [])]
        p.history = list(d.get("history", []))
        # The trust boundary is the FILE (synced drives, git): a turd-drop
        # written by another tool must not slip in through load. Validate here
        # too — review demonstrated the bypass.
        p._validate()
        return p


class PassExchange:
    """A directory of pass files. Sync it however you already sync things —
    git, shared drive, an uploader. The exchange is auditable with `ls`."""

    def __init__(self, root: Path | str, ground: Optional[TimeGround] = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.ground = ground or TimeGround()

    def _path(self, pass_id: str) -> Path:
        return self.root / f"pass-{pass_id}.json"

    def save(self, p: Pass) -> Path:
        path = self._path(p.id)
        path.write_text(json.dumps(p.to_dict(), indent=2, ensure_ascii=False),
                        encoding="utf-8")
        return path

    def load(self, pass_id: str) -> Pass:
        return Pass.from_dict(json.loads(self._path(pass_id).read_text(encoding="utf-8")))

    def all(self) -> list[Pass]:
        return [Pass.from_dict(json.loads(f.read_text(encoding="utf-8")))
                for f in sorted(self.root.glob("pass-*.json"))]

    def inbox(self, receiver: str) -> list[Pass]:
        """What's waiting for me? The receiving half of coordination."""
        return [p for p in self.all()
                if p.receiver == receiver and p.status == PassStatus.SENT]

    def outstanding(self, sender: str) -> list[Pass]:
        """What did I pass that hasn't landed? Sent-but-never-received passes
        are the drops nobody notices — this query notices."""
        return [p for p in self.all()
                if p.sender == sender
                and p.status in (PassStatus.SENT, PassStatus.RECEIVED,
                                 PassStatus.ACCEPTED)]

    def overdue(self) -> list[Pass]:
        return [p for p in self.all() if p.is_overdue(self.ground)]

    def receiver_prompt(self, p: Pass) -> str:
        """Render a pass as the receiver's working prompt — the pass literally
        writes most of the receiver's prompt, as doctrine says it should."""
        lines = [
            f"# Pass {p.id} — from {p.sender} to {p.receiver}",
            f"status: {p.status.value}"
            + (f" · deadline {p.deadline.isoformat()}" if p.deadline else ""),
            "", "## The ask", p.ask, "", "## Context (read before acting)", p.context,
        ]
        if p.artifacts:
            lines += ["", "## Artifacts"] + [f"- {a}" for a in p.artifacts]
        if p.comments:
            lines += ["", "## Thread so far (this is the coordination record)"]
            lines += [f"- [{c.at.isoformat()}] {c.author}: {c.text}" for c in p.comments]
        return "\n".join(lines)
