CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE TABLE IF NOT EXISTS cockpit_marker (
  id bigserial PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  note text NOT NULL
);

CREATE TABLE IF NOT EXISTS cockpit_signals (
  id text PRIMARY KEY,
  t timestamptz NOT NULL,
  fingerprint text NOT NULL,
  type text NOT NULL,
  severity text NOT NULL,
  metric text NOT NULL,
  value double precision,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS cockpit_signals_t_idx ON cockpit_signals(t DESC);
CREATE INDEX IF NOT EXISTS cockpit_signals_fingerprint_idx ON cockpit_signals(fingerprint);

CREATE TABLE IF NOT EXISTS cockpit_incidents (
  id text PRIMARY KEY,
  fingerprint text NOT NULL,
  type text NOT NULL,
  severity text NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL,
  started_at timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL,
  resolved_at timestamptz,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS cockpit_incidents_started_idx ON cockpit_incidents(started_at DESC);
CREATE INDEX IF NOT EXISTS cockpit_incidents_status_idx ON cockpit_incidents(status);
CREATE INDEX IF NOT EXISTS cockpit_incidents_fingerprint_idx ON cockpit_incidents(fingerprint);

CREATE TABLE IF NOT EXISTS cockpit_ai_verdicts (
  incident_id text PRIMARY KEY REFERENCES cockpit_incidents(id) ON DELETE CASCADE,
  status text NOT NULL,
  chat_id text,
  model_id text,
  verdict jsonb,
  payload jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS cockpit_query_fingerprint_snapshots (
  observed_at timestamptz NOT NULL,
  userid oid NOT NULL,
  dbid oid NOT NULL,
  queryid bigint NOT NULL,
  calls bigint NOT NULL,
  total_plan_time double precision NOT NULL,
  total_exec_time double precision NOT NULL,
  rows bigint NOT NULL,
  shared_blks_hit bigint NOT NULL,
  shared_blks_read bigint NOT NULL,
  shared_blks_dirtied bigint NOT NULL,
  shared_blks_written bigint NOT NULL,
  local_blks_hit bigint NOT NULL,
  local_blks_read bigint NOT NULL,
  local_blks_dirtied bigint NOT NULL,
  local_blks_written bigint NOT NULL,
  temp_blks_read bigint NOT NULL,
  temp_blks_written bigint NOT NULL,
  blk_read_time double precision NOT NULL,
  blk_write_time double precision NOT NULL,
  wal_records bigint NOT NULL,
  wal_fpi bigint NOT NULL,
  wal_bytes numeric NOT NULL,
  query text NOT NULL,
  PRIMARY KEY (observed_at, userid, dbid, queryid)
);

CREATE INDEX IF NOT EXISTS cockpit_query_fingerprint_snapshots_observed_idx
  ON cockpit_query_fingerprint_snapshots(observed_at DESC);
CREATE INDEX IF NOT EXISTS cockpit_query_fingerprint_snapshots_queryid_idx
  ON cockpit_query_fingerprint_snapshots(queryid, observed_at DESC);

INSERT INTO cockpit_marker(note)
VALUES ('cockpit postgres sandbox initialized')
ON CONFLICT DO NOTHING;
