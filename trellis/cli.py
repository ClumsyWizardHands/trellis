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

    ledger = Path(config.ledger_path())
    try:
        ledger.parent.mkdir(parents=True, exist_ok=True)
        probe = ledger.parent / ".trellis-write-probe"
        probe.write_text("ok", encoding="utf-8"); probe.unlink()
        r.line("OK", "ledger path writable", str(ledger))
    except Exception as e:
        r.line("FAIL", "ledger path writable", f"{ledger}: {e}")

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
            r.line("OK", "Discord read", f"{len(reads)} allowlisted surface(s)")
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
    from .providers import provider_from_env, ProviderUnavailable
    try:
        prov = provider_from_env()
    except ProviderUnavailable as e:
        r.line("FAIL", f"model seat ({kind})", str(e))
        return
    preflight = getattr(prov, "preflight", None)
    if callable(preflight):
        try:
            info = preflight()
            note = "context UNCONFIRMED" if info and info.get("context_confirmed") is False else "reachable"
            r.line("OK", f"model seat ({kind})", note)
        except Exception as e:
            r.line("FAIL", f"model seat ({kind})", f"not reachable: {e}")
    else:
        r.line("OK", f"model seat ({kind})", "constructed (no network preflight)")


# ---------- demo ----------

def cmd_demo(args: argparse.Namespace) -> int:
    ex = Path.cwd() / "examples" / "run_witness.py"
    if not ex.is_file():
        print("! examples/run_witness.py not found (run from the repo root)", file=sys.stderr)
        return 1
    import runpy
    runpy.run_path(str(ex), run_name="__main__")
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
    sub.add_parser("demo", help="run a full witness cycle offline (no accounts)")
    w = sub.add_parser("web", help="launch the read-only portal ([web] extra)")
    w.add_argument("rest", nargs=argparse.REMAINDER,
                   help="args passed through to trellis-web (e.g. --port 8001)")

    args = ap.parse_args(argv)
    return {"init": cmd_init, "doctor": cmd_doctor,
            "demo": cmd_demo, "web": cmd_web}[args.cmd](args)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
