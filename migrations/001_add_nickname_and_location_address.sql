-- Migration: Add unit_nickname and location_address columns
-- Purpose: Support multi-strategy unit lookup (VIN → unit_number → nickname)
--          and store raw service location strings.
-- Safety: Additive changes only (no column drops or type changes).

-- 1) Add unit_nickname column to units table.
-- Reason: Allows customers to identify vehicles by friendly names (e.g., "Blue Truck").
ALTER TABLE units
  ADD COLUMN IF NOT EXISTS unit_nickname TEXT;

-- 2) Add location_address column to service_orders table.
-- Reason: Stores raw location string from caller (e.g., "I-70 and Wadsworth").
ALTER TABLE service_orders
  ADD COLUMN IF NOT EXISTS location_address TEXT;

-- 3) Add index for nickname lookup.
-- Reason: Optimizes queries like "find unit by customer_id + nickname".
-- NOTE: CONCURRENTLY avoids locking the table during index creation.
--       Must be run outside a transaction block.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_units_customer_id_unit_nickname
  ON units (customer_id, unit_nickname);
