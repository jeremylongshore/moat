"""
app.store
~~~~~~~~~
Async SQLAlchemy-backed stores for the control plane.

Replaces the MVP in-memory dicts with persistent storage.
The stores use a shared session factory configured during app lifespan.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from moat_core.db import AgentRow, CapabilityRow, ConnectionRow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


class CapabilityStore:
    """Async DB-backed capability registry."""

    def __init__(self) -> None:
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def configure(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def _session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError(
                "CapabilityStore not configured. Call configure() during lifespan."
            )
        return self._session_factory()

    async def create(self, data: dict[str, Any]) -> CapabilityRow:
        capability_id = str(uuid4())
        async with self._session() as session:
            row = CapabilityRow(capability_id=capability_id, **data)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get(self, capability_id: str) -> CapabilityRow | None:
        async with self._session() as session:
            return await session.get(CapabilityRow, capability_id)

    async def list(
        self,
        provider: str | None = None,
        status: str | None = None,
    ) -> list[CapabilityRow]:
        async with self._session() as session:
            stmt = select(CapabilityRow)
            if provider:
                stmt = stmt.where(CapabilityRow.provider == provider)
            if status:
                stmt = stmt.where(CapabilityRow.status == status)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_status(
        self, capability_id: str, status: str
    ) -> CapabilityRow | None:
        async with self._session() as session:
            row = await session.get(CapabilityRow, capability_id)
            if row is None:
                return None
            row.status = status
            await session.commit()
            await session.refresh(row)
            return row


class ConnectionStore:
    """Async DB-backed connection registry."""

    def __init__(self) -> None:
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def configure(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def _session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError(
                "ConnectionStore not configured. Call configure() during lifespan."
            )
        return self._session_factory()

    async def create(self, data: dict[str, Any]) -> ConnectionRow:
        connection_id = str(uuid4())
        async with self._session() as session:
            row = ConnectionRow(connection_id=connection_id, **data)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get(self, connection_id: str) -> ConnectionRow | None:
        async with self._session() as session:
            return await session.get(ConnectionRow, connection_id)

    async def list(self, tenant_id: str | None = None) -> list[ConnectionRow]:
        async with self._session() as session:
            stmt = select(ConnectionRow)
            if tenant_id:
                stmt = stmt.where(ConnectionRow.tenant_id == tenant_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())


class AgentStore:
    """Async DB-backed agent registry with ERC-8004 identity."""

    def __init__(self) -> None:
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def configure(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def _session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError(
                "AgentStore not configured. Call configure() during lifespan."
            )
        return self._session_factory()

    async def create(self, data: dict[str, Any]) -> AgentRow:
        agent_id = str(uuid4())
        async with self._session() as session:
            row = AgentRow(agent_id=agent_id, **data)
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def get(self, agent_id: str) -> AgentRow | None:
        async with self._session() as session:
            return await session.get(AgentRow, agent_id)

    async def get_by_name(self, name: str) -> AgentRow | None:
        async with self._session() as session:
            stmt = select(AgentRow).where(AgentRow.name == name)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list(
        self,
        status: str | None = None,
        owner_tenant_id: str | None = None,
    ) -> list[AgentRow]:
        async with self._session() as session:
            stmt = select(AgentRow)
            if status:
                stmt = stmt.where(AgentRow.status == status)
            if owner_tenant_id:
                stmt = stmt.where(AgentRow.owner_tenant_id == owner_tenant_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update(
        self,
        agent_id: str,
        data: dict[str, Any],
    ) -> AgentRow | None:
        async with self._session() as session:
            row = await session.get(AgentRow, agent_id)
            if row is None:
                return None
            for key, value in data.items():
                if hasattr(row, key):
                    setattr(row, key, value)
            await session.commit()
            await session.refresh(row)
            return row

    async def delete(self, agent_id: str) -> bool:
        async with self._session() as session:
            row = await session.get(AgentRow, agent_id)
            if row is None:
                return False
            await session.delete(row)
            await session.commit()
            return True


# Module-level singletons — configured during app lifespan
capability_store = CapabilityStore()
connection_store = ConnectionStore()
agent_store = AgentStore()
