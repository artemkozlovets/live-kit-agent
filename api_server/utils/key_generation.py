"""Unique key generation utilities for customer codes and service orders.

These utilities generate collision-resistant identifiers using:
- secrets module for cryptographically secure random values
- UUID4 for placeholder VINs

Key formats:
- Customer code: CUST-XXXXXXXX (8 uppercase alphanumeric)
- Service order: SO-YYYYMMDD-XXXXXX (date + 6 uppercase alphanumeric)
- Placeholder VIN: NO-VIN-xxxxxxxx (8 lowercase hex from UUID)
"""

import secrets
import string
import uuid
from datetime import date

# Reason: Uppercase + digits gives 36 possible characters per position.
# For 8 chars: 36^8 ≈ 2.8 trillion combinations (customer code).
# For 6 chars: 36^6 ≈ 2.2 billion combinations (service order suffix).
ALPHANUMERIC = string.ascii_uppercase + string.digits


def generate_customer_code(random_bytes: bytes | None = None) -> str:
    """Generate unique customer code: CUST-XXXXXXXX.

    Args:
        random_bytes: Optional fixed bytes for deterministic testing.
                      In production, leave as None for secure randomness.

    Returns:
        A string like "CUST-A1B2C3D4" (13 characters total).
    """
    if random_bytes is None:
        # Production: use cryptographically secure random choice.
        suffix = "".join(secrets.choice(ALPHANUMERIC) for _ in range(8))
    else:
        # Testing: deterministic mode using provided bytes.
        # Reason: Each byte (0-255) is mapped to one of 36 characters.
        suffix = "".join(
            ALPHANUMERIC[b % len(ALPHANUMERIC)] for b in random_bytes[:8]
        )
    return f"CUST-{suffix}"


def generate_service_order_number(
    today: date | None = None,
    random_bytes: bytes | None = None,
) -> str:
    """Generate unique service order number: SO-YYYYMMDD-XXXXXX.

    Args:
        today: Date to embed in the order number. Defaults to today.
        random_bytes: Optional fixed bytes for deterministic testing.

    Returns:
        A string like "SO-20260109-A1B2C3" (18 characters total).
    """
    if today is None:
        today = date.today()

    # Reason: YYYYMMDD format is sortable and human-readable.
    date_part = today.strftime("%Y%m%d")

    if random_bytes is None:
        suffix = "".join(secrets.choice(ALPHANUMERIC) for _ in range(6))
    else:
        suffix = "".join(
            ALPHANUMERIC[b % len(ALPHANUMERIC)] for b in random_bytes[:6]
        )

    return f"SO-{date_part}-{suffix}"


def generate_placeholder_vin() -> str:
    """Generate placeholder VIN for units without a real VIN: NO-VIN-xxxxxxxx.

    Uses first 8 hex characters of a UUID4 for uniqueness.
    With 16^8 = 4.3 billion combinations, collisions are extremely unlikely.

    Returns:
        A string like "NO-VIN-a1b2c3d4" (15 characters total).
    """
    # Reason: UUID4 is based on random numbers, giving us unique values.
    # We take just the first 8 hex chars to keep it short for voice use.
    return f"NO-VIN-{uuid.uuid4().hex[:8]}"
