"""cli.py — the `trellis` command. Zero-dependency (argparse + stdlib only).

Designed so a fresh `git clone` OR a plain unzipped download is turnkey, and so an
AI assistant pointed at this repo can set it up deterministically:

    trellis init      # scaffold .env (+ a generated portal secret) and state/
    trellis doctor    # honestly check what's configured and reachable
    trellis demo      # prove the harness runs offline (no accounts, MockProvider)
    trellis web       # launch the read-only portal (needs the [web] extra)

`doctor` never reports READY for something it could not actually reach — readiness
is verified, not assumed (the harness's own maker≠verifier ethic, applied to setup).
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

from . import config


# ---------- init ----------

def _set_env_line(text: str, key: str, value: str) -> str:
    out, hit = [], False
    for line in text.splitlines():
        if line.strip().startswith(f"{key}="):
            out.append(f"{key}={value}")
            hit = True
        else:
            out.append(line)
    if not hit:
        out.append(f"{key}={value}")
    return "\n".join(out) + "\n"


def cmd_init(args: argparse.Namespace) -> int:
    root = Path.cwd()
    env, example = root / ".env", root / ".env.example"
    if env.exists():
        print(f"✓ keeping existing {env.name} (not overwritten)")
    elif example.exists():
        text = example.read_text(encoding="utf-8")
        sec = secrets.token_urlsafe(32)
        text = _set_env_line(text, "TRELLIS_APPROVER_SECRET", sec)
        env.write_text(text, encoding="utf-8")
        try:
            env.chmod(0o600)
        except OSError:
            pass
        print(f"✓ wrote {env.name} from .env.example (gitignored)")
        print("  generated a random TRELLIS_APPROVER_SECRET for the portal login")
    else:
        print("! no .env.example here — run this from the trellis repo root",
              file=sys.stderr)
        return 1
    state = root / "state"
    state.mkdir(exist_ok=True)
    print(f"✓ ensured {state.name}/ (gitignored — holds your ledger)")
    print("\nNext: edit .env (add a model + any surfaces), then run:  trellis doctor")
    return 0


# ---------- doctor ----------

class _Report:
    def __init__(self) -> None:
        self.failed = False

    def line(self, status: str, label: str, detail: str = "") -> None:
        mark = {"OK": "✓", "SKIP": "·", "WARN": "!", "FAIL": "✗"}.get(status, "?")
        print(f"  {mark} {status:<4} {label}" + (f" — {detail}" if detail else ""))
        if status == "FAIL":
            self.failed = True


def cmd_doctor(args: argparse.Namespace) -> int:
    config.load_dotenv()
    r = _Report()
    print("trellis doctor — configured surfaces are verified, unconfigured ones are skipped\n")

    # --- core ---
    py_ok = sys.version_info >= (3, 10)
    r.line("OK" if py_ok else "FAIL", "python >= 3.10",
           f"{sys.version_info.major}.{sys.version_info.minor}")
    try:
        import trellis  # noqa
        r.line("OK", "import trellis", getattr(trellis, "__version__", "?"))
    except Exception as e:  # pragma: no cover
        r.line("FAIL", "import trellis", str(e))

    _check_ledger(r)

    _check_env_not_tracked(r)

    # --- model seat ---
    kind = config.provider_kind()
    if not kind:
        r.line("SKIP", "model seat", "TRELLIS_PROVIDER unset — set local|openai|claude|mock")
    else:
        _check_provider(r, kind)

    # --- Obsidian vault ---
    vp = config.vault_path()
    if not vp:
        r.line("SKIP", "Obsidian vault", "TRELLIS_VAULT_PATH unset")
    else:
        p = Path(vp).expanduser()
        if p.parent.exists():
            r.line("OK", "Obsidian vault", str(p))
        else:
            r.line("FAIL", "Obsidian vault", f"parent of {p} does not exist")

    # --- Discord (config-level; no token is spent here) ---
    if not os.environ.get("TRELLIS_DISCORD_TOKEN", "").strip():
        r.line("SKIP", "Discord", "TRELLIS_DISCORD_TOKEN unset (inert)")
    else:
        reads = [s for s in os.environ.get("TRELLIS_READ_SURFACES", "").split(",") if s.strip()]
        acts = [s for s in os.environ.get("TRELLIS_ACT_SURFACES", "").split(",") if s.strip()]
        if not reads:
            r.line("WARN", "Discord", "token set but TRELLIS_READ_SURFACES empty (reads nothing)")
        else:
            # No credential or reachability check has run here, so we do NOT
            # claim OK — an unchecked token is UNVERIFIED, not verified (Codex#14).
            r.line("WARN", "Discord read",
                   f"UNVERIFIED — {len(reads)} allowlisted surface(s); token not "
                   "validated (no reachability check built)")
        if acts:
            r.line("WARN", "Discord ACT", f"ARMED to send to {len(acts)} surface(s) — send path is unbuilt; keep empty unless intended")

    # --- portal auth ---
    if os.environ.get("TRELLIS_APPROVER_SECRET", "").strip():
        r.line("OK", "portal auth", "stable TRELLIS_APPROVER_SECRET set")
    else:
        r.line("WARN", "portal auth", "no secret — portal mints a one-time console token each boot")

    print()
    if r.failed:
        print("NOT READY — fix the ✗ lines above.")
        return 1
    print("READY (for what is configured; SKIP lines are simply not set up yet).")
    return 0


def _check_ledger(r: _Report) -> None:
    """Actually open the configured ledger and append to it (in a sibling probe
    file), so `TRELLIS_LEDGER=.` — a path that is a directory, where Ledger()
    constructs but append() fails — is reported as unusable, not READY (Codex#14).
    """
    from .ledger import Ledger
    ledger = Path(config.ledger_path())
    # A path that is itself a directory can never be a JSONL ledger file.
    if ledger.exists() and ledger.is_dir():
        r.line("FAIL", "ledger writable", f"{ledger} is a directory, not a ledger file")
        return
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        probe = ledger.parent / f".trellis-doctor-probe-{os.getpid()}.jsonl"
        Ledger(probe).append("doctor_probe", "doctor", {"probe": True})
        probe.unlink(missing_ok=True)
        r.line("OK", "ledger writable", str(ledger))
    except Exception as e:
        r.line("FAIL", "ledger writable", f"{ledger}: {e}")


def _check_env_not_tracked(r: _Report) -> None:
    """Zip-safe: only meaningful in a git checkout; a plain download has no .git."""
    if not Path(".git").exists():
        r.line("OK", ".env not committed", "no git repo (zip/download) — nothing tracked")
        return
    import subprocess
    try:
        res = subprocess.run(["git", "ls-files", "--error-unmatch", ".env"],
                             capture_output=True, timeout=5)
        if res.returncode == 0:
            r.line("FAIL", ".env not committed", "your .env IS tracked by git — remove it before pushing")
        else:
            r.line("OK", ".env not committed", "gitignored")
    except Exception:
        r.line("SKIP", ".env not committed", "git not available to check")


def _check_provider(r: _Report, kind: str) -> None:
    from .providers import provider_from_env
    try:
        prov = provider_from_env()
    except Exception as e:
        # Any construction/config error (missing var, malformed TRELLIS_MIN_CONTEXT,
        # absent SDK) is a FAIL line — never an uncaught traceback out of doctor.
        r.line("FAIL", f"model seat ({kind})", str(e))
        return
    preflight = getattr(prov, "preflight", None)
    if callable(preflight):
        try:
            info = preflight() or {}
            note = (info.get("note")
                    or ("context UNCONFIRMED" if info.get("context_confirmed") is False
                        else "reachable"))
            r.line("OK", f"model seat ({kind})", note)
        except Exception as e:
            r.line("FAIL", f"model seat ({kind})", f"not reachable: {e}")
    else:
        r.line("OK", f"model seat ({kind})", "constructed (no network preflight)")


# ---------- demo ----------

# The demo EMP travels WITH the package (Codex#19): the demo must run from an
# installed `trellis` even when the source `examples/` directory isn't present.
_DEMO_EMP = """# Witness — the contextual reader
authored-by: Alex Crowell

## Ends
- The team's context is held and current, so no one works functionally blind
- Chiefs can be still, trusting that context isn't being lost while they are

## Means
- Read-only access to the surface (channels, transcripts, files)
- A workspace beside it; the ledger; the pass exchange
- A verifier seat that is not me

## Principles
- Never fail silently
- Never certify my own completions
- An unresolved T is a hidden no
- Stage, don't fire — nothing reaches the world without a human's yes
- Newer supersedes older, and I say so out loud
- Nothing to report is a finding, not a gap — I don't manufacture opinions

## Identity
I am an agent. I perceive through tool calls, not senses. I hold state in
files, not in a self that persists — this session will end, and what I wrote
to the record is what survives. I can be wrong, and the record is how I am
corrected.

## Friction
- 2026-02-22: an agent ignored an explicit ownership instruction ("Lyra takes
  point") and built anyway — I do not assert ownership that wasn't given
- 2026-04-01: work delivered to the wrong channel — I check the key before I stage
- 2026-05-01: private chief discussion leaked cross-channel — DM content never
  flows outward without a logged human declassification

## Signals
- confidence: stated per opinion, grounded in the evidence I actually opened
- staleness-pressure: how old my read's newest input is
- budget-pressure: turns and tool calls remaining in the current loop

## Observable
- Opens a thread and answers inside it; timestamps what it says
- States plainly what it did NOT do and could not verify
- Retrieves with citations; declares uncertainty instead of filling gaps
"""


def run_demo(state_dir: "Path", *, out=print) -> None:
    """A complete witness cycle, offline (no API key, no network), against an
    ISOLATED, freshly-prepared state directory. Packaged so it runs from an
    installed trellis, not only from a source checkout (Codex#19)."""
    import json
    from datetime import timedelta

    from .agent import Event, Witness
    from .clock import TimeGround
    from .emp import load_emp
    from .ledger import Ledger
    from .memory import Workspace
    from .providers.mock import MockProvider
    from .surfaces import ConversationKey, Surface

    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    emp_path = state_dir / "witness-emp.md"
    emp_path.write_text(_DEMO_EMP, encoding="utf-8")

    ground = TimeGround()
    ledger = Ledger(state_dir / "ledger.jsonl", ground)
    workspace = Workspace(state_dir / "workspace", ledger)
    emp = load_emp(emp_path)
    key = ConversationKey("witness:witness", Surface.CHANNEL, "chiefs-of-staffs", "")

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

    out("— witness cycle —")
    w = Witness(emp, provider, ledger, workspace, key, ground=ground)
    outcome = w.witness_cycle(events)
    out(f"outcome: {outcome.value}")

    out("\n— the read (written beside the agent) —")
    out(workspace.read("read/current-read.md"))

    out("\n— decisions on the record —")
    for e in ledger.current("decision"):
        out(f"  [{e.body['verdict']}] {e.body['subject']}  "
            f"(lineage: {e.body['emp_lineage']})")

    out("\n— verification (by a non-maker) —")
    for e in ledger.entries():
        if e.kind == "verification":
            out(f"  {e.body['status']} — verifier {e.author!r} on maker "
                f"{e.body['maker']!r}")

    out("\n— staging outbound (nothing fires) —")
    aid = w.propose_outbound("discord_post", "#chiefs-of-staffs",
                             "Read updated: July framing of time-blindness "
                             "adopted; canvas question is a live T owned by Alex.")
    out(f"  staged action {aid}; pending human approval: "
        f"{len(w.outbox.pending())} action(s)")

    workspace.flush("example-session", w.id, survivors=[])
    workspace.epitaph(
        "example-session", w.id,
        what_happened="one witness cycle over three events; two opinions recorded",
        what_was_learned="the July reframe supersedes April; canvas fork still live",
        open_threads=["approve or deny the staged digest",
                      "resolve the canvas T by its revisit date"])
    out("\n— epitaph written; the agent dies, the record survives —")


def _demo_state_dir() -> "Path":
    import tempfile
    return Path(tempfile.gettempdir()) / "trellis-demo-state"


def cmd_demo(args: argparse.Namespace) -> int:
    import shutil
    fresh = getattr(args, "fresh", False)
    state = _demo_state_dir()
    # Each invocation starts from a clean, isolated state dir, so the demo is
    # idempotently re-runnable — the second run no longer collides on persisted
    # decisions (Codex#19). --fresh additionally clears any legacy repo demo
    # state left by the old examples/.state layout.
    shutil.rmtree(state, ignore_errors=True)
    if fresh:
        shutil.rmtree(Path.cwd() / "examples" / ".state", ignore_errors=True)
    try:
        run_demo(state)
    except Exception as e:  # a broken demo must fail loud, not print half a cycle
        print(f"! demo failed: {e}", file=sys.stderr)
        return 1
    print(f"\n(demo state written under {state} — safe to delete)")
    return 0


# ---------- tick / run (the always-on runner, D37) ----------

def _build_runner():
    """Construct a ledger-backed Runner over the configured ledger + a windowed,
    ledger-derived daily budget. Model handlers are a separate seat (a provider must
    be configured to wire the witness cycle); the runner itself needs no model."""
    from .ledger import Ledger
    from .runner import Runner, budget_from_env
    ledger = Ledger(config.ledger_path())
    budget = budget_from_env(ledger)
    return Runner(ledger, budget=budget)


def _print_health(runner) -> None:
    h = runner.health()
    orphans = h["orphan_starts"]
    if orphans:
        print(f"  ! {len(orphans)} orphaned loop start(s) — a prior hard-kill")
    for name, v in h["schedules"].items():
        mark = "✓" if v.get("ok") else "!"
        print(f"  {mark} schedule {name}: {v.get('reason', '?')}")
    if "budget" in h:
        b = h["budget"]
        print(f"  · budget: {b['spent']}/{b['cap']} {b['unit']} spent today "
              f"({b['remaining']} left)")


def cmd_tick(args: argparse.Namespace) -> int:
    config.load_dotenv()
    runner = _build_runner()
    # No model handlers are wired here (that seat needs a configured provider); the
    # tick still sweeps orphans, registers the standing schedules, enforces the
    # budget, and reports health — the crash-safe scaffolding runs offline.
    report = runner.tick(handlers={})
    if report["swept"]:
        print(f"swept {len(report['swept'])} orphaned loop start(s) "
              "(prior hard-kill → recorded as protocol_violation)")
    if report["budget_blocked"]:
        print("tick skipped: daily budget cap reached — no new work started")
    else:
        fired = report["fired"]
        print(f"ran {len(fired)} due schedule(s)"
              + (": " + ", ".join(f"{n}={o}" for n, o in fired) if fired else ""))
    _print_health(runner)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config.load_dotenv()
    from datetime import timedelta

    from .runner import default_cadence
    runner = _build_runner()
    cadence = (timedelta(seconds=args.every) if getattr(args, "every", None)
               else default_cadence())
    print(f"trellis run — always-on while this process lives; tick every "
          f"{cadence.total_seconds():.0f}s (Ctrl-C to stop)")
    try:
        runner.run(handlers={}, cadence=cadence)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\nstopped.")
    return 0


# ---------- web ----------

def cmd_web(args: argparse.Namespace) -> int:
    try:
        from web.app import main as web_main
    except Exception as e:
        print(f"! the portal needs the web extra: pip install 'trellis-harness[web]'  ({e})",
              file=sys.stderr)
        return 1
    sys.argv = ["trellis-web"] + list(args.rest or [])
    web_main()
    return 0


# ---------- entry ----------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="trellis", description="the trellis harness CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="scaffold .env + state/ (idempotent; never overwrites .env)")
    sub.add_parser("doctor", help="honestly check what is configured and reachable")
    d = sub.add_parser("demo", help="run a full witness cycle offline (no accounts)")
    d.add_argument("--fresh", action="store_true",
                   help="reset demo state before running (also clears legacy examples/.state)")
    sub.add_parser("tick", help="run one always-on pass (sweep, schedule, budget, health)")
    rn = sub.add_parser("run", help="the in-process always-on loop (sleep then tick)")
    rn.add_argument("--every", type=float, default=None,
                    help="seconds between ticks (default TRELLIS_TICK_SECONDS or 900)")
    w = sub.add_parser("web", help="launch the read-only portal ([web] extra)")
    w.add_argument("rest", nargs=argparse.REMAINDER,
                   help="args passed through to trellis-web (e.g. --port 8001)")

    args = ap.parse_args(argv)
    return {"init": cmd_init, "doctor": cmd_doctor, "demo": cmd_demo,
            "tick": cmd_tick, "run": cmd_run, "web": cmd_web}[args.cmd](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
