"""Persistencia SQLite compartida por servicios locales y puente AWS."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()


SCHEMA = """
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
            """
