CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

CREATE TABLE IF NOT EXISTS cockpit_marker (
  id bigserial PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  note text NOT NULL
);

INSERT INTO cockpit_marker(note)
VALUES ('cockpit postgres sandbox initialized')
ON CONFLICT DO NOTHING;
