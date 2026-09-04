"""Append-only audit logging and state store backed by SQLite.

Records all mandate issuances, verification attempts, agent proposals, firewall verdicts,
and payment execution results. Crucially audits razorpay_called: False on rejections.
"""
from datetime import datetime, timezone
import json
import sqlite3
from typing import Any, Dict, List, Optional
from pathlib import Path


class AuditLogger:
    """Manages immutable audit log and mandate state tracking."""

    def __init__(self, db_path: str = "sentry/audit/sentry.db"):
        self.db_path = db_path
        # Ensure parent directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            # Audit log table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event TEXT NOT NULL,
                    mandate_id TEXT,
                    sku TEXT,
                    quantity INTEGER,
                    requested_total INTEGER,
                    decision TEXT,
                    reason TEXT,
                    razorpay_called BOOLEAN NOT NULL DEFAULT 0,
                    order_id TEXT,
                    details_json TEXT
                )
            """)

            # Executed orders & consumed mandates table for idempotency & single-use tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS consumed_mandates (
                    mandate_id TEXT PRIMARY KEY,
                    consumed_at TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    total_amount INTEGER NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS executed_orders (
                    idempotency_key TEXT PRIMARY KEY,
                    mandate_id TEXT NOT NULL,
                    order_id TEXT NOT NULL,
                    total_amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    razorpay_response_json TEXT
                )
            """)

            # Pending human approval orders (P1)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS pending_approvals (
                    approval_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    mandate_id TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    total_amount INTEGER NOT NULL,
                    currency TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING'
                )
            """)
            conn.commit()

    def log_event(
        self,
        event: str,
        mandate_id: Optional[str] = None,
        sku: Optional[str] = None,
        quantity: Optional[int] = None,
        requested_total: Optional[int] = None,
        decision: Optional[str] = None,
        reason: Optional[str] = None,
        razorpay_called: bool = False,
        order_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None
    ) -> int:
        """Appends an immutable audit event."""
        if timestamp is None:
            ts_str = datetime.now(timezone.utc).isoformat()
        else:
            ts_str = timestamp.astimezone(timezone.utc).isoformat()

        details_str = json.dumps(details or {}, sort_keys=True)

        with self._get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO audit_events (
                    timestamp, event, mandate_id, sku, quantity,
                    requested_total, decision, reason, razorpay_called,
                    order_id, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ts_str, event, mandate_id, sku, quantity,
                requested_total, decision, reason, 1 if razorpay_called else 0,
                order_id, details_str
            ))
            conn.commit()
            return cursor.lastrowid

    def is_mandate_used(self, mandate_id: str) -> bool:
        """Checks if a single-use mandate has already completed an order."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT 1 FROM consumed_mandates WHERE mandate_id = ?",
                (mandate_id,)
            )
            return cur.fetchone() is not None

    def mark_mandate_consumed(self, mandate_id: str, order_id: str, total_amount: int):
        """Marks mandate as consumed upon successful payment order creation."""
        ts = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO consumed_mandates (mandate_id, consumed_at, order_id, total_amount)
                VALUES (?, ?, ?, ?)
            """, (mandate_id, ts, order_id, total_amount))
            conn.commit()

    def get_idempotent_order(self, idempotency_key: str) -> Optional[dict]:
        """Retrieves existing order for idempotency key if already executed."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM executed_orders WHERE idempotency_key = ?",
                (idempotency_key,)
            )
            row = cur.fetchone()
            if row:
                return {
                    "idempotency_key": row["idempotency_key"],
                    "mandate_id": row["mandate_id"],
                    "order_id": row["order_id"],
                    "total_amount": row["total_amount"],
                    "currency": row["currency"],
                    "created_at": row["created_at"],
                    "razorpay_response": json.loads(row["razorpay_response_json"] or "{}")
                }
            return None

    def record_executed_order(
        self,
        idempotency_key: str,
        mandate_id: str,
        order_id: str,
        total_amount: int,
        currency: str,
        razorpay_response: dict
    ):
        """Records executed order for idempotency guarantee."""
        ts = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO executed_orders (
                    idempotency_key, mandate_id, order_id, total_amount, currency, created_at, razorpay_response_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                idempotency_key, mandate_id, order_id, total_amount,
                currency, ts, json.dumps(razorpay_response)
            ))
            conn.commit()

    def get_recent_events(self, limit: int = 50) -> List[dict]:
        """Returns the most recent audit events."""
        with self._get_connection() as conn:
            cur = conn.execute("""
                SELECT id, timestamp, event, mandate_id, sku, quantity,
                       requested_total, decision, reason, razorpay_called,
                       order_id, details_json
                FROM audit_events
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            rows = cur.fetchall()
            results = []
            for r in rows:
                results.append({
                    "id": r["id"],
                    "timestamp": r["timestamp"],
                    "event": r["event"],
                    "mandate_id": r["mandate_id"],
                    "sku": r["sku"],
                    "quantity": r["quantity"],
                    "requested_total": r["requested_total"],
                    "decision": r["decision"],
                    "reason": r["reason"],
                    "razorpay_called": bool(r["razorpay_called"]),
                    "order_id": r["order_id"],
                    "details": json.loads(r["details_json"] or "{}")
                })
            return results

    def clear_database(self):
        """Clears all audit tables (useful for test resets)."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM audit_events")
            conn.execute("DELETE FROM consumed_mandates")
            conn.execute("DELETE FROM executed_orders")
            conn.execute("DELETE FROM pending_approvals")
            conn.commit()
