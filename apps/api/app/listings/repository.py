from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..cloud import (
    firestore_primary,
    get_document,
    persist_document,
    persist_semantic_memory,
    query_documents,
    query_semantic_memory,
)
from ..models import (
    AgentEvent,
    AgentRun,
    DecisionBrief,
    DecisionProfile,
    DecisionWatch,
    DecisionWatchEvent,
    EvidenceRevision,
    EvaluationReport,
    Listing,
    PreferenceProposal,
    PromptRevisionCandidate,
    SemanticMemoryItem,
    Session,
)


_MODULE_PATH = Path(__file__).resolve()
PROJECT_ROOT = _MODULE_PATH.parents[4] if len(_MODULE_PATH.parents) > 4 else Path.cwd()
PRICE_BAND_ORDER = ("LOW", "MEDIUM", "HIGH", "ULTRA_HIGH")
CATALOG_SCHEMA_VERSION = "4"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _normalize_memory_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    vector = normalized.get("embedding")
    if hasattr(vector, "to_map_value"):
        normalized["embedding"] = list(vector.to_map_value().get("value", ()))
    return normalized


class ListingRepository:
    """Durable local catalog used by the API and mirrored to Firestore."""

    def __init__(self, path: str | Path | None = None) -> None:
        configured_path = path or os.getenv("ROAMSTEAD_DATABASE_PATH", "data/roamstead.db")
        self.path = Path(configured_path)
        if not self.path.is_absolute():
            self.path = PROJECT_ROOT / self.path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS listing_catalog (
                    id TEXT PRIMARY KEY,
                    transaction_mode TEXT NOT NULL,
                    city TEXT NOT NULL DEFAULT 'Ho Chi Minh City',
                    price_band TEXT NOT NULL,
                    source_url TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_listing_catalog_mode_seen
                    ON listing_catalog(transaction_mode, last_seen_at DESC);
                CREATE INDEX IF NOT EXISTS idx_listing_catalog_mode_band
                    ON listing_catalog(transaction_mode, price_band);

                CREATE TABLE IF NOT EXISTS listing_refresh (
                    transaction_mode TEXT PRIMARY KEY,
                    last_attempt_at TEXT,
                    last_success_at TEXT,
                    returned_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                );

                CREATE TABLE IF NOT EXISTS catalog_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decision_profiles (
                    profile_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_sessions_profile
                    ON sessions(profile_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS profile_revisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_profile_revisions_profile
                    ON profile_revisions(profile_id, id DESC);

                CREATE TABLE IF NOT EXISTS preference_proposals (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_preference_proposals_profile
                    ON preference_proposals(profile_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS saved_items (
                    profile_id TEXT NOT NULL,
                    listing_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(profile_id, listing_id)
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_agent_runs_profile
                    ON agent_runs(profile_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS agent_events (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, sequence)
                );

                CREATE TABLE IF NOT EXISTS decision_briefs (
                    run_id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluation_reports (
                    id TEXT PRIMARY KEY,
                    passed INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evaluation_reports_created
                    ON evaluation_reports(created_at DESC);

                CREATE TABLE IF NOT EXISTS prompt_revision_candidates (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS semantic_memory (
                    id TEXT PRIMARY KEY,
                    profile_id TEXT NOT NULL,
                    preference_key TEXT,
                    embedding_status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_semantic_memory_profile
                    ON semantic_memory(profile_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_semantic_memory_preference
                    ON semantic_memory(profile_id, preference_key, updated_at DESC);

                CREATE TABLE IF NOT EXISTS decision_watches (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    profile_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    next_run_at TEXT,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_decision_watches_profile
                    ON decision_watches(profile_id, updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_decision_watches_due
                    ON decision_watches(status, next_run_at);

                CREATE TABLE IF NOT EXISTS evidence_revisions (
                    id TEXT PRIMARY KEY,
                    watch_id TEXT NOT NULL,
                    listing_id TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_evidence_revisions_watch
                    ON evidence_revisions(watch_id, created_at ASC);

                CREATE TABLE IF NOT EXISTS decision_watch_events (
                    id TEXT PRIMARY KEY,
                    watch_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(watch_id, sequence)
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(listing_catalog)").fetchall()
            }
            if "city" not in columns:
                connection.execute(
                    "ALTER TABLE listing_catalog ADD COLUMN city TEXT NOT NULL DEFAULT 'Ho Chi Minh City'"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_listing_catalog_city_mode ON listing_catalog(city, transaction_mode, last_seen_at DESC)"
            )
            version = connection.execute(
                "SELECT value FROM catalog_meta WHERE key = 'schema_version'"
            ).fetchone()
            if not version or version["value"] != CATALOG_SCHEMA_VERSION:
                # Schema v4 keys unique real-property images independently so
                # several inventory cards may share one Batdongsan source page.
                connection.execute("DROP TABLE listing_catalog")
                connection.executescript(
                    """
                    CREATE TABLE listing_catalog (
                        id TEXT PRIMARY KEY,
                        transaction_mode TEXT NOT NULL,
                        city TEXT NOT NULL DEFAULT 'Ho Chi Minh City',
                        price_band TEXT NOT NULL,
                        source_url TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        first_seen_at TEXT NOT NULL,
                        last_seen_at TEXT NOT NULL
                    );
                    CREATE INDEX idx_listing_catalog_mode_seen
                        ON listing_catalog(transaction_mode, last_seen_at DESC);
                    CREATE INDEX idx_listing_catalog_mode_band
                        ON listing_catalog(transaction_mode, price_band);
                    CREATE INDEX idx_listing_catalog_city_mode
                        ON listing_catalog(city, transaction_mode, last_seen_at DESC);
                    CREATE INDEX idx_listing_catalog_source
                        ON listing_catalog(source_url);
                    """
                )
                connection.execute("DELETE FROM listing_refresh")
                connection.execute(
                    """
                    INSERT INTO catalog_meta(key, value) VALUES ('schema_version', ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (CATALOG_SCHEMA_VERSION,),
                )

    def list(self, mode: str, limit: int = 100, city: str = "Ho Chi Minh City") -> list[Listing]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json
                FROM listing_catalog
                WHERE transaction_mode = ? AND city = ?
                ORDER BY last_seen_at DESC, id ASC
                LIMIT 400
                """,
                (mode, city),
            ).fetchall()

        if not rows and firestore_primary():
            cloud_items: list[Listing] = []
            for payload in query_documents("listing_catalog", "transaction_mode", mode):
                try:
                    item = Listing.model_validate(payload)
                    if item.city == city:
                        cloud_items.append(item)
                except Exception:
                    continue
            if cloud_items:
                self.save_progress(mode, cloud_items)
                return self.list(mode, limit, city)

        buckets: dict[str, list[Listing]] = {band: [] for band in PRICE_BAND_ORDER}
        for row in rows:
            try:
                item = Listing.model_validate_json(row["payload_json"])
            except Exception:
                continue
            buckets[item.price_band].append(item)

        # Round-robin keeps every available price segment visible instead of
        # allowing one large band to consume the entire 100-item catalog.
        ordered: list[Listing] = []
        while len(ordered) < limit and any(buckets.values()):
            for band in PRICE_BAND_ORDER:
                if buckets[band] and len(ordered) < limit:
                    ordered.append(buckets[band].pop(0))
        return ordered

    def get(self, listing_id: str) -> Listing | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM listing_catalog WHERE id = ?",
                (listing_id,),
            ).fetchone()
        if not row:
            payload = get_document("listing_catalog", listing_id)
            if not payload:
                return None
            try:
                item = Listing.model_validate(payload)
            except Exception:
                return None
            self.save_progress(item.transaction_mode, [item])
            return item
        try:
            return Listing.model_validate_json(row["payload_json"])
        except Exception:
            return None

    def mark_attempt(self, mode: str) -> str:
        attempted_at = _utc_now().isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO listing_refresh(transaction_mode, last_attempt_at)
                VALUES (?, ?)
                ON CONFLICT(transaction_mode) DO UPDATE SET
                    last_attempt_at = excluded.last_attempt_at,
                    last_error = NULL
                """,
                (mode, attempted_at),
            )
        return attempted_at

    def _upsert_items(
        self,
        connection: sqlite3.Connection,
        mode: str,
        items: list[Listing],
        seen_at: str,
    ) -> None:
        for item in items:
            connection.execute(
                """
                INSERT INTO listing_catalog(
                    id, transaction_mode, city, price_band, source_url,
                    payload_json, first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    transaction_mode = excluded.transaction_mode,
                    city = excluded.city,
                    price_band = excluded.price_band,
                    source_url = excluded.source_url,
                    payload_json = excluded.payload_json,
                    last_seen_at = excluded.last_seen_at
                """,
                (
                    item.id,
                    mode,
                    item.city,
                    item.price_band,
                    item.source_url,
                    item.model_dump_json(),
                    seen_at,
                    seen_at,
                ),
            )

    def save_progress(self, mode: str, items: list[Listing]) -> dict[str, Any]:
        """Persist validated batches without starting a new weekly success window."""
        if not items:
            return self.status(mode)
        now_iso = _utc_now().isoformat()
        with self._connect() as connection:
            self._upsert_items(connection, mode, items, now_iso)
        return self.status(mode, items[0].city)

    def save_success(self, mode: str, items: list[Listing]) -> dict[str, Any]:
        now = _utc_now()
        now_iso = now.isoformat()
        retention_days = max(1, int(os.getenv("LISTING_RETENTION_DAYS", "7")))
        cutoff = (now - timedelta(days=retention_days)).isoformat()

        with self._connect() as connection:
            self._upsert_items(connection, mode, items, now_iso)
            cities = sorted({item.city for item in items}) or ["Ho Chi Minh City"]
            for city in cities:
                connection.execute(
                    "DELETE FROM listing_catalog WHERE transaction_mode = ? AND city = ? AND last_seen_at < ?",
                    (mode, city, cutoff),
                )
            connection.execute(
                """
                INSERT INTO listing_refresh(
                    transaction_mode, last_attempt_at, last_success_at,
                    returned_count, last_error
                ) VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(transaction_mode) DO UPDATE SET
                    last_attempt_at = excluded.last_attempt_at,
                    last_success_at = excluded.last_success_at,
                    returned_count = excluded.returned_count,
                    last_error = NULL
                """,
                (mode, now_iso, now_iso, len(items)),
            )
        return self.status(mode, items[0].city if items else "Ho Chi Minh City")

    def mark_failure(self, mode: str, error: str) -> dict[str, Any]:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO listing_refresh(transaction_mode, last_attempt_at, last_error)
                VALUES (?, ?, ?)
                ON CONFLICT(transaction_mode) DO UPDATE SET
                    last_attempt_at = excluded.last_attempt_at,
                    last_error = excluded.last_error
                """,
                (mode, _utc_now().isoformat(), error[:500]),
            )
        return self.status(mode)

    def status(self, mode: str, city: str = "Ho Chi Minh City") -> dict[str, Any]:
        with self._connect() as connection:
            refresh = connection.execute(
                "SELECT * FROM listing_refresh WHERE transaction_mode = ?",
                (mode,),
            ).fetchone()
            count = connection.execute(
                "SELECT COUNT(*) AS total FROM listing_catalog WHERE transaction_mode = ? AND city = ?",
                (mode, city),
            ).fetchone()["total"]

        refresh_hours = max(1, int(os.getenv("LISTING_REFRESH_HOURS", "168")))
        last_attempt = _parse_datetime(refresh["last_attempt_at"] if refresh else None)
        last_success = _parse_datetime(refresh["last_success_at"] if refresh else None)
        # Automatic provider calls are rate-limited by the most recent attempt,
        # whether it succeeded or failed. This prevents an hourly scheduler
        # check from repeatedly spending Gemini quota after a transient error.
        refresh_anchor = max(
            (value for value in (last_attempt, last_success) if value is not None),
            default=None,
        )
        next_refresh = refresh_anchor + timedelta(hours=refresh_hours) if refresh_anchor else None
        return {
            "transaction_mode": mode,
            "city": city,
            "count": count,
            "last_attempt_at": refresh["last_attempt_at"] if refresh else None,
            "last_success_at": refresh["last_success_at"] if refresh else None,
            "last_returned_count": refresh["returned_count"] if refresh else 0,
            "last_error": refresh["last_error"] if refresh else None,
            "next_refresh_at": next_refresh.isoformat() if next_refresh else None,
            "due": next_refresh is None or _utc_now() >= next_refresh,
        }

    def all_items(self, limit: int = 200) -> list[Listing]:
        items: list[Listing] = []
        for city in ("Ho Chi Minh City", "Bangkok", "Kuala Lumpur"):
            for mode in ("BUY", "RENT"):
                items.extend(self.list(mode, limit, city))
        return items

    def save_profile(self, profile: DecisionProfile) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO decision_profiles(profile_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (profile.profile_id, profile.model_dump_json(), _utc_now().isoformat()),
            )
        persist_document("profiles", profile.profile_id, profile.model_dump(mode="json"))

    def save_session(self, session: Session) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions(id, profile_id, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    profile_id = excluded.profile_id,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (session.id, session.profile_id, session.model_dump_json(), _utc_now().isoformat()),
            )
        persist_document("sessions", session.id, session.model_dump(mode="json"))

    def get_session(self, session_id: str) -> Session | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
        if row:
            return Session.model_validate_json(row["payload_json"])
        payload = get_document("sessions", session_id)
        if not payload:
            return None
        session = Session.model_validate(payload)
        self.save_session(session)
        return session

    def get_profile(self, profile_id: str) -> DecisionProfile | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM decision_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        if not row:
            payload = get_document("profiles", profile_id)
            if not payload:
                return None
            try:
                profile = DecisionProfile.model_validate(payload)
                self.save_profile(profile)
                return profile
            except Exception:
                return None
        try:
            return DecisionProfile.model_validate_json(row["payload_json"])
        except Exception:
            return None

    def save_revision(self, profile_id: str, revision: dict[str, Any]) -> None:
        revision_id = f"{profile_id}-{int(_utc_now().timestamp() * 1_000_000)}"
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO profile_revisions(profile_id, payload_json, created_at) VALUES (?, ?, ?)",
                (profile_id, json.dumps(revision), _utc_now().isoformat()),
            )
        persist_document("profile_revisions", revision_id, {"id": revision_id, "profile_id": profile_id, **revision})

    def list_revisions(self, profile_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM profile_revisions WHERE profile_id = ? ORDER BY id ASC",
                (profile_id,),
            ).fetchall()
        audit = [json.loads(row["payload_json"]) for row in rows] if rows else [
            {key: value for key, value in payload.items() if key not in {"id", "profile_id"}}
            for payload in query_documents("profile_revisions", "profile_id", profile_id)
        ]
        active: list[dict[str, Any]] = []
        for revision in audit:
            if revision.get("decision") == "UNDO":
                if active:
                    active.pop()
            else:
                active.append(revision)
        return active

    def delete_latest_revision(self, profile_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM profile_revisions WHERE id = (SELECT id FROM profile_revisions WHERE profile_id = ? ORDER BY id DESC LIMIT 1)",
                (profile_id,),
            )

    def save_proposal(self, profile_id: str, proposal: PreferenceProposal) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO preference_proposals(id, profile_id, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (proposal.id, profile_id, proposal.model_dump_json(), _utc_now().isoformat()),
            )
        persist_document("preference_proposals", proposal.id, {"profile_id": profile_id, **proposal.model_dump(mode="json")})

    def get_proposal(self, proposal_id: str) -> tuple[str, PreferenceProposal] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT profile_id, payload_json FROM preference_proposals WHERE id = ?",
                (proposal_id,),
            ).fetchone()
        if not row:
            payload = get_document("preference_proposals", proposal_id)
            if not payload:
                return None
            profile_id = str(payload.pop("profile_id"))
            proposal = PreferenceProposal.model_validate(payload)
            self.save_proposal(profile_id, proposal)
            return profile_id, proposal
        return row["profile_id"], PreferenceProposal.model_validate_json(row["payload_json"])

    def save_item(self, profile_id: str, listing_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO saved_items(profile_id, listing_id, created_at) VALUES (?, ?, ?)",
                (profile_id, listing_id, _utc_now().isoformat()),
            )
        persist_document("saved_items", f"{profile_id}:{listing_id}", {"profile_id": profile_id, "listing_id": listing_id, "created_at": _utc_now().isoformat()})

    def list_saved_items(self, profile_id: str) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT listing_id FROM saved_items WHERE profile_id = ? ORDER BY created_at",
                (profile_id,),
            ).fetchall()
        if rows:
            return {row["listing_id"] for row in rows}
        return {str(payload["listing_id"]) for payload in query_documents("saved_items", "profile_id", profile_id)}

    def save_agent_run(self, run: AgentRun) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs(id, profile_id, idempotency_key, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (run.id, run.profile_id, run.idempotency_key, run.model_dump_json(), _utc_now().isoformat()),
            )
        persist_document("agent_runs", run.id, run.model_dump(mode="json"))

    def insert_agent_run_if_absent(self, run: AgentRun) -> AgentRun:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs(id, profile_id, idempotency_key, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (run.id, run.profile_id, run.idempotency_key, run.model_dump_json(), _utc_now().isoformat()),
            )
            row = connection.execute(
                "SELECT payload_json FROM agent_runs WHERE idempotency_key = ?",
                (run.idempotency_key,),
            ).fetchone()
        selected = AgentRun.model_validate_json(row["payload_json"])
        if selected.id == run.id:
            persist_document("agent_runs", run.id, run.model_dump(mode="json"))
        return selected

    def get_agent_run(self, run_id: str) -> AgentRun | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload_json FROM agent_runs WHERE id = ?", (run_id,)).fetchone()
        if row:
            return AgentRun.model_validate_json(row["payload_json"])
        payload = get_document("agent_runs", run_id)
        return AgentRun.model_validate(payload) if payload else None

    def get_agent_run_by_key(self, idempotency_key: str) -> AgentRun | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM agent_runs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row:
            return AgentRun.model_validate_json(row["payload_json"])
        matches = query_documents("agent_runs", "idempotency_key", idempotency_key)
        return AgentRun.model_validate(matches[0]) if matches else None

    def save_agent_event(self, event: AgentEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_events(id, run_id, sequence, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO NOTHING
                """,
                (event.id, event.run_id, event.sequence, event.model_dump_json(), event.created_at),
            )
        persist_document("agent_events", event.id, event.model_dump(mode="json"))

    def list_agent_events(self, run_id: str) -> list[AgentEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM agent_events WHERE run_id = ? ORDER BY sequence",
                (run_id,),
            ).fetchall()
        if rows:
            return [AgentEvent.model_validate_json(row["payload_json"]) for row in rows]
        return sorted(
            [AgentEvent.model_validate(payload) for payload in query_documents("agent_events", "run_id", run_id)],
            key=lambda event: event.sequence,
        )

    def save_decision_brief(self, brief: DecisionBrief) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO decision_briefs(run_id, profile_id, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (brief.run_id, brief.profile_id, brief.model_dump_json(), _utc_now().isoformat()),
            )
        persist_document("decision_briefs", brief.run_id, brief.model_dump(mode="json"))

    def get_decision_brief(self, run_id: str) -> DecisionBrief | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM decision_briefs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row:
            return DecisionBrief.model_validate_json(row["payload_json"])
        payload = get_document("decision_briefs", run_id)
        return DecisionBrief.model_validate(payload) if payload else None

    def list_decision_briefs(self, profile_id: str) -> list[DecisionBrief]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM decision_briefs WHERE profile_id = ? ORDER BY updated_at DESC",
                (profile_id,),
            ).fetchall()
        if rows:
            return [DecisionBrief.model_validate_json(row["payload_json"]) for row in rows]
        return sorted(
            [DecisionBrief.model_validate(payload) for payload in query_documents("decision_briefs", "profile_id", profile_id)],
            key=lambda brief: brief.updated_at,
            reverse=True,
        )

    def save_evaluation_report(self, report: EvaluationReport) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO evaluation_reports(id, passed, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    passed = excluded.passed,
                    payload_json = excluded.payload_json,
                    created_at = excluded.created_at
                """,
                (report.id, int(report.passed), report.model_dump_json(), report.created_at),
            )
        persist_document("evaluation_reports", report.id, report.model_dump(mode="json"))
        persist_document("evaluation_meta", "latest", report.model_dump(mode="json"))
        if report.passed:
            persist_document("evaluation_meta", "latest_passed", report.model_dump(mode="json"))

    def latest_evaluation_report(self, *, passed_only: bool = False) -> EvaluationReport | None:
        clause = "WHERE passed = 1" if passed_only else ""
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT payload_json FROM evaluation_reports {clause} ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row:
            return EvaluationReport.model_validate_json(row["payload_json"])
        payload = get_document("evaluation_meta", "latest_passed" if passed_only else "latest")
        return EvaluationReport.model_validate(payload) if payload else None

    def get_evaluation_report(self, report_id: str) -> EvaluationReport | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM evaluation_reports WHERE id = ?", (report_id,)
            ).fetchone()
        if row:
            return EvaluationReport.model_validate_json(row["payload_json"])
        payload = get_document("evaluation_reports", report_id)
        return EvaluationReport.model_validate(payload) if payload else None

    def save_prompt_revision_candidate(self, candidate: PromptRevisionCandidate) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO prompt_revision_candidates(id, status, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (candidate.id, candidate.status, candidate.model_dump_json(), _utc_now().isoformat()),
            )
        persist_document("prompt_revision_candidates", candidate.id, candidate.model_dump(mode="json"))

    def get_prompt_revision_candidate(self, candidate_id: str) -> PromptRevisionCandidate | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM prompt_revision_candidates WHERE id = ?", (candidate_id,)
            ).fetchone()
        if row:
            return PromptRevisionCandidate.model_validate_json(row["payload_json"])
        payload = get_document("prompt_revision_candidates", candidate_id)
        return PromptRevisionCandidate.model_validate(payload) if payload else None

    def save_semantic_memory(self, item: SemanticMemoryItem) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO semantic_memory(id, profile_id, preference_key, embedding_status, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    preference_key = excluded.preference_key,
                    embedding_status = excluded.embedding_status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    item.id,
                    item.profile_id,
                    item.preference_key,
                    item.embedding_status,
                    item.model_dump_json(),
                    _utc_now().isoformat(),
                ),
            )
        persist_semantic_memory(item.id, item.model_dump(mode="json"))

    def get_semantic_memory(self, memory_id: str) -> SemanticMemoryItem | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM semantic_memory WHERE id = ?",
                (memory_id,),
            ).fetchone()
        if row:
            return SemanticMemoryItem.model_validate_json(row["payload_json"])
        payload = get_document("semantic_memory", memory_id)
        return SemanticMemoryItem.model_validate(_normalize_memory_payload(payload)) if payload else None

    def list_semantic_memory(self, profile_id: str) -> list[SemanticMemoryItem]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM semantic_memory WHERE profile_id = ? ORDER BY updated_at DESC",
                (profile_id,),
            ).fetchall()
        if rows:
            return [SemanticMemoryItem.model_validate_json(row["payload_json"]) for row in rows]
        return [
            SemanticMemoryItem.model_validate(_normalize_memory_payload(payload))
            for payload in query_documents("semantic_memory", "profile_id", profile_id)
        ]

    def vector_search_semantic_memory(
        self,
        profile_id: str,
        query_vector: list[float],
        limit: int = 20,
    ) -> list[tuple[SemanticMemoryItem, float | None]]:
        if firestore_primary():
            return [
                (
                    SemanticMemoryItem.model_validate(
                        _normalize_memory_payload(
                            {key: value for key, value in payload.items() if key != "cosine_distance"}
                        )
                    ),
                    float(payload["cosine_distance"]) if payload.get("cosine_distance") is not None else None,
                )
                for payload in query_semantic_memory(profile_id, query_vector, limit)
            ]
        return [(item, None) for item in self.list_semantic_memory(profile_id)]

    def save_decision_watch(self, watch: DecisionWatch) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO decision_watches(
                    id, idempotency_key, profile_id, status, next_run_at,
                    payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    next_run_at = excluded.next_run_at,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    watch.id,
                    watch.idempotency_key,
                    watch.profile_id,
                    watch.status,
                    watch.next_run_at,
                    watch.model_dump_json(),
                    watch.updated_at,
                ),
            )
        persist_document("decision_watches", watch.id, watch.model_dump(mode="json"))

    def insert_decision_watch_if_absent(self, watch: DecisionWatch) -> DecisionWatch:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO decision_watches(
                    id, idempotency_key, profile_id, status, next_run_at,
                    payload_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idempotency_key) DO NOTHING
                """,
                (
                    watch.id,
                    watch.idempotency_key,
                    watch.profile_id,
                    watch.status,
                    watch.next_run_at,
                    watch.model_dump_json(),
                    watch.updated_at,
                ),
            )
            row = connection.execute(
                "SELECT payload_json FROM decision_watches WHERE idempotency_key = ?",
                (watch.idempotency_key,),
            ).fetchone()
        selected = DecisionWatch.model_validate_json(row["payload_json"])
        if selected.id == watch.id:
            persist_document("decision_watches", watch.id, watch.model_dump(mode="json"))
        return selected

    def get_decision_watch(self, watch_id: str) -> DecisionWatch | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM decision_watches WHERE id = ?", (watch_id,)
            ).fetchone()
        if row:
            return DecisionWatch.model_validate_json(row["payload_json"])
        payload = get_document("decision_watches", watch_id)
        if not payload:
            return None
        watch = DecisionWatch.model_validate(payload)
        self.save_decision_watch(watch)
        return watch

    def get_decision_watch_by_key(self, idempotency_key: str) -> DecisionWatch | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM decision_watches WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
        if row:
            return DecisionWatch.model_validate_json(row["payload_json"])
        matches = query_documents("decision_watches", "idempotency_key", idempotency_key)
        return DecisionWatch.model_validate(matches[0]) if matches else None

    def list_decision_watches(self, profile_id: str) -> list[DecisionWatch]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM decision_watches WHERE profile_id = ? ORDER BY updated_at DESC",
                (profile_id,),
            ).fetchall()
        if rows:
            return [DecisionWatch.model_validate_json(row["payload_json"]) for row in rows]
        return sorted(
            [DecisionWatch.model_validate(payload) for payload in query_documents("decision_watches", "profile_id", profile_id)],
            key=lambda watch: watch.updated_at,
            reverse=True,
        )

    def list_due_decision_watches(self, limit: int = 5) -> list[DecisionWatch]:
        now = _utc_now()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payload_json FROM decision_watches
                WHERE status = 'ACTIVE' AND next_run_at IS NOT NULL AND next_run_at <= ?
                ORDER BY next_run_at ASC LIMIT ?
                """,
                (now.isoformat(), limit),
            ).fetchall()
        watches = [DecisionWatch.model_validate_json(row["payload_json"]) for row in rows]
        if not watches and firestore_primary():
            cloud_watches = [
                DecisionWatch.model_validate(payload)
                for payload in query_documents("decision_watches", "status", "ACTIVE")
            ]
            watches = sorted(
                [
                    watch
                    for watch in cloud_watches
                    if (parsed := _parse_datetime(watch.next_run_at)) is not None and parsed <= now
                ],
                key=lambda watch: watch.next_run_at or "",
            )[:limit]
        return watches

    def save_evidence_revision(self, revision: EvidenceRevision) -> EvidenceRevision:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO evidence_revisions(
                    id, watch_id, listing_id, tool, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    revision.id,
                    revision.watch_id,
                    revision.listing_id,
                    revision.tool,
                    revision.model_dump_json(),
                    revision.created_at,
                ),
            )
            row = connection.execute(
                "SELECT payload_json FROM evidence_revisions WHERE id = ?", (revision.id,)
            ).fetchone()
        selected = EvidenceRevision.model_validate_json(row["payload_json"])
        if selected == revision:
            persist_document("evidence_revisions", revision.id, revision.model_dump(mode="json"))
        return selected

    def list_evidence_revisions(self, watch_id: str) -> list[EvidenceRevision]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM evidence_revisions WHERE watch_id = ? ORDER BY created_at ASC",
                (watch_id,),
            ).fetchall()
        if rows:
            return [EvidenceRevision.model_validate_json(row["payload_json"]) for row in rows]
        return sorted(
            [EvidenceRevision.model_validate(payload) for payload in query_documents("evidence_revisions", "watch_id", watch_id)],
            key=lambda revision: revision.created_at,
        )

    def save_decision_watch_event(self, event: DecisionWatchEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO decision_watch_events(
                    id, watch_id, sequence, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (event.id, event.watch_id, event.sequence, event.model_dump_json(), event.created_at),
            )
        persist_document("decision_watch_events", event.id, event.model_dump(mode="json"))

    def list_decision_watch_events(self, watch_id: str) -> list[DecisionWatchEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json FROM decision_watch_events WHERE watch_id = ? ORDER BY sequence ASC",
                (watch_id,),
            ).fetchall()
        if rows:
            return [DecisionWatchEvent.model_validate_json(row["payload_json"]) for row in rows]
        return sorted(
            [DecisionWatchEvent.model_validate(payload) for payload in query_documents("decision_watch_events", "watch_id", watch_id)],
            key=lambda event: event.sequence,
        )
