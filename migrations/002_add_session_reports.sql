-- Adds session report storage for LiveKit Agent observability exports.
--
-- This table stores one JSON "session report" per LiveKit room (call).
-- The agent publishes it at session end via POST /observability/session-report.

CREATE TABLE IF NOT EXISTS session_reports (
  room_name TEXT PRIMARY KEY,
  report JSONB NOT NULL,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS session_reports_received_at_idx
  ON session_reports (received_at DESC);

