"""registry.py — the IdentityRegistry: a stable identity so a rename can't
poison attribution. (DECISIONS.md D32; the audit's G11.)

A Discord user-id SNOWFLAKE is permanent and is the real identity; a display
name is a mutable LABEL. This is a ledger-backed projection (rebuildable like
every other, D2/D5) that maps a snowflake to a canonical trellis id — an ASCII
identifier minted via identity.require_identity / normalize_identity, the same
allowlist every gate uses.

Three properties the attribution contract needs:
  * AUTO-REGISTER on first sight — the first resolve of a snowflake appends an
    append-only `identity_registration` carrying the snowflake, the display
    name, and the minted canonical id. The registry (an agent) authors it, so
    attribution holds — the human is the subject, never the author.
  * RENAME-SAFE — a later resolve of the same snowflake with a new display name
    returns the SAME canonical id and appends a label update (append, never
    rewrite — D2). Identity does not move when a name changes.
  * COLLISION-SAFE — two different snowflakes that fold to the same canonical id
    get a discriminator, so two humans are never merged into one id (the round-4
    attribution contract: a canonical id belongs to exactly one person).

Because the minted canonical id is RECORDED in the registration event, a rebuild
reads it back rather than recomputing — a fresh IdentityRegistry over the same
ledger yields exactly the same mapping, deterministically.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .identity import normalize_identity, require_identity
from .ledger import Ledger


@dataclass(frozen=True)
class Identity:
    """One known identity, for the session-log page (D32's session log)."""
    discord_user_id: str      # the snowflake — permanent, the real identity
    canonical_id: str         # the minted ASCII trellis id — never changes
    label: str                # the current display name — mutable
    first_seen: datetime      # when this identity was first registered


class IdentityRegistry:
    REGISTRATION_KIND = "identity_registration"
    LABEL_KIND = "identity_label"
    AUTHOR = "trellis-registry"

    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    # ----- projection (rebuilt from the file, the sole source of truth) -----

    def _project(self):
        """Fold the ledger into the current identity maps. Registration events
        set the canonical id + first_seen (read back, never recomputed — so a
        rebuild is identical); label events (and the registration's own name)
        set the current label, latest write wins."""
        by_snowflake: dict[str, str] = {}          # snowflake -> canonical_id
        canonical_of: dict[str, str] = {}          # canonical_id -> snowflake
        first_seen: dict[str, datetime] = {}       # snowflake -> event_time
        label: dict[str, str] = {}                 # snowflake -> current display name
        order: list[str] = []                      # snowflakes in registration order
        for e in self.ledger.entries():
            if e.kind == self.REGISTRATION_KIND:
                snow = e.body.get("discord_user_id", "")
                cid = e.body.get("canonical_id", "")
                if not snow or not cid or snow in by_snowflake:
                    continue
                by_snowflake[snow] = cid
                canonical_of[cid] = snow
                first_seen[snow] = e.stamp.event_time
                label[snow] = e.body.get("display_name", "")
                order.append(snow)
            elif e.kind == self.LABEL_KIND:
                snow = e.body.get("discord_user_id", "")
                if snow in by_snowflake:
                    label[snow] = e.body.get("display_name", "")
        return by_snowflake, canonical_of, first_seen, label, order

    # ----- mint --------------------------------------------------------------

    @staticmethod
    def _mint(display_name: str, snowflake: str, used: set[str]) -> str:
        """A usable ASCII canonical id for a brand-new snowflake. Prefer a
        readable id from the display name; fall back to the snowflake when the
        name is non-ASCII or blank (so a non-ASCII name never crashes — it just
        gets a snowflake-derived id). A collision with an id already assigned to
        a DIFFERENT snowflake appends a numeric discriminator, so two humans are
        never merged. Deterministic given ledger order."""
        base = normalize_identity(display_name)
        if not base:
            base = normalize_identity(f"user-{snowflake}") or "user"
        candidate = base
        n = 2
        while candidate in used:
            candidate = f"{base}-{n}"
            n += 1
        return require_identity(candidate)

    # ----- public API --------------------------------------------------------

    def resolve(self, discord_user_id: str, display_name: str = "") -> str:
        """The canonical trellis id for a snowflake, auto-registering on first
        sight and following a rename without moving the identity."""
        snow = (discord_user_id or "").strip()
        if not snow:
            raise ValueError("discord_user_id (snowflake) is required")
        name = (display_name or "").strip()
        # The whole read-then-append is atomic across writers (the mint reads the
        # used-id set that its own registration then extends) so two concurrent
        # first-sights of the same snowflake cannot double-register.
        with self.ledger.write_transaction():
            by_snowflake, _, _, label, _ = self._project()
            if snow in by_snowflake:
                cid = by_snowflake[snow]
                if name and name != label.get(snow, ""):
                    self.ledger.append(
                        self.LABEL_KIND, self.AUTHOR,
                        {"discord_user_id": snow, "canonical_id": cid,
                         "display_name": name})
                return cid
            used = set(by_snowflake.values())
            cid = self._mint(name, snow, used)
            self.ledger.append(
                self.REGISTRATION_KIND, self.AUTHOR,
                {"discord_user_id": snow, "canonical_id": cid, "display_name": name})
            return cid

    def canonical_for(self, discord_user_id: str) -> Optional[str]:
        """The canonical id for a snowflake WITHOUT registering (None if unseen)."""
        by_snowflake, _, _, _, _ = self._project()
        return by_snowflake.get((discord_user_id or "").strip())

    def label(self, canonical_id: str) -> str:
        """The current display name for a canonical id ("" if unknown)."""
        by_snowflake, canonical_of, _, label, _ = self._project()
        snow = canonical_of.get(canonical_id)
        return label.get(snow, "") if snow is not None else ""

    def all(self) -> list[Identity]:
        """Every known identity, in registration order — for the session log."""
        by_snowflake, _, first_seen, label, order = self._project()
        return [
            Identity(
                discord_user_id=snow,
                canonical_id=by_snowflake[snow],
                label=label.get(snow, ""),
                first_seen=first_seen[snow],
            )
            for snow in order
        ]
