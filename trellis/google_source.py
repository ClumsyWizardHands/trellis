"""google_source.py — a THIN Google Drive/Docs source adapter, credential-clean.

The `[google]` extra and the env stubs existed; this builds the missing adapter,
deliberately thin (brief §3):

  * ONE granted folder (D30-style allowlist): `TRELLIS_DRIVE_FOLDER` names the
    single Drive folder id trellis may read. No folder id → the adapter refuses
    to run; it never wanders the whole Drive.
  * CREDENTIAL-CLEAN: trellis never touches a raw OAuth secret. The human runs
    the grant ONCE (`trellis google grant`) — Google's own `google-auth-oauthlib`
    client opens the browser, the human approves, and Google's own library
    writes the token store. This adapter only READS that store via
    `Credentials.from_authorized_user_file` and lets the official client refresh
    it. Nothing is logged, nothing lands on the ledger. (Same posture as the
    `codex`/`claude` seats: the official client owns the credential.)
  * HONEST WHEN UNGRANTED: every missing precondition (library, client secret,
    token store, folder id) raises a typed `GoogleNotGranted` naming exactly
    what the human still has to do — and `google_status()` gives `trellis
    doctor` the same truth as a dict. "Wired, awaiting the human's grant" is a
    real, reportable state, never a silent stub.
  * IDEMPOTENT: `item_id` is the Drive file id, so a re-scan is a no-op and a
    re-edited doc (new content, same id) is a CORRECTION on the spine. Documents
    land through the same `document_harvester` as local transcripts.

The Google client libraries are imported LAZILY inside methods, so the core
stays zero-dependency: importing this module costs nothing, and only a call
that actually needs Google reaches for the extra.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, Optional

from .clock import parse_iso
from .sources import RawItem

#: least-privilege scope: read-only Drive (covers listing + Docs export).
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

#: Drive mime types we understand. Google Docs export as text; plain/markdown
#: files download as-is. Everything else is counted in `skipped`, never eaten.
_GOOGLE_DOC = "application/vnd.google-apps.document"
_TEXT_MIMES = {"text/plain", "text/markdown", "text/x-markdown"}

_TRANSCRIPT_MARKERS = ("transcript", "notes by gemini", "notes-by-gemini",
                       "meeting-started")


class GoogleNotGranted(Exception):
    """The Google surface is wired but the human has not granted it yet (or the
    optional dependency is not installed). The message says exactly what is
    missing — this is the honest 'awaiting the human's grant' state."""


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def google_status() -> dict:
    """The doctor's view: what is configured, what is granted, what remains.
    Never touches the network; never reads a secret's value into the report."""
    status = {
        "libs_installed": False,
        "client_secret_configured": False,
        "client_secret_exists": False,
        "token_store_configured": False,
        "token_store_exists": False,
        "folder_configured": False,
        "ready": False,
        "detail": "",
    }
    try:
        import googleapiclient  # noqa: F401
        import google_auth_oauthlib  # noqa: F401
        status["libs_installed"] = True
    except ImportError:
        status["detail"] = "pip install 'trellis-harness[google]'"
    cs = _env("TRELLIS_GOOGLE_CLIENT_SECRET")
    ts = _env("TRELLIS_GOOGLE_TOKEN_STORE")
    status["client_secret_configured"] = bool(cs)
    status["client_secret_exists"] = bool(cs) and Path(cs).expanduser().is_file()
    status["token_store_configured"] = bool(ts)
    status["token_store_exists"] = bool(ts) and Path(ts).expanduser().is_file()
    status["folder_configured"] = bool(_env("TRELLIS_DRIVE_FOLDER"))
    status["ready"] = (status["libs_installed"] and status["token_store_exists"]
                       and status["folder_configured"])
    if not status["detail"]:
        if not status["folder_configured"]:
            status["detail"] = "TRELLIS_DRIVE_FOLDER unset (the one granted folder id)"
        elif not status["token_store_exists"]:
            status["detail"] = ("no token store yet — the human runs "
                                "`trellis google grant` once, in a browser")
        else:
            status["detail"] = "granted"
    return status


def _load_credentials(token_store: str):
    """Read the token store Google's own client manages. Refresh through the
    official transport when expired; REFUSE (typed, honest) when absent or
    unusable — trellis never invents or repairs a credential."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError as e:
        raise GoogleNotGranted(
            "the Google client libraries are not installed — "
            "pip install 'trellis-harness[google]'") from e
    p = Path(token_store).expanduser()
    if not p.is_file():
        raise GoogleNotGranted(
            f"no Google token store at {p} — the human runs `trellis google "
            "grant` once (a browser OAuth approval); trellis never handles the "
            "secret itself")
    creds = Credentials.from_authorized_user_file(str(p), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            # refresh IN MEMORY only — the token store is strictly read-only to
            # trellis. Writing back would re-serialize with trellis's narrowed
            # scopes, and if the store is (or was copied from) another agent's
            # token file, that rewrite could clobber the scopes its owner
            # depends on. The refresh token is the durable part; re-refreshing
            # per process is one cheap roundtrip, not a persistence problem.
            creds.refresh(Request())
        else:
            raise GoogleNotGranted(
                f"the Google token at {p} is expired and cannot refresh — "
                "the human re-runs `trellis google grant`")
    return creds


def run_grant_flow(client_secret: str, token_store: str) -> str:
    """The HUMAN's one-time browser grant. Google's own InstalledAppFlow opens
    the browser and returns the credential; Google's own serialization writes
    the token store (0600). trellis passes paths, never secret values. Returns
    the token-store path for the CLI to confirm."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as e:
        raise GoogleNotGranted(
            "google-auth-oauthlib is not installed — "
            "pip install 'trellis-harness[google]'") from e
    cs = Path(client_secret).expanduser()
    if not cs.is_file():
        raise GoogleNotGranted(
            f"no OAuth client secret at {cs} — download the 'Desktop app' OAuth "
            "client JSON from Google Cloud Console and set "
            "TRELLIS_GOOGLE_CLIENT_SECRET to its path")
    flow = InstalledAppFlow.from_client_secrets_file(str(cs), SCOPES)
    creds = flow.run_local_server(port=0)
    ts = Path(token_store).expanduser()
    ts.parent.mkdir(parents=True, exist_ok=True)
    ts.write_text(creds.to_json(), encoding="utf-8")
    try:
        ts.chmod(0o600)
    except OSError:
        pass
    return str(ts)


class GoogleDriveAdapter:
    """A `SourceAdapter` over ONE granted Drive folder.

    `service` is injectable so tests never touch the network (the same
    discipline as `DiscordClient(urlopen=…)`); production leaves it None and the
    adapter builds the official client from the token store on first use."""

    def __init__(self, folder_id: Optional[str] = None,
                 token_store: Optional[str] = None,
                 service=None, page_size: int = 100):
        self.folder_id = (folder_id or _env("TRELLIS_DRIVE_FOLDER")).strip()
        self.token_store = (token_store or _env("TRELLIS_GOOGLE_TOKEN_STORE")).strip()
        self._service = service
        self.page_size = page_size
        self.skipped: list[str] = []     # names we could not read, per scan
        # {file_id: modifiedTime datetime} the caller already holds — an
        # UNCHANGED file's content is not re-downloaded (it would only be
        # hashed and skipped by the spine anyway). ~1,000 exports/pass saved.
        self.known: dict = {}
        self.skipped_unchanged: int = 0

    def _drive(self):
        if self._service is not None:
            return self._service
        try:
            from googleapiclient.discovery import build
        except ImportError as e:
            raise GoogleNotGranted(
                "google-api-python-client is not installed — "
                "pip install 'trellis-harness[google]'") from e
        if not self.token_store:
            raise GoogleNotGranted(
                "TRELLIS_GOOGLE_TOKEN_STORE is unset — where should Google's "
                "client keep the token the human grants?")
        creds = _load_credentials(self.token_store)
        # a BOUNDED transport: without an explicit timeout the Google client
        # blocks FOREVER on a wedged connection — which froze the resident for
        # 68 silent minutes on 2026-07-22. A hung call must become a loud,
        # per-file skip, never an infinite stall.
        try:
            import httplib2
            from google_auth_httplib2 import AuthorizedHttp
            authed = AuthorizedHttp(creds, http=httplib2.Http(timeout=60))
            self._service = build("drive", "v3", http=authed,
                                  cache_discovery=False)
        except ImportError:
            self._service = build("drive", "v3", credentials=creds,
                                  cache_discovery=False)
        return self._service

    # ----- discovery ---------------------------------------------------------

    def discover(self) -> Iterator[RawItem]:
        """Yield one RawItem per readable file in the granted folder. The Drive
        query itself is scoped to the folder — nothing outside it is even
        listed, mirroring the D30 'never fetched, not merely dropped' posture."""
        if not self.folder_id:
            raise GoogleNotGranted(
                "TRELLIS_DRIVE_FOLDER is unset — name the ONE Drive folder id "
                "trellis may read (the D30 posture: an unconfigured surface is "
                "inert, not omnivorous)")
        drive = self._drive()
        self.skipped = []
        self.skipped_unchanged = 0
        page_token = None
        while True:
            resp = drive.files().list(
                q=f"'{self.folder_id}' in parents and trashed=false",
                fields=("nextPageToken, files(id, name, mimeType, "
                        "modifiedTime, createdTime)"),
                pageSize=self.page_size,
                pageToken=page_token,
                # a granted folder may live inside a SHARED DRIVE (empire
                # village does) — without these two flags the v3 API silently
                # returns an EMPTY list for shared-drive content, which would
                # read as "nothing there" instead of the truth. Harmless for
                # My-Drive folders.
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            ).execute()
            for f in resp.get("files", []):
                item = self._to_rawitem(drive, f)
                if item is not None:
                    yield item
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

    def _to_rawitem(self, drive, f: dict) -> Optional[RawItem]:
        fid = str(f.get("id", "") or "")
        name = str(f.get("name", "") or "(untitled)")
        mime = str(f.get("mimeType", "") or "")
        # unchanged-since-last-ingest? skip the content download entirely —
        # the metadata listing already proves there is nothing new to read.
        if fid in self.known:
            try:
                if parse_iso(str(f.get("modifiedTime"))) == self.known[fid]:
                    self.skipped_unchanged += 1
                    return None
            except (TypeError, ValueError):
                pass                     # unparseable time → fetch, be safe
        try:
            if mime == _GOOGLE_DOC:
                raw = drive.files().export(
                    fileId=fid, mimeType="text/plain").execute()
            elif mime in _TEXT_MIMES:
                raw = drive.files().get_media(fileId=fid,
                                              supportsAllDrives=True).execute()
            else:
                self.skipped.append(name)
                return None
        except GoogleNotGranted:
            raise
        except Exception:
            # one unreadable file must not kill the scan — counted, not silent.
            self.skipped.append(name)
            return None
        content = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        when_raw = f.get("modifiedTime") or f.get("createdTime")
        try:
            event_time = parse_iso(str(when_raw))
        except (TypeError, ValueError):
            self.skipped.append(name)    # a file with no honest timestamp is refused
            return None
        low = name.lower()
        is_transcript = any(m in low for m in _TRANSCRIPT_MARKERS)
        return RawItem(
            source="gdrive",
            channel=self.folder_id,
            content=content,
            event_time=event_time,
            item_id=fid,
            kind="transcript" if is_transcript else "document",
            # a Drive doc named like a Meet/Gemini transcript is ASR output —
            # flagged fallible; a human-authored doc is not machine-transcribed.
            machine_transcribed=is_transcript,
            meta=(("title", name), ("mime", mime)),
        )
