import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.business import DomainIssue

SCHEMA = """CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, report TEXT NOT NULL, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING', revision INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '', reviewed TEXT, seq INTEGER NOT NULL DEFAULT 0
);"""

RECEIPT_SCHEMA = """CREATE TABLE IF NOT EXISTS receipts (
    id TEXT PRIMARY KEY, handoff TEXT NOT NULL UNIQUE, origin TEXT UNIQUE,
    position INTEGER NOT NULL UNIQUE, count INTEGER NOT NULL, created TEXT NOT NULL,
    payload TEXT NOT NULL
);"""


class Store:
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=15)) as db, db:
            db.row_factory = sqlite3.Row
            db.execute(SCHEMA)
            db.execute(RECEIPT_SCHEMA)
            self._migrate(db)
            yield db

    @contextmanager
    def transaction(self):
        """写事务：建表、补登记序号、选批次和落回执都在同一把锁内完成。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        begun = False
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA busy_timeout=15000")
            db.execute("BEGIN IMMEDIATE")
            begun = True
            db.execute(SCHEMA)
            db.execute(RECEIPT_SCHEMA)
            self._migrate(db)
            yield db
            db.execute("COMMIT")
            begun = False
        finally:
            if begun:
                db.execute("ROLLBACK")
            db.close()

    def _migrate(self, db):
        """把旧库的批次补齐登记序号；序号决定下游交付顺序。"""
        columns = {row["name"] for row in db.execute("PRAGMA table_info(runs)")}
        if "seq" not in columns:
            db.execute("ALTER TABLE runs ADD COLUMN seq INTEGER NOT NULL DEFAULT 0")
        pending = db.execute("SELECT id FROM runs WHERE seq=0 ORDER BY rowid").fetchall()
        if pending:
            start = db.execute("SELECT COALESCE(MAX(seq),0) FROM runs").fetchone()[0]
            for offset, row in enumerate(pending, 1):
                db.execute(
                    "UPDATE runs SET seq=? WHERE id=?", (start + offset, row["id"])
                )
        db.execute("CREATE INDEX IF NOT EXISTS runs_seq ON runs(seq)")

    def register(self, run_id, report):
        with self.transaction() as db:
            found = db.execute("SELECT id FROM runs WHERE id=?", (run_id,)).fetchone()
            if found is None:
                seq = db.execute("SELECT COALESCE(MAX(seq),0)+1 FROM runs").fetchone()[0]
                db.execute(
                    "INSERT INTO runs(id,report,created,seq) VALUES (?,?,?,?)",
                    (
                        run_id,
                        json.dumps(report, ensure_ascii=False),
                        report["manifest"]["created"],
                        seq,
                    ),
                )
        return self.load(run_id)

    def load(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise DomainIssue("RUN_NOT_FOUND")
        result = dict(row)
        result["report"] = json.loads(result["report"])
        return result

    def list(self):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,created,status,revision,note FROM runs ORDER BY created DESC,id LIMIT 50"
                )
            ]

    def revise(self, run_id, revision, status, note, now):
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE runs SET status=?,note=?,reviewed=?,revision=revision+1 WHERE id=? AND revision=?",
                (status, note, now, run_id, revision),
            )
            if cursor.rowcount != 1:
                raise DomainIssue("STALE_REVIEW")
        return self.load(run_id)

    def receipt(self, receipt_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM receipts WHERE id=?", (receipt_id,)
            ).fetchone()
        if row is None:
            raise DomainIssue("RECEIPT_NOT_FOUND")
        return json.loads(row["payload"])

    def receipts(self, limit=50):
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT id,handoff,origin,position,count,created FROM receipts "
                    "ORDER BY position DESC,created DESC,id LIMIT ?",
                    (limit,),
                )
            ]
