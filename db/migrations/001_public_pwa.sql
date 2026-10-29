-- Backend-owned tables. Run with the private backend database role, never the browser.

CREATE TABLE IF NOT EXISTS pwa_users (
 id TEXT PRIMARY KEY, email TEXT NOT NULL, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user'
);
CREATE TABLE IF NOT EXISTS pwa_submissions (
 id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES pwa_users(id), label TEXT NOT NULL,
 language TEXT NOT NULL, filename TEXT NOT NULL, size INTEGER NOT NULL, mime TEXT NOT NULL,
 rights INTEGER NOT NULL, training INTEGER NOT NULL, research INTEGER NOT NULL DEFAULT 0, idempotency_key TEXT NOT NULL,
 moderation_status TEXT NOT NULL DEFAULT 'pending', processing_status TEXT NOT NULL DEFAULT 'not_started',
 source_status TEXT NOT NULL DEFAULT 'uploading', source_ref TEXT, source_metadata TEXT NOT NULL DEFAULT '{}',
 reason TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 0, created_at DOUBLE PRECISION NOT NULL,
 UNIQUE(owner_id,idempotency_key)
);
ALTER TABLE pwa_submissions ADD COLUMN IF NOT EXISTS research INTEGER NOT NULL DEFAULT 0;
CREATE TABLE IF NOT EXISTS pwa_jobs (
 id TEXT PRIMARY KEY, submission_id TEXT NOT NULL UNIQUE REFERENCES pwa_submissions(id),
 state TEXT NOT NULL, attempt INTEGER NOT NULL DEFAULT 0, lease_until DOUBLE PRECISION,
 lease_token TEXT, worker TEXT, error_code TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS pwa_artifacts (
 submission_id TEXT PRIMARY KEY REFERENCES pwa_submissions(id), payload BYTEA NOT NULL,
 checksum TEXT NOT NULL, metadata TEXT NOT NULL, backed_up INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS pwa_audit (
 id TEXT PRIMARY KEY, submission_id TEXT NOT NULL, actor_id TEXT NOT NULL,
 action TEXT NOT NULL, detail TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL
);
CREATE TABLE IF NOT EXISTS pwa_training_runs (
 id TEXT PRIMARY KEY, state TEXT NOT NULL, snapshot TEXT NOT NULL, metrics TEXT NOT NULL DEFAULT '{}',
 reason TEXT NOT NULL DEFAULT '', created_at DOUBLE PRECISION NOT NULL,
 lease_until DOUBLE PRECISION, lease_token TEXT
);
CREATE TABLE IF NOT EXISTS pwa_uploads (
 submission_id TEXT PRIMARY KEY REFERENCES pwa_submissions(id), received INTEGER NOT NULL DEFAULT 0,
 session_uri TEXT, file_id TEXT
);

ALTER TABLE pwa_users ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON pwa_users FROM anon, authenticated;

ALTER TABLE pwa_submissions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON pwa_submissions FROM anon, authenticated;

ALTER TABLE pwa_jobs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON pwa_jobs FROM anon, authenticated;

ALTER TABLE pwa_artifacts ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON pwa_artifacts FROM anon, authenticated;

ALTER TABLE pwa_audit ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON pwa_audit FROM anon, authenticated;

ALTER TABLE pwa_training_runs ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON pwa_training_runs FROM anon, authenticated;

ALTER TABLE pwa_uploads ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON pwa_uploads FROM anon, authenticated;
