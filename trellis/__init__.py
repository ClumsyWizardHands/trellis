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

On that spine sits a contemplating mind: memory as navigation (search titles,
walk decisions — navigate.py), the mortality/reflection posture (reflect.py),
and the contemplative backdrop that reads the team's record in and understands
it — idempotent ingestion (sources.py), each decision recorded as an observation
+ the agent's own opinion (observe.py), projected into a reconciled Obsidian
vault (vault.py), with a curiosity loop whose questions nag and where "I
searched" is never "I understand" (curiosity.py).
"""

__version__ = "0.1.0"

from .clock import TimeGround, Staleness
from .ledger import Ledger, Entry
from .emp import EMP, load_emp, SoulRefusalError, lint_identity
from .decisions import (Decision, Verdict, POV, IncompleteTriangulationError,
                        DecisionLog, CollidingDecisionError, question_key)
from .navigate import (Navigator, Walk, NavHit, ResolvedHeadCache,
                       ReopenRequiredError)
from .reflect import (ReflectionRitual, SelfChange, self_image_stats,
                      reflection_loop_spec, DreadError, UnverifiedSelfChangeError,
                      ReflectionSynthesisError, REFLECTION_KIND)
from .sources import (RawItem, Provenance, Ingestor, IngestResult, SourceAdapter,
                      MARKER_KIND)
from .observe import (Candidate, DecisionObserver, conversation_velocity, Velocity,
                      stable_decision_id, synthesize_read)
from .vault import (VaultReconciler, ReconcileReport, Drift, note_state,
                    render_frontmatter, hash_content)
from .curiosity import (Question, QuestionLog, assumption_key, NotResolvedError,
                        QUESTION_KIND, SEEK_KIND)
from .surfaces import Surface, ConversationKey, PrivacyBoundaryError
from .passes import Pass, PassStatus, TurdDropError, PassExchange
from .loops import LoopSpec, LoopRun, Outcome, LoopRegistry, LoopBudgetExceeded
from .verify import CompletionClaim, Evidence, Verdict as VerifyVerdict  # noqa: F401
from .verify import RuleVerifier, SelfCertificationError
from .stage import Outbox, StagedAction, ActionStatus, UnapprovedFireError
from .memory import Workspace, SynthesisTestError, TitleError
from .prompt import assemble_prompt, PromptBudgetExceeded
from .panel import VerifierPanel, PanelVerdict, panel_as_subagent_specs
from .ingest import (DiscordMessage, CalendarEvent, ingest_discord, ingest_calendar,
                     position_history, PositionHistory, temporal_context)

__all__ = [
    "TimeGround", "Staleness",
    "Ledger", "Entry",
    "EMP", "load_emp", "SoulRefusalError", "lint_identity",
    "Decision", "Verdict", "POV", "IncompleteTriangulationError",
    "DecisionLog", "CollidingDecisionError", "question_key",
    "Navigator", "Walk", "NavHit", "ResolvedHeadCache", "ReopenRequiredError",
    "Workspace", "TitleError",
    "ReflectionRitual", "SelfChange", "self_image_stats", "reflection_loop_spec",
    "DreadError", "UnverifiedSelfChangeError", "ReflectionSynthesisError",
    "REFLECTION_KIND",
    "Surface", "ConversationKey", "PrivacyBoundaryError",
    "Pass", "PassStatus", "TurdDropError", "PassExchange",
    "LoopSpec", "LoopRun", "Outcome", "LoopRegistry", "LoopBudgetExceeded",
    "CompletionClaim", "Evidence", "RuleVerifier", "SelfCertificationError",
    "Outbox", "StagedAction", "ActionStatus", "UnapprovedFireError",
    "Workspace", "SynthesisTestError",
    "assemble_prompt", "PromptBudgetExceeded",
]
