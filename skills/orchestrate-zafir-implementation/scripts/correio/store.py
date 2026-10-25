"""SQLite store of correio v2: one database per repository key, WAL, short IMMEDIATE transactions."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import pathlib
import sqlite3
import time
from typing import Any, Iterator

from . import migrations

BUSY_TIMEOUT_MS = 10000


class CorreioError(RuntimeError):
    """A refused operation; the message says why."""


# Writers queue on a blocking flock of ``<db>.write.lock`` before BEGIN IMMEDIATE. SQLite's busy handler polls
# with growing sleeps, so a writer in a loop re-takes the lock before a sleeping one wakes, and the sleeper can
# starve past busy_timeout ("database is locked") while the other's burst lasts. A blocked flock waiter is woken
# by the kernel at the release, so writers take turns. Per process the lock is shared by every Store of the same
# file (flock is per open file), so a second Store in the process never waits on its own process.
_WRITE_LOCKS: dict[str, list[Any]] = {}


@contextlib.contextmanager
def _writer_turn(db: pathlib.Path) -> Iterator[None]:
    key = str(db.resolve()) + ".write.lock"
    entry = _WRITE_LOCKS.get(key)
    if entry is None:
        old_umask = os.umask(0o077)
        try:
            fd = os.open(key, os.O_RDWR | os.O_CREAT, 0o600)
        finally:
            os.umask(old_umask)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
        except BaseException:
            os.close(fd)
            raise
        entry = _WRITE_LOCKS[key] = [fd, 0]
    entry[1] += 1
    try:
        yield
    finally:
        entry[1] -= 1
        if entry[1] == 0:
            del _WRITE_LOCKS[key]
            fcntl.flock(entry[0], fcntl.LOCK_UN)
            os.close(entry[0])


def state_root() -> pathlib.Path:
    key = os.environ.get("CORREIO_REPO_KEY", "uwassi")
    base = pathlib.Path(os.environ.get("XDG_STATE_HOME") or pathlib.Path.home() / ".local/state")
    return base / "orchestrate-zafir-implementation" / key


def default_db_path() -> pathlib.Path:
    explicit = os.environ.get("CORREIO_DB")
    return pathlib.Path(explicit) if explicit else state_root() / "correio.db"


class Clock:
    """Wall clock; tests inject a fixed or stepping one."""

    def epoch(self) -> float:
        return time.time()

    def iso(self, epoch: float | None = None) -> str:
        value = dt.datetime.fromtimestamp(self.epoch() if epoch is None else epoch, dt.timezone.utc)
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_iso(value: Any) -> float | None:
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def fts_available() -> bool:
    con = sqlite3.connect(":memory:")
    try:
        con.execute("CREATE VIRTUAL TABLE t USING fts5(a)")
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


class Store:
    def __init__(self, path: os.PathLike[str] | str | None = None, clock: Clock | None = None):
        self.path = pathlib.Path(path) if path else default_db_path()
        self.clock = clock or Clock()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with contextlib.suppress(PermissionError):
            os.chmod(self.path.parent, 0o700)
        old_umask = os.umask(0o077)
        try:
            self.con = sqlite3.connect(str(self.path), timeout=BUSY_TIMEOUT_MS / 1000, isolation_level=None)
        finally:
            os.umask(old_umask)
        os.chmod(self.path, 0o600)
        self.con.row_factory = sqlite3.Row
        self.con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        mode = self.con.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise CorreioError(f"cannot enable WAL on {self.path}: {mode}")
        self.con.execute("PRAGMA synchronous=FULL")
        self.con.execute("PRAGMA foreign_keys=ON")
        self._depth = 0
        self.migrate()

    # -- schema -------------------------------------------------------------------------------------------
    def migrate(self) -> None:
        with self.tx():
            self.con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            row = self.con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            current = int(row[0]) if row else 0
            if current > migrations.LATEST:
                raise CorreioError(f"database schema {current} is newer than this code ({migrations.LATEST})")
            for version, script in migrations.STEPS:
                if version <= current:
                    continue
                for statement in _statements(script):
                    self.con.execute(statement)
                if version == 1:
                    fts = fts_available()
                    if fts:
                        for statement in _statements(migrations.FTS):
                            self.con.execute(statement)
                    self.con.execute("INSERT OR REPLACE INTO meta VALUES ('fts', ?)", ("1" if fts else "0",))
                self.con.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (str(version),))

    @property
    def fts(self) -> bool:
        row = self.con.execute("SELECT value FROM meta WHERE key='fts'").fetchone()
        return bool(row and row[0] == "1")

    # -- transactions ---------------------------------------------------------------------------------------
    @contextlib.contextmanager
    def tx(self) -> Iterator["Store"]:
        """BEGIN IMMEDIATE ... COMMIT; nested calls join the outer transaction."""
        if self._depth:
            self._depth += 1
            try:
                yield self
            finally:
                self._depth -= 1
            return
        with _writer_turn(self.path):
            self.con.execute("BEGIN IMMEDIATE")
            self._depth = 1
            try:
                yield self
            except BaseException:
                self.con.execute("ROLLBACK")
                raise
            else:
                self.con.execute("COMMIT")
            finally:
                self._depth = 0

    def close(self) -> None:
        self.con.close()

    def now(self) -> str:
        return self.clock.iso()

    def q(self, sql: str, args: tuple | list = ()) -> list[sqlite3.Row]:
        return self.con.execute(sql, args).fetchall()

    def one(self, sql: str, args: tuple | list = ()) -> sqlite3.Row | None:
        return self.con.execute(sql, args).fetchone()

    def x(self, sql: str, args: tuple | list = ()) -> sqlite3.Cursor:
        return self.con.execute(sql, args)

    # -- rows as dicts -------------------------------------------------------------------------------------------
    def space(self, space_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM spaces WHERE id=?", (space_id,))
        if row is None:
            return None
        value = dict(row)
        value["contract"] = json.loads(value["contract"]) if value["contract"] else None
        value["legacy"] = bool(value["legacy"])
        return value

    def members(self, space_id: str, *, include_left: bool = False) -> dict[str, dict[str, Any]]:
        sql = "SELECT * FROM members WHERE space_id=?" + ("" if include_left else " AND left_at IS NULL")
        return {row["agent"]: _member(row) for row in self.q(sql, (space_id,))}

    def member(self, space_id: str, agent: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM members WHERE space_id=? AND agent=?", (space_id, agent))
        return _member(row) if row else None

    def update_member(self, space_id: str, agent: str, **cols: Any) -> None:
        if not cols:
            return
        for key in ("configuration", "attributes"):
            if key in cols and not isinstance(cols[key], (str, type(None))):
                cols[key] = json.dumps(cols[key], sort_keys=True, ensure_ascii=False)
        sets = ", ".join(f"{key}=?" for key in cols)
        cur = self.x(f"UPDATE members SET {sets} WHERE space_id=? AND agent=?", (*cols.values(), space_id, agent))
        if cur.rowcount != 1:
            raise CorreioError(f"no member {agent} in space {space_id}")

    def message(self, message_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT m.*, t.key AS thread FROM messages m JOIN threads t ON t.id=m.thread_id WHERE m.id=?",
                       (message_id,))
        return _message(row) if row else None

    def find_messages(self, space_id: str, **where: Any) -> list[dict[str, Any]]:
        clauses, args = ["m.space_id=?"], [space_id]
        for key, value in where.items():
            if key.startswith("field_"):
                clauses.append(f"json_extract(m.fields, '$.{key[6:]}')=?")
            else:
                clauses.append(f"m.{key}=?")
            args.append(value)
        rows = self.q("SELECT m.*, t.key AS thread FROM messages m JOIN threads t ON t.id=m.thread_id WHERE "
                      + " AND ".join(clauses) + " ORDER BY m.sent_at, m.rowid", args)
        return [_message(row) for row in rows]

    def receipt(self, message_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM receipts WHERE message_id=?", (message_id,))
        if row is None:
            return None
        value = dict(row)
        value["accepted"] = bool(value["accepted"])
        return value

    def space_state(self, space_id: str) -> dict[str, Any]:
        row = self.one("SELECT state FROM space_state WHERE space_id=?", (space_id,))
        return json.loads(row[0]) if row else {}

    def set_space_state(self, space_id: str, state: dict[str, Any], by: str) -> None:
        self.x("INSERT INTO space_state(space_id, state, updated_by, updated_at) VALUES (?,?,?,?) "
               "ON CONFLICT(space_id) DO UPDATE SET state=excluded.state, updated_by=excluded.updated_by, "
               "updated_at=excluded.updated_at",
               (space_id, json.dumps(state, sort_keys=True, ensure_ascii=False), by, self.now()))
        if "state" in state:
            self.x("UPDATE spaces SET state=? WHERE id=?", (state["state"], space_id))

    def task(self, space_id: str, task_id: str) -> dict[str, Any] | None:
        row = self.one("SELECT * FROM tasks WHERE space_id=? AND task_id=?", (space_id, task_id))
        return dict(row) if row else None

    def upsert_task(self, space_id: str, task_id: str, by: str, **cols: Any) -> None:
        current = self.task(space_id, task_id)
        if current is None:
            if "state" not in cols:
                raise CorreioError("a new task needs a state")
            names = ["space_id", "task_id", "updated_by", "updated_at", *cols]
            self.x(f"INSERT INTO tasks({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
                   (space_id, task_id, by, self.now(), *cols.values()))
        else:
            sets = ", ".join(f"{key}=?" for key in cols)
            self.x(f"UPDATE tasks SET {sets}{', ' if cols else ''}updated_by=?, updated_at=? "
                   "WHERE space_id=? AND task_id=?", (*cols.values(), by, self.now(), space_id, task_id))

    def tasks(self, space_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.q("SELECT * FROM tasks WHERE space_id=? ORDER BY task_id", (space_id,))]

    def set_thread_state(self, space_id: str, key: str, state: str) -> None:
        self.x("UPDATE threads SET state=?, closed_at=? WHERE space_id=? AND key=?",
               (state, self.now() if state == "closed" else None, space_id, key))

    def close_space(self, space_id: str) -> None:
        self.x("UPDATE spaces SET closed_at=COALESCE(closed_at, ?) WHERE id=?", (self.now(), space_id))

    def observer(self, name: str) -> dict[str, Any] | None:
        row = self.one("SELECT state FROM observers WHERE name=?", (name,))
        return json.loads(row[0]) if row else None

    def set_observer(self, name: str, state: dict[str, Any]) -> None:
        self.x("INSERT INTO observers(name, state, updated_at) VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET "
               "state=excluded.state, updated_at=excluded.updated_at",
               (name, json.dumps(state, sort_keys=True, ensure_ascii=False), self.now()))

    def beat(self, component: str) -> None:
        self.x("INSERT INTO heartbeat(component, pid, at, epoch) VALUES (?,?,?,?) ON CONFLICT(component) DO UPDATE "
               "SET pid=excluded.pid, at=excluded.at, epoch=excluded.epoch",
               (component, os.getpid(), self.now(), self.clock.epoch()))

    def backup(self, target: pathlib.Path) -> pathlib.Path:
        """``sqlite3 .backup`` through the online backup API."""
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        old_umask = os.umask(0o077)
        try:
            dest = sqlite3.connect(str(tmp))
            try:
                self.con.backup(dest)
            finally:
                dest.close()
        finally:
            os.umask(old_umask)
        os.replace(tmp, target)
        return target


def _statements(script: str) -> list[str]:
    """Split a schema script on statement ends, keeping trigger bodies whole."""
    out, buf = [], []
    for line in script.strip().splitlines():
        buf.append(line)
        text = "\n".join(buf).strip()
        if text and sqlite3.complete_statement(text):
            out.append(text)
            buf = []
    if "".join(buf).strip():
        raise CorreioError("incomplete schema statement")
    return out


def _member(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["configuration"] = json.loads(value["configuration"]) if value["configuration"] else None
    value["attributes"] = json.loads(value["attributes"] or "{}")
    value["ready"], value["blocked"] = bool(value["ready"]), bool(value["blocked"])
    return value


def _message(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["fields"] = json.loads(value["fields"])
    value["envelope"] = bytes(value["envelope"])
    value.pop("rowid", None)
    return value

