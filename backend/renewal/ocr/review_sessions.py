"""V11 privacy-safe OCR review sessions.

The V10 OCR field extractor is deliberately stateless. This module adds a
durable review workflow around those extraction results without saving raw OCR
text or uploaded image bytes. Stored session records contain page hashes,
redacted snippets, normalized field candidates, reviewer decisions, and an audit
trail suitable for later compliance review.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from .fields import (
    FieldCandidate,
    OCRFieldError,
    build_review_packet,
    extract_ocr_fields,
    field_specs,
    mortgage_draft,
    normalize_correction,
    review_status,
    summarize_review_decision,
)

_LOCK = RLock()

MAX_ALIAS_LENGTH = 120
MAX_ACTOR_LENGTH = 120
MAX_NOTE_LENGTH = 1000
MAX_DECISIONS = 30
MIN_EXPIRES_DAYS = 1
MAX_EXPIRES_DAYS = 180
DEFAULT_EXPIRES_DAYS = 45

DECISION_VALUES = frozenset({"approved", "needs_followup", "rejected"})
FINAL_STATUSES = frozenset({"ready_for_prefill", "completed"})
SAFE_EXPORT_KEYS = (
    "provider",
    "filename",
    "pages",
    "fields",
    "alternatives",
    "mortgage_draft",
    "missing_required",
    "review_packet",
    "review_status",
    "manual_corrections",
    "metrics",
    "warnings",
    "preview",
    "notice",
    "review_summary",
)


class OCRReviewSessionError(ValueError):
    """Base class for controlled OCR review-session failures."""


class OCRReviewAccessDenied(OCRReviewSessionError):
    """The supplied review token is invalid or the session is no longer usable."""


class OCRReviewConflict(OCRReviewSessionError):
    """The requested state transition would create an unsafe review outcome."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise OCRReviewSessionError("Expected an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json_loads(value: str | bytes | None, default: Any) -> Any:
    if value in (None, ""):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise OCRReviewSessionError("Stored OCR review payload is not valid JSON") from exc


def _bounded_text(value: Any, *, field: str, limit: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise OCRReviewSessionError(f"{field} is required")
    if len(text) > limit:
        raise OCRReviewSessionError(f"{field} must be at most {limit} characters")
    return text


def _expires_at(days: int | None) -> str:
    if days is None:
        days = DEFAULT_EXPIRES_DAYS
    try:
        parsed = int(days)
    except (TypeError, ValueError) as exc:
        raise OCRReviewSessionError("expires_days must be a whole number") from exc
    if not MIN_EXPIRES_DAYS <= parsed <= MAX_EXPIRES_DAYS:
        raise OCRReviewSessionError(
            f"expires_days must be between {MIN_EXPIRES_DAYS} and {MAX_EXPIRES_DAYS}"
        )
    return _iso(_now() + timedelta(days=parsed))


def _page_digest(extraction: dict) -> str:
    pages = extraction.get("pages", [])
    material = [
        {
            "page_number": page.get("page_number"),
            "text_sha256": page.get("text_sha256"),
            "text_length": page.get("text_length"),
        }
        for page in pages
    ]
    return _digest(_json_dumps(material))


def _safe_extraction(extraction: dict) -> dict:
    """Keep only sanitized V10 extraction members before persistence/export."""
    safe = {key: extraction[key] for key in SAFE_EXPORT_KEYS if key in extraction}
    safe.setdefault("manual_corrections", [])
    safe.setdefault("warnings", [])
    safe["review_summary"] = summarize_review_decision(safe)
    return safe


def _candidate_from_public(key: str, payload: dict) -> FieldCandidate:
    if key not in field_specs():
        raise OCRReviewSessionError(f"Unknown stored OCR field: {key}")
    return FieldCandidate(
        key=key,
        label=str(payload.get("label") or field_specs()[key].label),
        value=payload.get("value"),
        display_value=str(payload.get("display_value") or payload.get("value") or ""),
        page=int(payload.get("page") or 0),
        excerpt=str(payload.get("excerpt") or ""),
        confidence=str(payload.get("confidence") or "low"),
        confidence_score=float(payload.get("confidence_score") or 0.0),
        source=str(payload.get("source") or "ocr_text"),
        pattern=str(payload.get("pattern") or "stored_candidate"),
        warnings=tuple(payload.get("warnings") or ()),
    )


def _fields_from_public(fields: dict[str, dict]) -> dict[str, FieldCandidate]:
    output: dict[str, FieldCandidate] = {}
    for key, payload in (fields or {}).items():
        if not isinstance(payload, dict):
            raise OCRReviewSessionError(f"Stored OCR field {key} is malformed")
        output[key] = _candidate_from_public(key, payload)
    return output


def _public_fields(fields: dict[str, FieldCandidate]) -> dict[str, dict]:
    return {key: candidate.public() for key, candidate in sorted(fields.items())}


def _rebuild_extraction(extraction: dict, fields: dict[str, FieldCandidate]) -> dict:
    refreshed = dict(extraction)
    packet = build_review_packet(fields, {key: [candidate] for key, candidate in fields.items()})
    refreshed["fields"] = _public_fields(fields)
    refreshed["review_packet"] = packet
    refreshed["review_status"] = review_status(packet)
    refreshed["missing_required"] = [
        item["field"] for item in packet if item.get("status") == "missing_required"
    ]
    refreshed["mortgage_draft"] = mortgage_draft(fields)
    refreshed["review_summary"] = summarize_review_decision(refreshed)
    refreshed["warnings"] = list(dict.fromkeys(refreshed.get("warnings", [])))
    return _safe_extraction(refreshed)


def _decision_map(decisions: list[dict]) -> dict[str, str]:
    return {item["field"]: item["decision"] for item in decisions}


def _required_field_keys() -> list[str]:
    return [key for key, spec in field_specs().items() if spec.required]


def _session_status(extraction: dict, decisions: list[dict]) -> str:
    fields = extraction.get("fields", {})
    decision_by_field = _decision_map(decisions)
    required = _required_field_keys()
    missing = [key for key in required if key not in fields]
    if missing:
        return "blocked"
    if any(item.get("decision") == "rejected" for item in decisions):
        return "needs_rework"
    if extraction.get("review_status") == "blocked":
        return "blocked"
    unapproved_required = [key for key in required if decision_by_field.get(key) != "approved"]
    if unapproved_required:
        return "review_required"
    unresolved = [
        item["field"]
        for item in extraction.get("review_packet", [])
        if item.get("status") == "needs_review"
        and decision_by_field.get(item.get("field")) != "approved"
        and item.get("field") in required
    ]
    if unresolved:
        return "review_required"
    return "ready_for_prefill"


def _gate(name: str, passed: bool, *, blocking: bool, detail: str) -> dict:
    return {
        "gate": name,
        "passed": bool(passed),
        "blocking": bool(blocking and not passed),
        "detail": detail,
    }


def quality_gates(extraction: dict, decisions: list[dict]) -> list[dict]:
    fields = extraction.get("fields", {})
    decision_by_field = _decision_map(decisions)
    required = _required_field_keys()
    missing_required = [key for key in required if key not in fields]
    unapproved_required = [key for key in required if decision_by_field.get(key) != "approved"]
    rejected = [item["field"] for item in decisions if item.get("decision") == "rejected"]
    blocking_packet = [item["field"] for item in extraction.get("review_packet", []) if item.get("blocking")]
    pages_without_hash = [
        str(page.get("page_number", "?"))
        for page in extraction.get("pages", [])
        if not page.get("text_sha256")
    ]
    manual_or_decision = bool(extraction.get("manual_corrections") or decisions)
    return [
        _gate(
            "required_fields_present",
            not missing_required,
            blocking=True,
            detail="All required mortgage fields are present"
            if not missing_required
            else "Missing: " + ", ".join(missing_required),
        ),
        _gate(
            "required_fields_approved",
            not unapproved_required,
            blocking=True,
            detail="All required fields have reviewer approval"
            if not unapproved_required
            else "Awaiting approval: " + ", ".join(unapproved_required),
        ),
        _gate(
            "no_rejected_fields",
            not rejected,
            blocking=True,
            detail="No reviewer rejected fields"
            if not rejected
            else "Rejected: " + ", ".join(rejected),
        ),
        _gate(
            "no_blocking_ocr_items",
            not blocking_packet,
            blocking=True,
            detail="The OCR packet has no blocking items"
            if not blocking_packet
            else "Blocking OCR fields: " + ", ".join(blocking_packet),
        ),
        _gate(
            "page_hashes_recorded",
            not pages_without_hash and bool(extraction.get("pages")),
            blocking=True,
            detail="Every OCR page has a source hash"
            if not pages_without_hash
            else "Pages without hashes: " + ", ".join(pages_without_hash),
        ),
        _gate(
            "human_review_recorded",
            manual_or_decision,
            blocking=False,
            detail="At least one correction or field decision is recorded"
            if manual_or_decision
            else "No reviewer action has been recorded yet",
        ),
    ]


def blocking_gates(gates: list[dict]) -> list[dict]:
    return [gate for gate in gates if gate.get("blocking")]


def review_actions(extraction: dict, decisions: list[dict]) -> list[dict]:
    actions = []
    decision_by_field = _decision_map(decisions)
    for item in extraction.get("review_packet", []):
        field = item.get("field")
        if decision_by_field.get(field) == "approved":
            continue
        if item.get("status") == "missing_required":
            actions.append(
                {
                    "field": field,
                    "priority": "high",
                    "action": "collect_required_value",
                    "prompt": item.get("prompt"),
                }
            )
        elif item.get("status") == "needs_review":
            actions.append(
                {
                    "field": field,
                    "priority": "medium" if not item.get("blocking") else "high",
                    "action": "verify_ocr_candidate",
                    "prompt": item.get("prompt"),
                }
            )
    for decision in decisions:
        if decision.get("decision") == "rejected":
            actions.append(
                {
                    "field": decision["field"],
                    "priority": "high",
                    "action": "replace_rejected_value",
                    "prompt": "Enter a corrected value or rerun OCR from a clearer source.",
                }
            )
    return actions


def export_digest(events: list[dict]) -> str:
    material = [
        {
            "action": event.get("action"),
            "actor": event.get("actor"),
            "created_at": event.get("created_at"),
            "detail": event.get("detail"),
        }
        for event in events
    ]
    return _digest(_json_dumps(material))


class OCRReviewSessionStore:
    """SQLite-backed review sessions for sanitized OCR extraction output."""

    def __init__(self, filename: str | Path):
        self.filename = str(filename)
        path = Path(self.filename)
        if path.parent:
            path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS ocr_review_sessions (
                    id TEXT PRIMARY KEY,
                    token_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    borrower_alias TEXT,
                    source TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    pages_digest TEXT NOT NULL,
                    extraction_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    finalized_at TEXT
                );
                CREATE INDEX IF NOT EXISTS ocr_review_status_idx
                    ON ocr_review_sessions(status, updated_at);

                CREATE TABLE IF NOT EXISTS ocr_review_decisions (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    field_key TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    source_value TEXT,
                    decided_at TEXT NOT NULL,
                    UNIQUE(session_id, field_key),
                    FOREIGN KEY(session_id) REFERENCES ocr_review_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS ocr_review_decision_session_idx
                    ON ocr_review_decisions(session_id, decided_at);

                CREATE TABLE IF NOT EXISTS ocr_review_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES ocr_review_sessions(id)
                );
                CREATE INDEX IF NOT EXISTS ocr_review_event_session_idx
                    ON ocr_review_events(session_id, created_at);
                """
            )

    def _db(self):
        db = sqlite3.connect(self.filename, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        return db

    def _audit(self, db: sqlite3.Connection, session_id: str, actor: str,
               action: str, detail: dict) -> None:
        db.execute(
            "INSERT INTO ocr_review_events VALUES (?,?,?,?,?,?)",
            (str(uuid.uuid4()), session_id, actor, action, _json_dumps(detail), _iso()),
        )

    def _row(self, db: sqlite3.Connection, session_id: str) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM ocr_review_sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise OCRReviewAccessDenied("Review session not found")
        return row

    def _assert_access(self, db: sqlite3.Connection, session_id: str,
                       token: str | None) -> sqlite3.Row:
        row = self._row(db, session_id)
        supplied = _digest(token or "")
        if not hmac.compare_digest(row["token_digest"], supplied):
            raise OCRReviewAccessDenied("Invalid review session token")
        if _parse_datetime(row["expires_at"]) < _now() and row["status"] != "completed":
            raise OCRReviewAccessDenied("Review session has expired")
        return row

    def _load_extraction(self, row: sqlite3.Row) -> dict:
        return _safe_extraction(_json_loads(row["extraction_json"], {}))

    def _decisions_for(self, db: sqlite3.Connection, session_id: str) -> list[dict]:
        rows = db.execute(
            """
            SELECT field_key, decision, reason, actor, source_value, decided_at
            FROM ocr_review_decisions
            WHERE session_id=?
            ORDER BY decided_at, field_key
            """,
            (session_id,),
        ).fetchall()
        return [
            {
                "field": row["field_key"],
                "decision": row["decision"],
                "reason": row["reason"],
                "actor": row["actor"],
                "source_value": row["source_value"],
                "decided_at": row["decided_at"],
            }
            for row in rows
        ]

    def _events_for(self, db: sqlite3.Connection, session_id: str) -> list[dict]:
        rows = db.execute(
            """
            SELECT actor, action, detail_json, created_at
            FROM ocr_review_events
            WHERE session_id=?
            ORDER BY created_at, id
            """,
            (session_id,),
        ).fetchall()
        return [
            {
                "actor": row["actor"],
                "action": row["action"],
                "detail": _json_loads(row["detail_json"], {}),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _public_session(self, row: sqlite3.Row, decisions: list[dict],
                        *, include_extraction: bool = True) -> dict:
        extraction = self._load_extraction(row)
        gates = quality_gates(extraction, decisions)
        session = {
            "session_id": row["id"],
            "status": row["status"],
            "filename": row["filename"],
            "borrower_alias": row["borrower_alias"],
            "source": row["source"],
            "page_count": row["page_count"],
            "pages_digest": row["pages_digest"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"],
            "finalized_at": row["finalized_at"],
            "review_summary": summarize_review_decision(extraction),
            "quality_gates": gates,
            "blocking_gates": blocking_gates(gates),
            "review_actions": review_actions(extraction, decisions),
            "decisions": decisions,
            "raw_ocr_stored": False,
            "token_returned_after_create": False,
        }
        if include_extraction:
            session["extraction"] = extraction
        return session

    def _update_session(self, db: sqlite3.Connection, session_id: str,
                        extraction: dict, decisions: list[dict],
                        *, status: str | None = None,
                        finalized_at: str | None = None) -> str:
        next_status = status or _session_status(extraction, decisions)
        db.execute(
            """
            UPDATE ocr_review_sessions
            SET status=?, extraction_json=?, updated_at=?, finalized_at=COALESCE(?, finalized_at)
            WHERE id=?
            """,
            (next_status, _json_dumps(_safe_extraction(extraction)), _iso(), finalized_at, session_id),
        )
        return next_status

    def create_session(self, pages: list[Any], *, filename: str = "ocr.txt",
                       min_confidence: float = 0.0,
                       corrections: dict[str, Any] | None = None,
                       borrower_alias: str | None = None,
                       source: str = "uploaded_ocr_text",
                       actor: str = "system",
                       expires_days: int | None = None) -> dict:
        actor = _bounded_text(actor, field="actor", limit=MAX_ACTOR_LENGTH) or "system"
        source = _bounded_text(source, field="source", limit=80) or "uploaded_ocr_text"
        borrower_alias = _bounded_text(
            borrower_alias, field="borrower_alias", limit=MAX_ALIAS_LENGTH
        ) or None
        extraction = _safe_extraction(
            extract_ocr_fields(
                pages,
                filename=filename,
                corrections=corrections,
                min_confidence=min_confidence,
            )
        )
        session_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        created_at = _iso()
        expires_at = _expires_at(expires_days)
        status = _session_status(extraction, [])
        filename = _bounded_text(filename, field="filename", limit=120) or "ocr.txt"
        page_count = len(extraction.get("pages", []))
        pages_digest = _page_digest(extraction)
        with _LOCK, self._db() as db:
            db.execute(
                """
                INSERT INTO ocr_review_sessions
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    session_id,
                    _digest(token),
                    status,
                    filename,
                    borrower_alias,
                    source,
                    page_count,
                    pages_digest,
                    _json_dumps(extraction),
                    created_at,
                    created_at,
                    expires_at,
                    None,
                ),
            )
            self._audit(
                db,
                session_id,
                actor,
                "session_created",
                {
                    "filename": filename,
                    "page_count": page_count,
                    "review_status": extraction.get("review_status"),
                    "field_count": len(extraction.get("fields", {})),
                    "raw_ocr_stored": False,
                },
            )
            if corrections:
                self._audit(
                    db,
                    session_id,
                    actor,
                    "initial_corrections_applied",
                    {"fields": sorted(corrections.keys())},
                )
            row = self._row(db, session_id)
            public = self._public_session(row, self._decisions_for(db, session_id))
        public["access_token"] = token
        public["token_returned_after_create"] = True
        return public

    def get_session(self, session_id: str, token: str | None,
                    *, include_extraction: bool = True) -> dict:
        with self._db() as db:
            row = self._assert_access(db, session_id, token)
            decisions = self._decisions_for(db, session_id)
            return self._public_session(row, decisions, include_extraction=include_extraction)

    def apply_corrections(self, session_id: str, token: str | None,
                          corrections: dict[str, Any], *,
                          actor: str = "reviewer",
                          note: str = "") -> dict:
        if not isinstance(corrections, dict) or not corrections:
            raise OCRReviewSessionError("Corrections must be a non-empty object")
        if len(corrections) > 20:
            raise OCRReviewSessionError("Supply at most 20 corrections at a time")
        actor = _bounded_text(actor, field="actor", limit=MAX_ACTOR_LENGTH) or "reviewer"
        note = _bounded_text(note, field="note", limit=MAX_NOTE_LENGTH)
        specs = field_specs()
        with _LOCK, self._db() as db:
            row = self._assert_access(db, session_id, token)
            if row["status"] == "completed":
                raise OCRReviewConflict("Completed review sessions cannot be corrected")
            extraction = self._load_extraction(row)
            fields = _fields_from_public(extraction.get("fields", {}))
            audit_items = list(extraction.get("manual_corrections", []))
            changed: list[str] = []
            for key, raw_value in corrections.items():
                if key not in specs:
                    raise OCRFieldError(f"Unknown correction field: {key}")
                corrected = normalize_correction(specs[key], raw_value)
                previous = fields.get(key)
                if previous and previous.display_value == corrected.display_value:
                    corrected = replace(
                        corrected,
                        warnings=tuple(dict.fromkeys([*corrected.warnings, "same_as_existing_value"])),
                    )
                fields[key] = corrected
                changed.append(key)
                audit_items.append(
                    {
                        "field": key,
                        "previous": previous.display_value if previous else None,
                        "new": corrected.display_value,
                        "source": "manual_review",
                        "actor": actor,
                    }
                )
            extraction["manual_corrections"] = audit_items
            extraction = _rebuild_extraction(extraction, fields)
            decisions = self._decisions_for(db, session_id)
            status = self._update_session(db, session_id, extraction, decisions)
            self._audit(
                db,
                session_id,
                actor,
                "corrections_applied",
                {"fields": sorted(changed), "note": note, "status": status},
            )
            row = self._row(db, session_id)
            return self._public_session(row, decisions)

    def record_decisions(self, session_id: str, token: str | None,
                         decisions: list[dict], *,
                         actor: str = "reviewer",
                         note: str = "") -> dict:
        if not isinstance(decisions, list) or not decisions:
            raise OCRReviewSessionError("Decisions must be a non-empty list")
        if len(decisions) > MAX_DECISIONS:
            raise OCRReviewSessionError(f"Supply at most {MAX_DECISIONS} decisions")
        actor = _bounded_text(actor, field="actor", limit=MAX_ACTOR_LENGTH) or "reviewer"
        note = _bounded_text(note, field="note", limit=MAX_NOTE_LENGTH)
        specs = field_specs()
        with _LOCK, self._db() as db:
            row = self._assert_access(db, session_id, token)
            if row["status"] == "completed":
                raise OCRReviewConflict("Completed review sessions cannot be changed")
            extraction = self._load_extraction(row)
            fields = extraction.get("fields", {})
            changed = []
            now = _iso()
            for item in decisions:
                if not isinstance(item, dict):
                    raise OCRReviewSessionError("Each decision must be an object")
                field = str(item.get("field") or "").strip()
                decision = str(item.get("decision") or "").strip()
                reason = _bounded_text(
                    item.get("reason", ""), field="reason", limit=MAX_NOTE_LENGTH
                )
                if field not in specs:
                    raise OCRReviewSessionError(f"Unknown decision field: {field}")
                if decision not in DECISION_VALUES:
                    raise OCRReviewSessionError("Decision must be approved, needs_followup or rejected")
                if decision == "approved" and field not in fields:
                    raise OCRReviewConflict(f"Cannot approve missing field: {field}")
                if decision in {"needs_followup", "rejected"} and not reason:
                    raise OCRReviewSessionError(f"{decision} decisions require a reason")
                source_value = fields.get(field, {}).get("display_value")
                db.execute(
                    """
                    INSERT INTO ocr_review_decisions
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(session_id, field_key) DO UPDATE SET
                        decision=excluded.decision,
                        reason=excluded.reason,
                        actor=excluded.actor,
                        source_value=excluded.source_value,
                        decided_at=excluded.decided_at
                    """,
                    (
                        str(uuid.uuid4()),
                        session_id,
                        field,
                        decision,
                        reason,
                        actor,
                        source_value,
                        now,
                    ),
                )
                changed.append({"field": field, "decision": decision})
            updated_decisions = self._decisions_for(db, session_id)
            status = self._update_session(db, session_id, extraction, updated_decisions)
            self._audit(
                db,
                session_id,
                actor,
                "field_decisions_recorded",
                {"decisions": changed, "note": note, "status": status},
            )
            row = self._row(db, session_id)
            return self._public_session(row, updated_decisions)

    def finalize_session(self, session_id: str, token: str | None,
                         *, actor: str = "reviewer", note: str = "") -> dict:
        actor = _bounded_text(actor, field="actor", limit=MAX_ACTOR_LENGTH) or "reviewer"
        note = _bounded_text(note, field="note", limit=MAX_NOTE_LENGTH)
        with _LOCK, self._db() as db:
            row = self._assert_access(db, session_id, token)
            if row["status"] == "completed":
                return self._public_session(row, self._decisions_for(db, session_id))
            extraction = self._load_extraction(row)
            decisions = self._decisions_for(db, session_id)
            gates = quality_gates(extraction, decisions)
            blockers = blocking_gates(gates)
            if blockers:
                names = ", ".join(gate["gate"] for gate in blockers)
                raise OCRReviewConflict(f"Review cannot be finalized; blocking gates: {names}")
            finalized_at = _iso()
            self._update_session(
                db,
                session_id,
                extraction,
                decisions,
                status="completed",
                finalized_at=finalized_at,
            )
            self._audit(
                db,
                session_id,
                actor,
                "session_finalized",
                {"note": note, "finalized_at": finalized_at},
            )
            row = self._row(db, session_id)
            return self._public_session(row, decisions)

    def audit_events(self, session_id: str, token: str | None) -> dict:
        with self._db() as db:
            self._assert_access(db, session_id, token)
            events = self._events_for(db, session_id)
            return {
                "session_id": session_id,
                "events": events,
                "event_count": len(events),
                "audit_digest": export_digest(events),
            }

    def export_packet(self, session_id: str, token: str | None) -> dict:
        with self._db() as db:
            row = self._assert_access(db, session_id, token)
            decisions = self._decisions_for(db, session_id)
            events = self._events_for(db, session_id)
            extraction = self._load_extraction(row)
            gates = quality_gates(extraction, decisions)
            return {
                "exported_at": _iso(),
                "session": self._public_session(row, decisions, include_extraction=False),
                "extraction": extraction,
                "decisions": decisions,
                "quality_gates": gates,
                "blocking_gates": blocking_gates(gates),
                "audit_event_count": len(events),
                "audit_digest": export_digest(events),
                "raw_ocr_stored": False,
                "contains_borrower_secret": False,
            }
