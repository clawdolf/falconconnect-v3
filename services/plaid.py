"""Plaid bank sync — Phase 2 stub.

Will handle:
- Link token creation for Plaid Link
- Transaction sync for carrier commission deposits
- Categorization of insurance carrier payments
"""

import logging

logger = logging.getLogger("falconconnect.plaid")


async def create_link_token(user_id: str) -> str:
    """Create a Plaid Link token for the frontend. (Phase 2)"""
    raise NotImplementedError("Plaid integration is Phase 2 — not yet implemented.")


async def sync_transactions() -> int:
    """Sync recent transactions from Plaid and categorize carrier deposits. (Phase 2)"""
    raise NotImplementedError("Plaid integration is Phase 2 — not yet implemented.")
