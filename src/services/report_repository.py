"""Persistence for approved and closed incident outcomes."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from src.models.api import ReviewAuditEntry, StoredReport
from src.models.incidents import Claim, DraftReport


class ReportRepositoryError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReportRepository(Protocol):
    def store(self, report: StoredReport) -> StoredReport: ...

    def get(self, incident_id: str) -> StoredReport | None: ...


class InMemoryReportRepository:
    def __init__(self) -> None:
        self._reports: dict[str, StoredReport] = {}

    def store(self, report: StoredReport) -> StoredReport:
        if report.incident_id in self._reports:
            raise ReportRepositoryError("REPORT_ALREADY_STORED", "terminal outcome is already stored")
        stored = report.model_copy(update={"stored_at": report.stored_at or datetime.now(UTC)})
        self._reports[report.incident_id] = stored
        return stored

    def get(self, incident_id: str) -> StoredReport | None:
        return self._reports.get(incident_id)


class SQLiteReportRepository:
    def __init__(self, database_path: str) -> None:
        if not database_path.strip():
            raise ValueError("database_path must not be blank")
        self._database_path = Path(database_path).resolve()
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def store(self, report: StoredReport) -> StoredReport:
        stored = report.model_copy(update={"stored_at": report.stored_at or datetime.now(UTC)})
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO incident_reports (
                        incident_id, status, final_report_json, evidence_json,
                        reviewer, decision, reason, stored_at, has_log,
                        artifact_json, claims_json, warnings_json, audit_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stored.incident_id,
                        stored.status,
                        stored.final_report.model_dump_json() if stored.final_report else None,
                        _json_list(stored.evidence_ids),
                        stored.reviewer,
                        stored.decision,
                        stored.reason,
                        stored.stored_at.isoformat() if stored.stored_at else None,
                        int(stored.has_log),
                        json.dumps(stored.artifact_uris, separators=(",", ":")),
                        json.dumps([claim.model_dump(mode="json") for claim in stored.claims], separators=(",", ":")),
                        json.dumps(stored.warnings, separators=(",", ":")),
                        json.dumps(
                            [entry.model_dump(mode="json") for entry in stored.review_audit], separators=(",", ":")
                        ),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ReportRepositoryError("REPORT_ALREADY_STORED", "terminal outcome is already stored") from exc
        except sqlite3.Error as exc:
            raise ReportRepositoryError("REPORT_STORAGE_FAILED", "could not store terminal outcome") from exc
        return stored

    def get(self, incident_id: str) -> StoredReport | None:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    """
                    SELECT incident_id, status, final_report_json, evidence_json,
                           reviewer, decision, reason, stored_at, has_log,
                           artifact_json, claims_json, warnings_json, audit_json
                    FROM incident_reports WHERE incident_id = ?
                    """,
                    (incident_id,),
                ).fetchone()
        except sqlite3.Error as exc:
            raise ReportRepositoryError("REPORT_STORAGE_FAILED", "could not read terminal outcome") from exc
        if row is None:
            return None
        return StoredReport(
            incident_id=row[0],
            status=row[1],
            has_log=bool(row[8]),
            artifact_uris=json.loads(row[9]),
            claims=[Claim.model_validate(item) for item in json.loads(row[10])],
            warnings=_parse_json_list(row[11]),
            review_audit=[ReviewAuditEntry.model_validate(item) for item in json.loads(row[12])],
            final_report=DraftReport.model_validate_json(row[2]) if row[2] else None,
            evidence_ids=_parse_json_list(row[3]),
            reviewer=row[4],
            decision=row[5],
            reason=row[6],
            stored_at=datetime.fromisoformat(row[7]),
        )

    def _initialize(self) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS incident_reports (
                        incident_id TEXT PRIMARY KEY,
                        status TEXT NOT NULL,
                        final_report_json TEXT,
                        evidence_json TEXT NOT NULL,
                        reviewer TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        reason TEXT,
                        stored_at TEXT NOT NULL,
                        has_log INTEGER NOT NULL DEFAULT 0,
                        artifact_json TEXT NOT NULL DEFAULT '{}',
                        claims_json TEXT NOT NULL DEFAULT '[]',
                        warnings_json TEXT NOT NULL DEFAULT '[]',
                        audit_json TEXT NOT NULL DEFAULT '[]'
                    )
                    """
                )
                columns = {row[1] for row in connection.execute("PRAGMA table_info(incident_reports)")}
                migrations = {
                    "has_log": "ALTER TABLE incident_reports ADD COLUMN has_log INTEGER NOT NULL DEFAULT 0",
                    "artifact_json": "ALTER TABLE incident_reports ADD COLUMN artifact_json TEXT NOT NULL DEFAULT '{}'",
                    "claims_json": "ALTER TABLE incident_reports ADD COLUMN claims_json TEXT NOT NULL DEFAULT '[]'",
                    "warnings_json": "ALTER TABLE incident_reports ADD COLUMN warnings_json TEXT NOT NULL DEFAULT '[]'",
                    "audit_json": "ALTER TABLE incident_reports ADD COLUMN audit_json TEXT NOT NULL DEFAULT '[]'",
                }
                for column, statement in migrations.items():
                    if column not in columns:
                        connection.execute(statement)
        except sqlite3.Error as exc:
            raise ReportRepositoryError("REPORT_STORAGE_FAILED", "could not initialize report storage") from exc

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)


def _json_list(values: list[str]) -> str:
    return json.dumps(values, separators=(",", ":"))


def _parse_json_list(value: str) -> list[str]:
    parsed = json.loads(value)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise ReportRepositoryError("REPORT_STORAGE_INVALID", "stored evidence list is invalid")
    return parsed
