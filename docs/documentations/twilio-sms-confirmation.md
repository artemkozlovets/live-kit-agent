# Twilio Confirmation SMS (Codex Context)

> **Last Updated**: 2026-01-30  
> **Audience**: Codex (repo context)  
> **Status**: Draft

## TL;DR
- **Goal:** send a confirmation SMS at the end of a call (after booking) using Twilio, and track delivery status callbacks.
- **Entry points:**
  - Tool send: [`handle_send_confirmation_sms`](../../api_server/vapi/handlers/phone.py#L421)
  - Status webhook: `POST /twilio/status-callback` ([`twilio_status_callback`](../../api_server/integrations/twilio/router.py#L65))
- **Where to change:**
  - Twilio API call: [`send_sms_via_twilio`](../../api_server/integrations/twilio/messages_client.py#L83)
  - Persistence: [`SmsMessageStore`](../../api_server/integrations/twilio/sms_message_store.py#L34)
  - DB schema: [`migrations/003_add_sms_messages.sql`](../../migrations/003_add_sms_messages.sql)
- **How to verify:** `./scripts/test_all.sh`

## Key Files
- [`api_server/vapi/handlers/phone.py`](../../api_server/vapi/handlers/phone.py#L421) — implements tool `send_confirmation_sms`
- [`api_server/integrations/twilio/messages_client.py`](../../api_server/integrations/twilio/messages_client.py#L38) — loads env + sends Twilio Messages API request
- [`api_server/integrations/twilio/router.py`](../../api_server/integrations/twilio/router.py#L65) — receives Twilio `StatusCallback` webhooks
- [`api_server/integrations/twilio/sms_message_store.py`](../../api_server/integrations/twilio/sms_message_store.py#L34) — stores MessageSid/status (in-memory or Postgres)
- [`migrations/003_add_sms_messages.sql`](../../migrations/003_add_sms_messages.sql) — adds `sms_messages` table
- [`squad/assistants/booking.prompt.md`](../../squad/assistants/booking.prompt.md#L1) — instructs the agent to ask permission then call `send_confirmation_sms`

## Flow (Happy Path)
1. Agent completes booking (`store_service_order`) and asks for permission (see [`booking.prompt.md`](../../squad/assistants/booking.prompt.md#L1)).
2. Agent calls backend `POST /tools` with tool `send_confirmation_sms`.
3. Backend normalizes the phone number and loads Twilio config:
   - Phone normalization: [`normalize_us_phone_number`](../../api_server/utils/phone_formatting.py#L1)
   - Twilio config: [`load_twilio_sms_config`](../../api_server/integrations/twilio/messages_client.py#L38)
4. Backend sends the SMS via Twilio Messages API ([`send_sms_via_twilio`](../../api_server/integrations/twilio/messages_client.py#L83)).
5. Backend records the outbound `MessageSid` + metadata:
   - Call-scoped idempotency: `session["confirmation_sms_message_sid"]` ([`phone.py`](../../api_server/vapi/handlers/phone.py#L445))
   - Durable tracking (Postgres when configured): [`sms_message_store.record_outbound_message`](../../api_server/vapi/handlers/phone.py#L521)
6. Twilio POSTs delivery updates to `POST /twilio/status-callback` and we persist status/error metadata:
   - Webhook handler: [`twilio_status_callback`](../../api_server/integrations/twilio/router.py#L65)
   - Store update: [`sms_message_store.update_status`](../../api_server/integrations/twilio/router.py#L94)

## Contracts / Invariants
- **Stub behavior must remain stable**: when Twilio env vars aren’t configured, `send_confirmation_sms` returns:
  - `{"sent": false, "sms_status": "not_configured", ...}` ([`phone.py`](../../api_server/vapi/handlers/phone.py#L477))
- **Idempotent per call**: if `send_confirmation_sms` is called twice for the same call, we return `already_sent` and do not re-send ([`phone.py`](../../api_server/vapi/handlers/phone.py#L445)).
- **PII minimization**: `sms_messages` stores only `to_last4`/`from_last4` (not full phone numbers) ([`migrations/003_add_sms_messages.sql`](../../migrations/003_add_sms_messages.sql)).
- **Webhook auth is optional but supported**:
  - If `TWILIO_WEBHOOK_TOKEN` is set, `/twilio/status-callback` requires `?token=<TWILIO_WEBHOOK_TOKEN>` ([`router.py`](../../api_server/integrations/twilio/router.py#L26)).

## Configuration
Backend (Railway / `.env`):
- `TWILIO_ACCOUNT_SID` — Twilio Account SID
- `TWILIO_AUTH_TOKEN` — Twilio Auth Token (secret)
- Choose one:
  - `TWILIO_SMS_FROM_NUMBER` — Twilio phone number in E.164 (recommended for “separate SMS number”)
  - `TWILIO_MESSAGING_SERVICE_SID` — Twilio Messaging Service SID (optional alternative)
- Optional delivery tracking:
  - `TWILIO_STATUS_CALLBACK_URL` — set to `https://<backend>/twilio/status-callback?token=<...>`
  - `TWILIO_WEBHOOK_TOKEN` — if set, must match the callback URL token

Example env template: [`.env.example`](../../.env.example).

## Verification
- Happy path (full suite): `./scripts/test_all.sh`
- Targeted tests (Twilio + SMS tool): `.venv/bin/python -m pytest -q api_server/tests -k send_confirmation_sms`
- Failure case (webhook token enforced): `.venv/bin/python -m pytest -q api_server/tests -k twilio_status_callback_requires_token`

## Failure Modes / Gotchas
- **Twilio trial accounts**: can only message verified recipient numbers (so production SMS needs a paid account).
- **No delivery updates**: if `TWILIO_STATUS_CALLBACK_URL` isn’t set, sends still work, but `sms_messages.status` won’t be updated by Twilio callbacks.
- **Webhook body parsing**: Twilio sends `application/x-www-form-urlencoded`. We parse it without `python-multipart` ([`_parse_urlencoded_body`](../../api_server/integrations/twilio/router.py#L36)).

## Related Docs
- [`docs/documentations/api-server.md`](./api-server.md)
- [`docs/documentations/database-and-migrations.md`](./database-and-migrations.md)
