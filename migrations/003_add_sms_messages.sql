-- Adds SMS message tracking storage for Twilio confirmation texts.
--
-- This table stores outbound Twilio MessageSid rows so delivery callbacks can be
-- correlated back to a call after the conversation ends.
--
-- PII policy:
-- - Do not store full phone numbers here. Store only last 4 digits.

CREATE TABLE IF NOT EXISTS sms_messages (
  message_sid TEXT PRIMARY KEY,
  call_id TEXT,
  to_last4 TEXT,
  from_last4 TEXT,
  status TEXT,
  error_code INTEGER,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sms_messages_call_id_idx
  ON sms_messages (call_id);

CREATE INDEX IF NOT EXISTS sms_messages_updated_at_idx
  ON sms_messages (updated_at DESC);

