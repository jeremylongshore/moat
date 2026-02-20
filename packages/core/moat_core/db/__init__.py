"""
moat_core.db
~~~~~~~~~~~~
Shared async SQLAlchemy database utilities for all Moat services.

Usage::

    from moat_core.db import Base, create_engine, create_session_factory, init_tables

    engine = create_engine(settings.DATABASE_URL)
    session_factory = create_session_factory(engine)
    await init_tables(engine)
"""

from moat_core.db.base import Base, create_engine, create_session_factory, init_tables
from moat_core.db.models import (
    CapabilityRow,
    ConnectionRow,
    IdempotencyCacheRow,
    OutcomeEventRow,
    PolicyBundleRow,
    ReceiptRow,
)

__all__ = [
    "Base",
    "CapabilityRow",
    "ConnectionRow",
    "IdempotencyCacheRow",
    "OutcomeEventRow",
    "PolicyBundleRow",
    "ReceiptRow",
    "create_engine",
    "create_session_factory",
    "init_tables",
]
