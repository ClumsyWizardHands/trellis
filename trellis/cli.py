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
            r.line("WARN", "Discord ACT", f"ARMED to send to {len(acts)} surface(s) — every send still stages for the owner's approval (refusal #5); keep empty unless intended")

    # --- portal auth ---
    if os.environ.get("TRELLIS_APPROVER_SECRET", "").strip():
        r.line("OK", "portal auth", "stable TRELLIS_APPROVER_SECRET set")
    else:
        r.line("WARN", "portal auth", "no secret — portal mints a one-time console token each boot")

    # --- Google Drive (the onboarding source; honest about the grant state) ---
    _check_google(r)

    # --- transcript + document folders (each may be a comma-separated list) ---
    for label, var in (("transcripts", "TRELLIS_TRANSCRIPTS_DIR"),
                       ("docs folders", "TRELLIS_DOCS_DIRS")):
        dirs = [p.strip() for p in os.environ.get(var, "").split(",") if p.strip()]
        if not dirs:
            r.line("SKIP", label, f"{var} unset")
            continue
        for d in dirs:
            if Path(d).expanduser().is_dir():
                r.line("OK", label, d)
            else:
                r.line("FAIL", label, f"{d} is not a directory")

    # --- onboarding consent (has the human said yes to learning?) ---
    _check_onboarding(r)

    print()
    if r.failed:
        print("NOT READY — fix the ✗ lines above.")
        return 1
    print("READY (for what is configured; SKIP lines are simply not set up yet).")
    return 0


def _check_google(r: _Report) -> None:
    """The Google surface has a real intermediate state — code wired, human
    grant pending — and doctor reports it as exactly that, never READY."""
    from .google_source import google_status
    st = google_status()
    if not (st["client_secret_configured"] or st["token_store_configured"]
            or st["folder_configured"]):
        r.line("SKIP", "Google Drive", "TRELLIS_GOOGLE_* / TRELLIS_DRIVE_FOLDER unset")
        return
    if st["ready"]:
        # config + token present; no network call was made, so this is
        # config-verified, not reachability-verified — say so.
        r.line("OK", "Google Drive",
               "granted (token store present; reachability checked at first read)")
    else:
        r.line("WARN", "Google Drive", f"wired, awaiting the human's grant — {st['detail']}")


def _check_onboarding(r: _Report) -> None:
    from .ledger import Ledger
    from .onboard import consent_state
    ledger_path = Path(config.ledger_path())
    if not ledger_path.is_file():
        r.line("SKIP", "onboarding", "no ledger yet — run `trellis begin`")
        return
    try:
        state = consent_state(Ledger(ledger_path))
    except Exception as e:
        r.line("WARN", "onboarding", f"could not read consent state: {e}")
        return
    if state == "granted":
        r.line("OK", "onboarding", "consent granted — learning may run")
    elif state == "declined":
        r.line("WARN", "onboarding", "consent DECLINED — trellis will not read; "
                                     "run `trellis begin` to ask again")
    else:
        r.line("SKIP", "onboarding", "not begun — run `trellis begin`")


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
    import os
    import tempfile
    # Overridable so tests (and concurrent processes) get an ISOLATED state dir —
    # a fixed shared path collided when several demos ran at once. The default
    # stays a stable, human-inspectable location for a single real user.
    override = os.environ.get("TRELLIS_DEMO_STATE")
    if override:
        return Path(override)
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


def _discord_client_from_env(iso=None, urlopen=None):
    """Construct the stdlib-only DiscordClient from env when a bot token is set, else
    None. Returning None is the 'Discord not configured — stay inert' signal the
    runner's poll step branches on: no token, no polling, no bytes on the wire. The
    token is fetched on demand by the client (never here, never logged)."""
    if not os.environ.get("TRELLIS_DISCORD_TOKEN", "").strip():
        return None
    from .isolation import Isolation
    from .discord_api import DiscordClient
    iso = iso or Isolation.from_env()
    return DiscordClient(identity_or_token_env=iso.identity, urlopen=urlopen)


def _run_runner(runner, client, cadence) -> None:  # pragma: no cover - interactive loop
    """Drive the always-on loop. A configured DiscordClient is attached as the
    runner's poll step (runner.discord), so each tick actually polls the
    allowlisted surfaces — the prior feature-detection probed for a
    `poll_client` parameter Runner.run never grew, so `trellis run` claimed
    'Discord poll wired' while never polling (noticed in the onboarding build;
    see docs/ONBOARDING-NOTES-FROM-FABLE.md)."""
    if client is not None and runner.discord is None:
        from .isolation import Isolation
        from .registry import IdentityRegistry
        from .runner import DiscordPoll
        iso = Isolation.from_env()
        iso, surfaces, _note = _discord_read_scope(iso, client, runner.ledger)
        runner.discord = DiscordPoll(client, iso, IdentityRegistry(runner.ledger),
                                     runner.ledger, surfaces=surfaces)
    runner.run(handlers={}, cadence=cadence)


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

    from .isolation import Isolation
    from .runner import default_cadence
    runner = _build_runner()
    cadence = (timedelta(seconds=args.every) if getattr(args, "every", None)
               else default_cadence())
    # When Discord is configured, construct the client from env and hand it to the
    # runner's poll step (Stage-2). Unconfigured → None → the runner stays offline.
    iso = Isolation.from_env()
    client = _discord_client_from_env(iso)
    if client is not None:
        print(f"  · Discord poll wired ({len(iso.allow.read)} read surface(s)); "
              "every send still stages for the owner's ✅")
    print(f"trellis run — always-on while this process lives; tick every "
          f"{cadence.total_seconds():.0f}s (Ctrl-C to stop)")
    try:
        _run_runner(runner, client, cadence)
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\nstopped.")
    return 0


# ---------- discord (the in-Discord approval gesture, D38) ----------

def cmd_discord(args: argparse.Namespace) -> int:
    """Construct the in-Discord approval gateway from env and (would) run the live
    loop. This is an OPERATOR step: it needs a trellis-owned bot token (D30) and an
    explicit ACT allowlist, plus the owner's Discord user id — the only id whose
    reaction may approve. It never connects or sends on import or in tests; without
    the required config it prints exactly what is missing and returns, and even
    fully configured it stops at the live-connection seam (unbuilt on purpose)."""
    config.load_dotenv()
    from .isolation import Isolation
    from .ledger import Ledger
    from .registry import IdentityRegistry
    from .stage import Outbox
    from .executor import DiscordExecutor, urllib_discord_sender
    from .discord_gateway import ApprovalGateway, DiscordGatewayConnection

    token = os.environ.get("TRELLIS_DISCORD_TOKEN", "").strip()
    owner = os.environ.get("TRELLIS_APPROVER_DISCORD_ID", "").strip()
    iso = Isolation.from_env()
    missing = []
    if not token:
        missing.append("TRELLIS_DISCORD_TOKEN (a trellis-OWNED bot token, D30)")
    if not owner:
        missing.append("TRELLIS_APPROVER_DISCORD_ID (the owner's Discord user id — "
                       "the only reactor whose ✅ approves)")
    if not iso.allow.act:
        missing.append("TRELLIS_ACT_SURFACES (the ACT allowlist — where trellis may send)")
    if missing:
        print("trellis discord — the in-Discord approval gesture is not configured yet:\n",
              file=sys.stderr)
        for m in missing:
            print(f"  ✗ set {m}", file=sys.stderr)
        print("\nNothing connects or sends until these are set. The approval MAPPING "
              "is already built and unit-tested (ApprovalGateway); this entrypoint only "
              "wires it to the live gateway once you provide the bot token + allowlist.",
              file=sys.stderr)
        return 1

    # Construct the gateway (no network here — a DiscordClient touches the wire only
    # at send/poll time). The executor is the hardened DiscordExecutor: it re-checks
    # the ledger for a durable APPROVED before any byte leaves (defense in depth on
    # refusal #5), guards the act surface (D30), then posts via the stdlib-only
    # DiscordClient — resolving a Surface.DM to a channel via open_dm first.
    ledger = Ledger(config.ledger_path())
    outbox = Outbox(ledger)
    registry = IdentityRegistry(ledger)

    # The real, DiscordClient-backed send transport. Built here, never in tests; it
    # posts nothing until reached through approve→fire AND past guard_act + the
    # ledger-approval re-check inside DiscordExecutor.
    send_fn = urllib_discord_sender(iso)
    executor = DiscordExecutor(iso, send_fn=send_fn, ledger=ledger)
    gateway = ApprovalGateway(ledger=ledger, iso=iso, registry=registry, outbox=outbox,
                              executor=executor.execute, approver_discord_id=owner)
    print("trellis discord — gateway constructed "
          f"(owner={owner}, {len(iso.allow.act)} act surface(s)). "
          "Every send still stays staged for the owner's ✅ (refusal #5 / W3).")
    # The live gateway loop is the operator seam — it requires the real bot client
    # and is not opened here (never in tests).
    DiscordGatewayConnection(gateway, bot_token=token).run()
    return 0


# ---------- begin (the onboarding ritual, D12's purest expression) ----------


def _env_list(name: str) -> list:
    """A comma-separated env var as a clean list — several transcript folders,
    several granted Drive folder ids. Empty/unset → []."""
    return [p.strip() for p in os.environ.get(name, "").split(",") if p.strip()]


def _workspace_root() -> Path:
    """The map's home: the Obsidian vault when configured (the record's
    navigable face, D21), else a workspace beside the ledger."""
    vp = config.vault_path()
    if vp:
        return Path(vp).expanduser()
    return Path(config.ledger_path()).parent / "workspace"


def _discord_read_scope(iso, client, ledger):
    """Resolve the READ scope (D40). With TRELLIS_DISCORD_GUILD set and
    TRELLIS_READ_SURFACES unset or `auto`, the allowlist is DERIVED from what
    trellis's own bot identity can actually see in that server — every public
    channel plus every private one it was invited into; the grant is edited in
    Discord, not in .env. An explicit id list still wins when given. Returns
    (iso, surfaces, note) — surfaces is None when no discovery ran."""
    reads_raw = os.environ.get("TRELLIS_READ_SURFACES", "").strip().lower()
    guild = os.environ.get("TRELLIS_DISCORD_GUILD", "").strip()
    if client is None or not guild or (reads_raw and reads_raw != "auto"):
        return iso, None, None
    from .backfill import discover_guild_read_surfaces
    from .isolation import Isolation, SurfaceAllowlist
    try:
        disc = discover_guild_read_surfaces(client, ledger, guild)
    except Exception as e:
        return iso, None, (f"guild discovery failed ({e}) — falling back to "
                           "the explicit TRELLIS_READ_SURFACES list")
    iso2 = Isolation(identity=iso.identity,
                     allow=SurfaceAllowlist(read=disc.read_ids,
                                            act=iso.allow.act))
    note = (f"read scope from the server itself: {len(disc.surfaces)} "
            f"channel(s) visible to my bot identity"
            + (f"; {len(disc.no_access)} refused (recorded)" if disc.no_access else ""))
    return iso2, list(disc.surfaces), note


def _onboard_sources_desc(iso) -> list:
    desc = []
    has_token = bool(os.environ.get("TRELLIS_DISCORD_TOKEN", "").strip())
    guild = os.environ.get("TRELLIS_DISCORD_GUILD", "").strip()
    reads_raw = os.environ.get("TRELLIS_READ_SURFACES", "").strip().lower()
    if has_token and guild and (not reads_raw or reads_raw == "auto"):
        desc.append("the Discord server's history — everything my own bot "
                    "identity can see there (every public channel, and any "
                    "private one it was invited into)")
    elif has_token and iso.allow.read:
        desc.append(f"the Discord history of {len(iso.allow.read)} allowlisted "
                    "channel(s) — and nothing outside that list")
    for d in _env_list("TRELLIS_TRANSCRIPTS_DIR"):
        desc.append(f"the transcripts in {d}")
    for d in _env_list("TRELLIS_DOCS_DIRS"):
        desc.append(f"the documents in {d}")
    gfolders = _env_list("TRELLIS_DRIVE_FOLDER")
    if gfolders:
        desc.append(f"{len(gfolders)} granted Google Drive folder(s) "
                    f"({', '.join(gfolders)})")
    if not desc:
        desc.append("nothing yet — no sources are configured; I would sit "
                    "ready until you grant one")
    return desc


def _build_onboarding(ledger, iso, registry, seed_terms):
    """Construct the coordinated set: the maker seat, the independent Haiku
    verifier panel, the source adapters, and the Discord backfill — each
    optional, each honest about its absence. Returns (ritual, sources,
    backfill, client, notes) where notes are human-readable wiring truths."""
    from .memory import Workspace
    from .onboard import OnboardingRitual
    from .verify import RuleVerifier
    notes = []

    provider = None
    verifier = None
    try:
        from .providers import provider_from_env
        provider = provider_from_env()
        notes.append(f"model seat: {getattr(provider, 'id', '?')}")
    except Exception as e:
        notes.append(f"model seat unavailable ({e}) — I will trace lineage "
                     "deterministically but propose no meanings")
    if provider is not None:
        try:
            from .providers.factory import verifier_provider_from_env
            from .panel import VerifierPanel
            vseat = verifier_provider_from_env(provider)
            verifier = VerifierPanel(
                "onboard-panel", vseat, ledger=ledger,
                rule_verifier=RuleVerifier("onboard-panel:floor", ledger))
            notes.append(f"verifier panel: 4 lenses on {getattr(vseat, 'id', '?')} "
                         "(refute-by-default; maker≠verifier)")
        except Exception as e:
            notes.append(f"verifier seat unavailable ({e}) — mapped meanings "
                         "will STAY unresolved rather than self-certify")

    sources = []
    tdirs = _env_list("TRELLIS_TRANSCRIPTS_DIR")
    ddirs = _env_list("TRELLIS_DOCS_DIRS")
    if tdirs or ddirs:
        from .transcripts import TranscriptFolderAdapter
        for d in tdirs:
            sources.append(TranscriptFolderAdapter(d))
        for d in ddirs:
            # a documents folder (principles checks, protocols, reference docs)
            # rides the same adapter with an HONEST kind — not everything on
            # disk is a transcript.
            sources.append(TranscriptFolderAdapter(d, source="docs",
                                                   kind="document"))
    gfolders = _env_list("TRELLIS_DRIVE_FOLDER")
    if gfolders:
        from .google_source import GoogleDriveAdapter, google_status
        st = google_status()
        for f in gfolders:
            sources.append(GoogleDriveAdapter(folder_id=f))
        if not st["ready"]:
            notes.append(f"Google Drive wired, awaiting the human's grant — {st['detail']}")

    backfill = None
    surfaces = None
    client = _discord_client_from_env(iso)
    if client is not None:
        iso, surfaces, scope_note = _discord_read_scope(iso, client, ledger)
        if scope_note:
            notes.append(scope_note)
        from .backfill import DiscordBackfill
        backfill = DiscordBackfill(client, iso, registry, ledger,
                                   surfaces=surfaces)
        notes.append(f"Discord backfill: {len(iso.allow.read)} read surface(s), "
                     "oldest→newest, resumable")

    # check-in digests: when an ACT surface is armed, new learnings STAGE a
    # digest there (posts only after the owner's ✅) — the discussion comes to
    # the human instead of waiting to be found.
    outbox, checkin_target = None, ""
    if iso.allow.act:
        from .stage import Outbox
        checkin_target = sorted(iso.allow.act)[0]
        outbox = Outbox(ledger, iso=iso)
        notes.append(f"check-in digests stage to {checkin_target} when "
                     "something settles or breaks (still your ✅ to post)")

    workspace = Workspace(_workspace_root(), ledger)
    ritual = OnboardingRitual(ledger, workspace, provider=provider,
                              verifier=verifier, registry=registry,
                              seed_terms=seed_terms,
                              outbox=outbox, checkin_target=checkin_target)
    return ritual, sources, backfill, client, iso, surfaces, notes


def _print_pass_summary(summary: dict) -> None:
    print(f"\n— learning pass: {summary['status']} —")
    if summary.get("backfill"):
        b = summary["backfill"]
        print(f"  backfill: {'caught up' if b.get('all_caught_up') else 'in progress'} "
              f"({len(b.get('surfaces', []))} surface(s))")
    for name, res in (summary.get("ingested") or {}).items():
        print(f"  {name}: {res['processed']} new, {res['corrected']} corrected, "
              f"{res['skipped_duplicate']} already known")
    for a in summary.get("awaiting", []):
        print(f"  ! {a['source']}: {a['why']}")
    minted = [t for t in summary.get("terms_minted", []) if t]
    if minted:
        print(f"  curious about: {', '.join(minted)}")
    for p in summary.get("terms_pursued", []):
        print(f"  · '{p['term']}' — {p['outcome']}")
    for t in summary.get("presence_questions", []):
        print(f"  ? {t}")
    print(f"  open unknowns on the record: {summary.get('open_unknowns', 0)}")
    comp = summary.get("comprehension")
    if comp:
        print(f"  comprehension: walked {comp['walked']}/{comp['ingested']} "
              f"ingested items ({comp['pct_walked']}%) · "
              f"{comp['terms_known']} meaning(s) known, {comp['terms_open']} open "
              "— ingested is not understood; this takes many sessions")
    if summary.get("checkin"):
        print(f"  check-in written: {summary['checkin']}"
              + (" (digest STAGED for your ✅)" if summary.get("checkin_staged") else ""))


def cmd_begin(args: argparse.Namespace) -> int:
    """The initialize command: introduce, ask consent, then bring up the whole
    coordinated set (backfill + sources + learning loop + verifier panel) under
    the runner. `--once` runs a single pass and exits; default stays resident."""
    config.load_dotenv()
    from datetime import timedelta

    from .isolation import Isolation
    from .ledger import Ledger
    from .onboard import (ONBOARD_SCHEDULE, consent_state, introduction_text,
                          onboarding_handler, record_consent,
                          record_introduction)
    from .registry import IdentityRegistry
    from .runner import DiscordPoll, budget_from_env, default_cadence

    ledger = Ledger(config.ledger_path())
    iso = Isolation.from_env()
    registry = IdentityRegistry(ledger)
    human = os.environ.get("TRELLIS_HUMAN", "operator").strip() or "operator"

    intro = introduction_text(_onboard_sources_desc(iso))
    state = consent_state(ledger)
    if state == "granted":
        print("(consent is already on the record — resuming the learning "
              "loop; nothing needs re-asking)\n")
    else:
        print(intro + "\n")
        answer = (args.answer or input("> ")).strip().lower()
        granted = answer in ("y", "yes")
        record_consent(ledger, human, granted,
                       note=f"answered {answer!r} at the terminal")
        if not granted:
            record_introduction(ledger, "trellis-onboard", intro)
            print("\nUnderstood — I won't read anything. The 'no' is on the "
                  "record; run `trellis begin` again if you change your mind.")
            return 0
        # If an ACT surface is armed, the introduction is also STAGED as a
        # Discord post — it reaches the server only after the owner's ✅
        # (stage-don't-fire, refusal #5; onboarding posts nothing on its own).
        staged_id = None
        if iso.allow.act:
            from .stage import Outbox, StagedAction
            from .surfaces import ConversationKey, Surface
            target = sorted(iso.allow.act)[0]
            staged_id = Outbox(ledger, iso=iso).stage(StagedAction(
                kind="discord_post", target=target, content=intro,
                created_by="trellis-onboard",
                destination=ConversationKey(agent=iso.identity.name,
                                            surface=Surface.CHANNEL,
                                            scope=target, human="")))
            print(f"\n(the introduction is STAGED for #{target} — it posts only "
                  "after your ✅; nothing has been sent)")
        record_introduction(ledger, "trellis-onboard", intro,
                            staged_action_id=staged_id)
        print("\nThank you. Beginning — I'll read only what you've granted, "
              "and I'll keep my open questions visible.\n")

    seed_terms = [t.strip() for t in
                  os.environ.get("TRELLIS_ONBOARD_TERMS", "").split(",")
                  if t.strip()]
    ritual, sources, backfill, client, iso, surfaces, notes = _build_onboarding(
        ledger, iso, registry, seed_terms)
    for n in notes:
        print(f"  · {n}")

    handler = onboarding_handler(ritual, sources=sources, backfill=backfill)
    summary = handler()                          # the first pass, right now
    _print_pass_summary(summary)

    if getattr(args, "once", False):
        print("\n(--once: single pass done. `trellis begin` again, or "
              "`trellis run`, to keep learning.)")
        return 0

    runner = _build_runner()
    if client is not None:
        runner.discord = DiscordPoll(client, iso, registry, ledger,
                                     surfaces=surfaces)
    cadence = default_cadence()
    raw = os.environ.get("TRELLIS_ONBOARD_SECONDS", "").strip()
    onboard_every = timedelta(seconds=float(raw)) if raw else timedelta(minutes=30)
    specs = runner.DEFAULT_SCHEDULES + (
        (ONBOARD_SCHEDULE, onboard_every, "the onboarding learning ritual — "
         "map, verify, surface unknowns"),)
    print(f"\ntrellis begin — learning in the background every "
          f"{onboard_every.total_seconds():.0f}s while this process lives "
          "(Ctrl-C to stop; the ledger resumes me)")
    try:
        import time
        while True:
            runner.tick(handlers={ONBOARD_SCHEDULE: handler}, specs=specs)
            time.sleep(cadence.total_seconds())
    except KeyboardInterrupt:  # pragma: no cover - interactive
        print("\nstopped — everything learned is on the record; a restart "
              "picks up where this left off.")
    return 0


# ---------- google (the human's one-time browser grant) ----------


def cmd_google(args: argparse.Namespace) -> int:
    config.load_dotenv()
    from .google_source import GoogleNotGranted, google_status, run_grant_flow
    if args.action == "status":
        st = google_status()
        for k, v in st.items():
            print(f"  {k}: {v}")
        return 0
    # action == "grant" — the HUMAN's browser approval; trellis passes paths only
    cs = os.environ.get("TRELLIS_GOOGLE_CLIENT_SECRET", "").strip()
    ts = os.environ.get("TRELLIS_GOOGLE_TOKEN_STORE", "").strip()
    if not cs or not ts:
        print("set TRELLIS_GOOGLE_CLIENT_SECRET (the Desktop-app OAuth client "
              "JSON path) and TRELLIS_GOOGLE_TOKEN_STORE (where Google's client "
              "should keep the token) in .env first", file=sys.stderr)
        return 1
    try:
        path = run_grant_flow(cs, ts)
    except GoogleNotGranted as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    print(f"✓ granted — Google's client wrote the token store at {path}. "
          "trellis never saw the secret.")
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
    sub.add_parser("discord", help="run the in-Discord approval gesture "
                                   "(needs a trellis-owned bot token + ACT allowlist)")
    b = sub.add_parser("begin", aliases=["onboard"],
                       help="introduce, ask consent, then map this place — "
                            "the begin-learning ritual (stays resident)")
    b.add_argument("--once", action="store_true",
                   help="run a single learning pass and exit (no resident loop)")
    b.add_argument("--answer", default=None, help=argparse.SUPPRESS)  # tests only
    g = sub.add_parser("google", help="the human's one-time Google grant "
                                      "(browser OAuth; trellis never sees the secret)")
    g.add_argument("action", choices=["grant", "status"])

    args = ap.parse_args(argv)
    return {"init": cmd_init, "doctor": cmd_doctor, "demo": cmd_demo,
            "tick": cmd_tick, "run": cmd_run, "web": cmd_web,
            "discord": cmd_discord, "begin": cmd_begin, "onboard": cmd_begin,
            "google": cmd_google}[args.cmd](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
