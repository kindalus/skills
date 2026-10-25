"""Schema migrations of correio.db. Append a new step; never edit a published one."""
from __future__ import annotations

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE spaces (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('orchestration', 'swarm')),
  slice TEXT, prefix TEXT,
  protocol TEXT NOT NULL, version TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL, closed_at TEXT,
  run_dir TEXT, repo_path TEXT, base_sha TEXT, spec_path TEXT,
  contract TEXT,
  legacy INTEGER NOT NULL DEFAULT 0 CHECK (legacy IN (0, 1))
);
CREATE TRIGGER spaces_pinned BEFORE UPDATE OF id, kind, protocol, version, legacy ON spaces
WHEN NEW.id IS NOT OLD.id OR NEW.kind IS NOT OLD.kind OR NEW.protocol IS NOT OLD.protocol
  OR NEW.version IS NOT OLD.version OR NEW.legacy IS NOT OLD.legacy
BEGIN SELECT RAISE(ABORT, 'a space keeps its id, kind, protocol, version and legacy flag'); END;
CREATE TABLE members (
  space_id TEXT NOT NULL REFERENCES spaces(id),
  agent TEXT NOT NULL,
  role TEXT NOT NULL,
  generation INTEGER NOT NULL DEFAULT 1 CHECK (generation >= 1),
  pane_id TEXT, workspace_id TEXT,
  configuration TEXT,
  ready INTEGER NOT NULL DEFAULT 0,
  blocked INTEGER NOT NULL DEFAULT 0,
  attributes TEXT NOT NULL DEFAULT '{}',
  joined_at TEXT NOT NULL, left_at TEXT,
  PRIMARY KEY (space_id, agent)
);
CREATE TABLE threads (
  id INTEGER PRIMARY KEY,
  space_id TEXT NOT NULL REFERENCES spaces(id),
  key TEXT NOT NULL,
  subject TEXT,
  state TEXT NOT NULL DEFAULT 'open' CHECK (state IN ('open', 'closed')),
  opened_by TEXT, opened_at TEXT NOT NULL, closed_at TEXT,
  UNIQUE (space_id, key)
);
CREATE TABLE messages (
  id TEXT PRIMARY KEY,
  space_id TEXT NOT NULL REFERENCES spaces(id),
  thread_id INTEGER NOT NULL REFERENCES threads(id),
  protocol TEXT NOT NULL, version TEXT NOT NULL,
  type TEXT NOT NULL,
  delivery TEXT NOT NULL CHECK (delivery IN ('wake', 'info')),
  from_agent TEXT NOT NULL, from_generation INTEGER,
  to_agent TEXT NOT NULL,
  in_reply_to TEXT,
  subject TEXT NOT NULL,
  sent_at TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  envelope BLOB NOT NULL,
  fields TEXT NOT NULL,
  body TEXT NOT NULL,
  imported_from TEXT
);
CREATE TRIGGER messages_immutable BEFORE UPDATE ON messages
BEGIN SELECT RAISE(ABORT, 'messages are immutable'); END;
CREATE TRIGGER messages_kept BEFORE DELETE ON messages
BEGIN SELECT RAISE(ABORT, 'messages are never deleted'); END;
CREATE INDEX messages_to ON messages (to_agent, sent_at);
CREATE INDEX messages_thread ON messages (thread_id);
CREATE INDEX messages_type ON messages (type);
CREATE INDEX messages_reply ON messages (in_reply_to);
CREATE INDEX messages_space ON messages (space_id, sent_at);
CREATE INDEX messages_candidate ON messages (json_extract(fields, '$.candidateSha'));
CREATE INDEX messages_task ON messages (json_extract(fields, '$.taskId'));
CREATE INDEX messages_assignment ON messages (json_extract(fields, '$.assignmentId'));
CREATE TABLE attachments (
  message_id TEXT NOT NULL REFERENCES messages(id),
  path TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
  PRIMARY KEY (message_id, path)
);
CREATE TABLE receipts (
  message_id TEXT PRIMARY KEY REFERENCES messages(id),
  agent TEXT NOT NULL,
  accepted INTEGER NOT NULL CHECK (accepted IN (0, 1)),
  disposition TEXT NOT NULL,
  message_sha256 TEXT NOT NULL,
  receipted_at TEXT NOT NULL
);
CREATE TRIGGER receipts_immutable BEFORE UPDATE ON receipts
BEGIN SELECT RAISE(ABORT, 'receipts are immutable'); END;
CREATE TABLE deliveries (
  message_id TEXT PRIMARY KEY REFERENCES messages(id),
  attempts INTEGER NOT NULL DEFAULT 0,
  last_attempt_at TEXT, last_attempt_epoch REAL,
  last_agent_status TEXT, last_action TEXT,
  escalated_at TEXT
);
CREATE TABLE space_state (
  space_id TEXT PRIMARY KEY REFERENCES spaces(id),
  state TEXT NOT NULL,
  updated_by TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE tasks (
  space_id TEXT NOT NULL REFERENCES spaces(id),
  task_id TEXT NOT NULL,
  state TEXT NOT NULL,
  revision INTEGER, assignment_id TEXT, candidate_sha TEXT,
  worktree TEXT, branch TEXT, owner TEXT,
  updated_by TEXT, updated_at TEXT NOT NULL,
  PRIMARY KEY (space_id, task_id)
);
CREATE TABLE jobs (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL, who TEXT NOT NULL, cmd TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 0,
  state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'done')),
  at TEXT NOT NULL, started_at TEXT, ended_at TEXT,
  exit INTEGER
);
CREATE INDEX jobs_queue ON jobs (state, priority DESC, seq);
CREATE TABLE heartbeat (component TEXT PRIMARY KEY, pid INTEGER NOT NULL, at TEXT NOT NULL, epoch REAL NOT NULL);
CREATE TABLE observers (name TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at TEXT NOT NULL);
"""

FTS = """
CREATE VIRTUAL TABLE messages_fts USING fts5(subject, body, content='messages', content_rowid='rowid');
CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages
BEGIN INSERT INTO messages_fts(rowid, subject, body) VALUES (NEW.rowid, NEW.subject, NEW.body); END;
"""

# Version 2: who wrote a receipt when it was not the recipient (the courier, for a read-only agent).
SCHEMA_V2 = """
ALTER TABLE receipts ADD COLUMN receipted_by TEXT;
"""

# (version, statements); FTS is added with version 1 when the sqlite build has FTS5.
STEPS = [(1, SCHEMA_V1), (2, SCHEMA_V2)]
LATEST = STEPS[-1][0]
