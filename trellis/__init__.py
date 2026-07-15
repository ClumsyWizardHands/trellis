"""trellis — an agent harness that is a trellis, not a soul.

Infrastructure for agents whose job is contextual understanding and
principled opinion, not task completion. Built from the failure record
of every agent that came before it (see DECISIONS.md and LINEAGE.md).

The five refusals (structural, not aspirational):
  1. No silent failure   — every loop run ends in a typed outcome (loops.py)
  2. No self-certification — maker != verifier, enforced (verify.py)
  3. No soul.md          — identity is an honest EMP (emp.py)
  4. No naked now()      — all state is bitemporal (ledger.py, clock.py)
  5. No auto-fire        — outbound actions are staged for a human (stage.py)
"""

__version__ = "0.1.0"

from .clock import TimeGround, Staleness
from .ledger import Ledger, Entry
from .emp import EMP, load_emp, SoulRefusalError, lint_identity
from .decisions import Decision, Verdict, POV, IncompleteTriangulationError
from .surfaces import Surface, ConversationKey, PrivacyBoundaryError
from .passes import Pass, PassStatus, TurdDropError, PassExchange
from .loops import LoopSpec, LoopRun, Outcome, LoopRegistry, LoopBudgetExceeded
from .verify import CompletionClaim, Evidence, Verdict as VerifyVerdict  # noqa: F401
from .verify import RuleVerifier, SelfCertificationError
from .stage import Outbox, StagedAction, ActionStatus, UnapprovedFireError
from .memory import Workspace, SynthesisTestError
from .prompt import assemble_prompt, PromptBudgetExceeded

__all__ = [
    "TimeGround", "Staleness",
    "Ledger", "Entry",
    "EMP", "load_emp", "SoulRefusalError", "lint_identity",
    "Decision", "Verdict", "POV", "IncompleteTriangulationError",
    "Surface", "ConversationKey", "PrivacyBoundaryError",
    "Pass", "PassStatus", "TurdDropError", "PassExchange",
    "LoopSpec", "LoopRun", "Outcome", "LoopRegistry", "LoopBudgetExceeded",
    "CompletionClaim", "Evidence", "RuleVerifier", "SelfCertificationError",
    "Outbox", "StagedAction", "ActionStatus", "UnapprovedFireError",
    "Workspace", "SynthesisTestError",
    "assemble_prompt", "PromptBudgetExceeded",
]
