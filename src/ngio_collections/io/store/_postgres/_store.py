from __future__ import annotations
import json

from typing import Iterator, Any

from ngio_collections.io.store._protocols import (
    StoreReadOnlyError,
    StoreDuplicateValueError,
)

from sqlalchemy.exc import NoResultFound, IntegrityError
from sqlalchemy import select, delete, func

from sqlalchemy import Engine
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession, AsyncEngine
from ngio_collections._types import JSONValue


class CollectionDBModel:
    """This currently only exists for type hinting."""

    dataset_id: int
    url: str
    document: JSONValue


class PostgresStore:
    dataset_id: int
    engine_sync: Engine
    engine_async: AsyncEngine

    orm_model: CollectionDBModel  # FIXME: Review this type hint

    def __init__(
        self,
        dataset_id: int,
        engine_sync: Engine,
        engine_async: AsyncEngine,
        orm_model: CollectionDBModel,  # FIXME: Review this type hint
        *,
        read_only: bool = False,
    ) -> None:
        """Start with whatever already lives in the database.

        Args:
            dataset_id: FIXME
            engine_sync: FIXME
            engine_async: FIXME
            orm_model: FIXME
            read_only: Whether `put` / `delete` raise `StoreReadOnlyError`.
        """
        self.dataset_id = dataset_id
        self.engine_sync = engine_sync
        self.engine_async = engine_async
        self.read_only = read_only
        self.orm_model = orm_model

    def _check_writable(self) -> None:
        if self.read_only:
            raise StoreReadOnlyError("MemoryStore is read-only")

    def _dict_to_bytes(self, data: JSONValue) -> bytes:
        return json.dumps(data).encode()

    def _bytes_to_dict(self, data: bytes) -> JSONValue:
        return json.loads(data.decode())

    async def get(self, url: str) -> bytes:
        """Return the bytes of the document stored at `url`.

        Raises:
            FileNotFoundError: If nothing is stored at `url`.
        """
        async with AsyncSession(bind=self.engine_async) as session:
            try:
                stmt = (
                    select(self.orm_model)
                    .where(self.orm_model.dataset_id == self.dataset_id)
                    .where(self.orm_model.url == url)
                )
                collection = (await session.execute(stmt)).scalars().one()
                return self._dict_to_bytes(collection.document)
            except NoResultFound as exc:
                raise FileNotFoundError(url) from exc

    async def put(self, url: str, data: bytes) -> None:
        """Store `data` at `url`.

        Raises:
            StoreReadOnlyError: If the store is read-only.
        """
        self._check_writable()
        async with AsyncSession(bind=self.engine_async) as session:
            session.add(
                self.orm_model(
                    dataset_id=self.dataset_id,
                    url=url,
                    document=self._bytes_to_dict(data),
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                # FIXME: We should only handle an IntegrityError due to
                # duplicate values, not an arbitrary one.
                raise StoreDuplicateValueError(url) from exc

    async def delete(self, url: str) -> None:
        """Remove the entry at `url`; idempotent (a missing URL is fine).

        Raises:
            StoreReadOnlyError: If the store is read-only.
        """
        self._check_writable()
        async with AsyncSession(bind=self.engine_async) as session:
            stmt = (
                delete(self.orm_model)
                .where(self.orm_model.dataset_id == self.dataset_id)
                .where(self.orm_model.url == url)
            )
            await session.execute(stmt)
            await session.commit()

    def items(self) -> Iterator[tuple[str, bytes]]:
        """Iterate over a snapshot of the stored `(url, bytes)` pairs."""
        with Session(bind=self.engine_sync) as session:
            stmt = (
                select(self.orm_model.url, self.orm_model.document)
                .where(self.orm_model.dataset_id == self.dataset_id)
                .order_by(self.orm_model.url)
            )
            res = session.execute(stmt)
            return iter(res.all())

    def __contains__(self, url: object) -> bool:
        """Return whether `url` has stored bytes."""
        stmt = (
            select(self.orm_model)
            .where(self.orm_model.dataset_id == self.dataset_id)
            .where(self.orm_model.url == url)
        )
        with Session(bind=self.engine_sync) as session:
            try:
                session.execute(stmt).scalars().one()
                return True
            except NoResultFound:
                return False

    def __len__(self) -> int:
        """Return the number of stored documents."""
        stmt = select(func.count(self.orm_model.url)).where(
            self.orm_model.dataset_id == self.dataset_id
        )
        with Session(bind=self.engine_sync) as session:
            return session.execute(stmt).one().scalar()
