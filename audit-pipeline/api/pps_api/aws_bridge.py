"""Explicit, one-shot bridge to the existing S3-triggered Lambda pipeline.

No synthetic progress: only upload acknowledgement and final reports are exposed.
"""

import json

from .service import require


class Bridge:
    def __init__(self, service, s3, policies_bucket, reports_bucket):
        self.service, self.s3 = service, s3
        self.policies_bucket, self.reports_bucket = policies_bucket, reports_bucket

    def dispatch(self):
        """Claim before network I/O; ambiguous puts are never automatically repeated."""
        sent = 0
        while True:
            with self.service.db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT a.id,p.metadata,p.document FROM audits a JOIN policies p "
                    "ON p.version_id=a.version_id WHERE a.dispatch='ready' "
                    "ORDER BY a.rowid LIMIT 1"
                ).fetchone()
                if row is None:
                    break
                metadata = json.loads(row["metadata"])
                key = f"policies/{row['id']}.{metadata['extension']}"
                db.execute(
                    "UPDATE audits SET dispatch='sending',object_key=? WHERE id=?", (key, row["id"])
                )
            # S3 triggers policy_generator only after the document was validated locally.
            # If this fails after S3 accepted the object, sync still discovers the result.
            self.s3.put_object(
                Bucket=self.policies_bucket,
                Key=key,
                Body=row["document"],
                ContentType=metadata["mime_type"],
                Metadata={"audit-id": row["id"], "policy-sha256": metadata["sha256"]},
            )
            with self.service.db() as db:
                db.execute("BEGIN IMMEDIATE")
                current = db.execute(
                    "SELECT dispatch FROM audits WHERE id=?", (row["id"],)
                ).fetchone()
                if current["dispatch"] == "sending":
                    db.execute("UPDATE audits SET dispatch='sent' WHERE id=?", (row["id"],))
                    self.service.event(
                        db,
                        row["id"],
                        "recibido",
                        "S3 confirmó la recepción; esperando reporte.",
                        status="running",
                    )
                    latest = json.loads(
                        db.execute(
                            "SELECT metadata FROM policies WHERE id=?", (metadata["id"],)
                        ).fetchone()["metadata"]
                    )
                    if latest["last_audit_id"] == row["id"]:
                        latest["status"] = "procesando"
                        db.execute(
                            "UPDATE policies SET metadata=? WHERE id=?",
                            (json.dumps(latest), latest["id"]),
                        )
            sent += 1
        return sent

    def read_json(self, key):
        response = self.s3.get_object(Bucket=self.reports_bucket, Key=key)
        stream = response["Body"]
        try:
            body = stream.read(20 * 1024 * 1024 + 1)
        finally:
            stream.close()
        require(len(body) <= 20 * 1024 * 1024, "artifact_too_large", 413)
        return json.loads(body)

    def sync(self):
        with self.service.db() as db:
            pending = {
                row["object_key"]: dict(row)
                for row in db.execute(
                    "SELECT a.id,a.object_key,p.metadata FROM audits a JOIN policies p "
                    "ON p.version_id=a.version_id WHERE a.dispatch IN ('sending','sent')"
                )
            }
        if not pending:
            return 0
        candidates = {}
        for page in self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.reports_bucket, Prefix="reports/"
        ):
            for obj in page.get("Contents", []):
                if not obj["Key"].endswith("/report.json"):
                    continue
                report = self.read_json(obj["Key"])
                if report.get("policy_key") in pending:
                    candidates.setdefault(report["policy_key"], []).append(report)
        finished = 0
        for policy_key, reports in candidates.items():
            # Duplicate S3 deliveries can create multiple runs in the existing pipeline.
            # Do not arbitrarily assign one of them to the desktop audit.
            if len({r.get("run_id") for r in reports}) != 1:
                with self.service.db() as db:
                    db.execute("BEGIN IMMEDIATE")
                    aid = pending[policy_key]["id"]
                    self.service.event(
                        db,
                        aid,
                        "recibido",
                        "Se detectaron múltiples ejecuciones; requiere reconciliación.",
                    )
                    db.execute("UPDATE audits SET dispatch='conflict' WHERE id=?", (aid,))
                continue
            report = reports[0]
            run_id = report["run_id"]
            require(isinstance(run_id, str) and run_id.isalnum(), "invalid_pipeline_run_id", 422)
            try:
                manifest = self.read_json(f"artifacts/{run_id}/manifest.json")
            except self.s3.exceptions.NoSuchKey:
                require(report.get("status") == "could_not_audit", "manifest_missing", 409)
                manifest = {
                    "run_id": run_id,
                    "policy_key": policy_key,
                    "checks": [],
                    "policy_sha256": json.loads(pending[policy_key]["metadata"])["sha256"],
                }
            self.service.finish(pending[policy_key]["id"], manifest, report)
            finished += 1
        return finished
