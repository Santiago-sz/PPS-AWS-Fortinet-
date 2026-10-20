"""Persistent single-user development service. No AWS calls in HTTP requests."""

import base64
import hashlib
import io
import json
import re
import secrets
import sqlite3
import time
import uuid
import zipfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from docx import Document
from pypdf import PdfReader

MAX_UPLOAD = 20 * 1024 * 1024
MIMES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
TERMINAL = {
    "completed",
    "truncated",
    "could_not_audit",
    "generation_failed",
    "no_verifiable_controls",
}
DEVICE = {
    "id": "fgt_local",
    "name": "FortiGate de desarrollo",
    "connector_status": "unknown",
    "last_checked_at": None,
}


def now():
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def uid(prefix):
    return prefix + "_" + uuid.uuid4().hex


class Error(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code = status, code


def require(condition, code="invalid_request", status=400):
    if not condition:
        raise Error(status, code, code.replace("_", " "))


def validate_document(data, extension):
    """Parse server-side, with a bound on ZIP expansion before opening DOCX."""
    try:
        if extension == "pdf":
            require(data.startswith(b"%PDF-"), "invalid_document", 422)
            reader = PdfReader(io.BytesIO(data))
            require(not reader.is_encrypted, "encrypted_document", 422)
            require(len(reader.pages) <= 2000, "too_many_pages", 422)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                require(
                    sum(x.file_size for x in archive.infolist()) <= 100 * 1024 * 1024,
                    "expanded_document_too_large",
                    422,
                )
                require(len(archive.infolist()) <= 2000, "too_many_zip_entries", 422)
            text = "\n".join(p.text for p in Document(io.BytesIO(data)).paragraphs)
        require(bool(text.strip()), "no_text_layer", 422)
        return text[:100_000]
    except Error:
        raise
    except Exception:
        raise Error(422, "invalid_document", "El documento no se puede interpretar.") from None


def sanitize(value):
    if isinstance(value, dict):
        return {
            key: sanitize(item)
            for key, item in value.items()
            if not re.search(
                r"^(?:script(?:_.*)?|code)$|password|passwd|secret|token|api.?key|authorization|private.?key",
                key,
                re.I,
            )
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = re.sub(r"(?i)Bearer\s+[^\s,;]+", "Bearer [OCULTO]", value)
        value = re.sub(
            r"(?i)((?:password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*)"
            r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
            r"\1[OCULTO]",
            value,
        )
        return re.sub(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b", "[OCULTO]", value)
    return value


class Service:
    def __init__(self, database, clock=time.time):
        self.database, self.clock = str(database), clock
        Path(database).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS policies (
                    id TEXT PRIMARY KEY, version_id TEXT UNIQUE NOT NULL,
                    metadata TEXT NOT NULL, upload_id TEXT UNIQUE NOT NULL,
                    token TEXT NOT NULL, expires REAL NOT NULL, document BLOB,
                    confirmed INTEGER NOT NULL DEFAULT 0, preview TEXT,
                    upload_audit_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS audits (
                    id TEXT PRIMARY KEY, version_id TEXT NOT NULL, data TEXT NOT NULL,
                    dispatch TEXT NOT NULL DEFAULT 'waiting', object_key TEXT UNIQUE,
                    result TEXT);
                CREATE TABLE IF NOT EXISTS idempotency (
                    operation TEXT NOT NULL, key TEXT NOT NULL, payload TEXT NOT NULL,
                    response TEXT NOT NULL, PRIMARY KEY(operation, key));
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def session(self):
        return {
            "organization": {"id": "local", "name": "Desarrollo local"},
            "user": {"id": "developer", "name": "Desarrollador local"},
            "role": "analyst",
            "environment": "LOCAL",
            "development": True,
            "max_upload_bytes": MAX_UPLOAD,
            "devices": [DEVICE],
            "capabilities": {"reaudit": True, "follow_up": False},
        }

    @staticmethod
    def cached(db, operation, key, payload):
        require(isinstance(key, str) and 0 < len(key) <= 200, "idempotency_key_required")
        encoded = json.dumps(payload, sort_keys=True)
        row = db.execute(
            "SELECT * FROM idempotency WHERE operation=? AND key=?", (operation, key)
        ).fetchone()
        if row:
            require(row["payload"] == encoded, "idempotency_conflict", 409)
            return json.loads(row["response"])

    @staticmethod
    def remember(db, operation, key, payload, response):
        db.execute(
            "INSERT INTO idempotency VALUES (?,?,?,?)",
            (operation, key, json.dumps(payload, sort_keys=True), json.dumps(response)),
        )

    @staticmethod
    def new_audit(db, policy, version_id):
        aid = uid("aud")
        audit = {
            "id": aid,
            "run_id": None,
            "policy_version_id": version_id,
            "policy_name": policy["name"],
            "policy_version": policy["version_label"],
            "device": DEVICE,
            "status": "pending",
            "phase": "esperando carga",
            "started_at": now(),
            "finished_at": None,
            "failure_reason": None,
            "events": [],
        }
        db.execute(
            "INSERT INTO audits(id,version_id,data) VALUES (?,?,?)",
            (aid, version_id, json.dumps(audit)),
        )
        return aid

    def create_policy(self, payload, key):
        require(isinstance(payload, dict))
        allowed = {
            "name",
            "version_label",
            "scope",
            "description",
            "device_id",
            "sha256",
            "size",
            "mime_type",
            "extension",
        }
        require(set(payload) == allowed, "invalid_metadata_fields")
        for field in ("name", "version_label", "scope", "description"):
            require(
                isinstance(payload[field], str) and len(payload[field]) <= 4000, "invalid_" + field
            )
        require(bool(payload["name"].strip()) and bool(payload["version_label"].strip()))
        require(payload["device_id"] == DEVICE["id"], "unknown_device", 404)
        require(isinstance(payload["extension"], str) and payload["extension"] in MIMES)
        require(payload["mime_type"] == MIMES[payload["extension"]], "mime_mismatch")
        require(
            type(payload["size"]) is int and 0 < payload["size"] <= MAX_UPLOAD,
            "invalid_document_size",
            413,
        )
        require(
            isinstance(payload["sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", payload["sha256"]),
            "invalid_sha256",
        )
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = self.cached(db, "create", key, payload)
            if cached:
                return cached
            pid, vid, upload_id = uid("pol"), uid("ver"), uid("up")
            token = secrets.token_urlsafe(32)
            metadata = {
                **payload,
                "id": pid,
                "version_id": vid,
                "status": "pendiente",
                "uploaded_by": "Desarrollador local",
                "uploaded_at": now(),
                "review_status": "proposed",
                "check_count": 0,
            }
            aid = self.new_audit(db, metadata, vid)
            metadata["last_audit_id"] = aid
            db.execute(
                "INSERT INTO policies(id,version_id,metadata,upload_id,token,expires,"
                "upload_audit_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (pid, vid, json.dumps(metadata), upload_id, token, self.clock() + 900, aid),
            )
            response = {
                "policy_id": pid,
                "version_id": vid,
                "audit_id": aid,
                "upload_id": upload_id,
                "upload": {
                    "method": "PUT",
                    "url": f"/uploads/{upload_id}?token={token}",
                    "headers": {"Content-Type": payload["mime_type"]},
                },
            }
            self.remember(db, "create", key, payload, response)
            return response

    def put_upload(self, upload_id, token, data, mime):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM policies WHERE upload_id=?", (upload_id,)).fetchone()
            require(row is not None, "not_found", 404)
            require(
                secrets.compare_digest(row["token"].encode(), token.encode()),
                "invalid_upload_token",
                403,
            )
            require(self.clock() <= row["expires"], "upload_expired", 403)
            require(not row["confirmed"], "upload_already_confirmed", 409)
            metadata = json.loads(row["metadata"])
            require(mime == metadata["mime_type"], "mime_mismatch", 422)
            require(
                len(data) == metadata["size"]
                and hashlib.sha256(data).hexdigest() == metadata["sha256"],
                "checksum_mismatch",
                422,
            )
            db.execute("UPDATE policies SET document=? WHERE id=?", (data, row["id"]))

    def complete(self, pid, vid, payload, key):
        operation = f"complete:{pid}:{vid}"
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = self.cached(db, operation, key, payload)
            if cached:
                return cached
            row = db.execute(
                "SELECT * FROM policies WHERE id=? AND version_id=?", (pid, vid)
            ).fetchone()
            require(row is not None, "not_found", 404)
            metadata = json.loads(row["metadata"])
            require(
                payload
                == {
                    "upload_id": row["upload_id"],
                    "sha256": metadata["sha256"],
                    "size": metadata["size"],
                },
                "upload_metadata_mismatch",
                409,
            )
            require(row["document"] is not None, "upload_missing", 409)
            # Verify persisted bytes again; the request's checksum is not authoritative.
            data = row["document"]
            require(
                len(data) == metadata["size"]
                and hashlib.sha256(data).hexdigest() == metadata["sha256"],
                "checksum_mismatch",
                422,
            )
            if not row["confirmed"]:
                preview = validate_document(data, metadata["extension"])
                metadata["status"] = "cargada"
                db.execute(
                    "UPDATE policies SET confirmed=1,preview=?,metadata=? WHERE id=?",
                    (preview, json.dumps(metadata), pid),
                )
                self.event(
                    db,
                    metadata["last_audit_id"],
                    "recibido",
                    "Documento validado; pendiente de envío a AWS.",
                )
                db.execute(
                    "UPDATE audits SET dispatch='ready' WHERE id=?", (metadata["last_audit_id"],)
                )
            response = {"audit_id": row["upload_audit_id"], "status": "pending"}
            self.remember(db, operation, key, payload, response)
            return response

    @staticmethod
    def event(db, aid, phase, message, **updates):
        row = db.execute("SELECT data FROM audits WHERE id=?", (aid,)).fetchone()
        require(row is not None, "not_found", 404)
        audit = json.loads(row["data"])
        audit.update(updates, phase=phase)
        audit["events"].append({"phase": phase, "timestamp": now(), "message": message})
        db.execute("UPDATE audits SET data=? WHERE id=?", (json.dumps(audit), aid))

    def collection(self, kind, cursor=None):
        offset = 0
        if cursor:
            try:
                offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
            except (ValueError, UnicodeError):
                raise Error(400, "invalid_cursor", "Cursor inválido") from None
            require(0 <= offset <= 2**63 - 1, "invalid_cursor")
        table, column = ("policies", "metadata") if kind == "policies" else ("audits", "data")
        with self.db() as db:
            rows = db.execute(
                f"SELECT rowid,{column} FROM {table} WHERE rowid>? ORDER BY rowid LIMIT 51",
                (offset,),
            ).fetchall()
        return {
            "items": [json.loads(r[column]) for r in rows[:50]],
            "next_cursor": base64.urlsafe_b64encode(str(rows[49]["rowid"]).encode()).decode()
            if len(rows) > 50
            else None,
        }

    def policy(self, pid):
        with self.db() as db:
            row = db.execute("SELECT * FROM policies WHERE id=?", (pid,)).fetchone()
            require(row is not None, "not_found", 404)
            metadata = json.loads(row["metadata"])
            result = db.execute(
                "SELECT result FROM audits WHERE id=?", (metadata["last_audit_id"],)
            ).fetchone()
            checks = json.loads(result["result"])["manifest"]["checks"] if result["result"] else []
        return {
            **metadata,
            "versions": [metadata],
            "checks": checks,
            "preview_text": row["preview"] or "",
            "original_download_available": bool(row["confirmed"]),
        }

    def document(self, pid, vid):
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM policies WHERE id=? AND version_id=? AND confirmed=1", (pid, vid)
            ).fetchone()
            require(row is not None, "not_found", 404)
            return row["document"], json.loads(row["metadata"])["mime_type"]

    def audit(self, aid, results=False):
        with self.db() as db:
            row = db.execute("SELECT * FROM audits WHERE id=?", (aid,)).fetchone()
            require(row is not None, "not_found", 404)
            if results:
                require(row["result"] is not None, "results_pending", 409)
                return json.loads(row["result"])
            return json.loads(row["data"])

    def reaudit(self, payload, key):
        require(isinstance(payload, dict) and set(payload) == {"policy_version_id", "device_id"})
        require(payload["device_id"] == DEVICE["id"], "unknown_device", 404)
        require(isinstance(payload["policy_version_id"], str))
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            cached = self.cached(db, "reaudit", key, payload)
            if cached:
                return cached
            row = db.execute(
                "SELECT * FROM policies WHERE version_id=? AND confirmed=1",
                (payload["policy_version_id"],),
            ).fetchone()
            require(row is not None, "not_found", 404)
            metadata = json.loads(row["metadata"])
            aid = self.new_audit(db, metadata, row["version_id"])
            self.event(db, aid, "recibido", "Nueva auditoría en cola para AWS.")
            db.execute("UPDATE audits SET dispatch='ready' WHERE id=?", (aid,))
            metadata.update(last_audit_id=aid, status="cargada", check_count=0)
            db.execute(
                "UPDATE policies SET metadata=? WHERE id=?", (json.dumps(metadata), row["id"])
            )
            response = {"audit_id": aid, "status": "pending"}
            self.remember(db, "reaudit", key, payload, response)
            return response

    def finish(self, aid, manifest, report):
        require(isinstance(manifest, dict) and isinstance(report, dict), "invalid_result", 422)
        require(report.get("status") in TERMINAL, "invalid_status", 422)
        require(
            isinstance(report.get("run_id"), str) and bool(report["run_id"]), "invalid_run_id", 422
        )
        require(manifest.get("run_id") == report["run_id"], "run_mismatch", 422)
        for key, value in (("checks", manifest), ("findings", report)):
            require(
                isinstance(value.get(key), list)
                and all(
                    isinstance(x, dict) and isinstance(x.get("check_id"), str) and x["check_id"]
                    for x in value[key]
                ),
                "invalid_" + key,
                422,
            )
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM audits WHERE id=?", (aid,)).fetchone()
            require(row is not None, "not_found", 404)
            policy = db.execute(
                "SELECT * FROM policies WHERE version_id=?", (row["version_id"],)
            ).fetchone()
            require(policy["confirmed"], "upload_not_confirmed", 409)
            metadata = json.loads(policy["metadata"])
            require(
                manifest.get("policy_sha256") == metadata["sha256"], "policy_hash_mismatch", 422
            )
            require(
                manifest.get("policy_key") == report.get("policy_key"), "policy_key_mismatch", 422
            )
            if row["object_key"]:
                require(report.get("policy_key") == row["object_key"], "policy_key_mismatch", 422)
            result = sanitize({"manifest": manifest, "report": report, "next_cursor": None})
            encoded = json.dumps(result, sort_keys=True, ensure_ascii=False)
            require(len(encoded.encode()) <= 20 * 1024 * 1024, "results_too_large", 413)
            if row["result"]:
                require(row["result"] == encoded, "immutable_result", 409)
                return
            self.event(
                db,
                aid,
                "finalizado",
                "Reporte recibido del pipeline.",
                status=report["status"],
                run_id=report["run_id"],
                finished_at=now(),
                failure_reason=result["report"].get("failure_reason"),
            )
            db.execute("UPDATE audits SET result=?,dispatch='finished' WHERE id=?", (encoded, aid))
            if metadata["last_audit_id"] == aid:
                metadata.update(
                    status=(
                        "lista"
                        if report["status"] in {"completed", "truncated"}
                        else "sin controles verificables"
                        if report["status"] == "no_verifiable_controls"
                        else "error"
                    ),
                    check_count=len(manifest["checks"]),
                )
                db.execute(
                    "UPDATE policies SET metadata=? WHERE id=?",
                    (json.dumps(metadata), policy["id"]),
                )

    def export(self, aid, fmt):
        result = self.audit(aid, results=True)
        if fmt == "json":
            return json.dumps(
                result["report"], ensure_ascii=False, indent=2
            ).encode(), "application/json"
        require(fmt == "md", "invalid_export_format")
        report = result["report"]
        lines = [
            "# Auditoría",
            f"Run: {report['run_id']}",
            f"Estado: {report['status']}",
            "",
            "Exportación de desarrollo desde el reporte saneado.",
        ]
        for finding in report["findings"]:
            lines.extend(
                [
                    "",
                    f"## {finding['check_id']} — {finding.get('status', '')}",
                    str(finding.get("evidence", "")),
                ]
            )
        return "\n".join(lines).encode(), "text/markdown; charset=utf-8"
