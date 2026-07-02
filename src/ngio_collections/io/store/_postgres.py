from __future__ import annotations
import json

from typing import Iterator, Any

from ngio_collections.io.store._protocols import StoreReadOnlyError


from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.exc import NoResultFound, IntegrityError
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import URL, select, delete, func

from sqlalchemy import create_engine, Engine
from sqlalchemy.orm import Session
from sqlalchemy import UniqueConstraint


SQLALCHEMY_DB_URL = URL(
    drivername="postgresql+psycopg",
    host="/var/run/postgresql/",
    port=5432,
    database="v3",
    username=None,
    password=None,
    query={},
)
DATASET_ID = 123


def init_session(ID: str) -> Session:
    return Session(
        autocommit=False,
        autoflush=False,
        bind=create_engine(ID),
    )


class Base(DeclarativeBase):
    """Inherits DeclarativeBase, base class for mapped objects."""

    type_annotation_map = {dict[str, Any]: JSON}


class Collection(Base):
    __tablename__ = "collection"
    __table_args__ = (UniqueConstraint("dataset_id", "url", name="dataset_url_unique"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    dataset_id: Mapped[int]
    url: Mapped[str]
    document: Mapped[dict[str, Any]]


class PostgresStore:
    dataset_id: int
    engine: Engine
    session: Session

    def __init__(
        self,
        dataset_id: int,
        engine: Engine,
        *,
        read_only: bool = False,
    ) -> None:
        """Start from a copy of `initial` (empty by default).

        Args:
            dataset_id: FIXME
            read_only: Whether `put` / `delete` raise `StoreReadOnlyError`.
        """
        self.dataset_id = dataset_id
        self.engine = engine
        self.read_only = read_only
        session = init_session(SQLALCHEMY_DB_URL)
        Base.metadata.create_all(session.get_bind())

    def _check_writable(self) -> None:
        if self.read_only:
            raise StoreReadOnlyError("MemoryStore is read-only")

    def get(self, url: str) -> bytes:
        """Return the bytes of the document stored at `url`.

        Raises:
            FileNotFoundError: If nothing is stored at `url`.
        """
        with Session(bind=self.engine) as session:
            try:
                collection = (
                    session.execute(
                        select(Collection)
                        .where(Collection.dataset_id == self.dataset_id)
                        .where(Collection.url == url)
                    )
                    .scalars()
                    .one()
                )
                return json.dumps(collection.document).encode()
            except NoResultFound as exc:
                raise FileNotFoundError(url) from exc

    def put(self, url: str, data: bytes) -> None:
        """Store `data` at `url`.

        Raises:
            StoreReadOnlyError: If the store is read-only.
        """
        self._check_writable()
        with Session(bind=self.engine) as session:
            session.add(
                Collection(
                    dataset_id=self.dataset_id,
                    url=url,
                    document=json.loads(data.decode()),
                )
            )
            session.commit()

    def delete(self, url: str) -> None:
        """Remove the entry at `url`; idempotent (a missing URL is fine).

        Raises:
            StoreReadOnlyError: If the store is read-only.
        """
        self._check_writable()
        stmt = (
            delete(Collection)
            .where(Collection.dataset_id == self.dataset_id)
            .where(Collection.url == url)
        )
        with Session(bind=self.engine) as session:
            session.execute(stmt)
            session.commit()

    def items(self) -> Iterator[tuple[str, bytes]]:
        """Iterate over a snapshot of the stored `(url, bytes)` pairs."""
        stmt = (
            select(Collection.url, Collection.document)
            .where(Collection.dataset_id == self.dataset_id)
            .order_by(Collection.url)
        )
        with Session(bind=self.engine) as session:
            res = session.execute(stmt)
            return iter(res.all())

    def __contains__(self, url: object) -> bool:
        """Return whether `url` has stored bytes."""
        with Session(bind=self.engine) as session:
            try:
                (
                    session.execute(
                        select(Collection)
                        .where(Collection.dataset_id == self.dataset_id)
                        .where(Collection.url == url)
                    )
                    .scalars()
                    .one()
                )
                return True
            except NoResultFound:
                return False

    def __len__(self) -> int:
        """Return the number of stored documents."""
        stmt = select(func.count(Collection.id)).where(
            Collection.dataset_id == self.dataset_id
        )
        with Session(bind=self.engine) as session:
            return session.execute(stmt).scalar()


def create_test_data(engine):
    with Session(bind=engine) as session:
        session.add(
            Collection(
                dataset_id=DATASET_ID,
                url="/tmp/dataset123/zarr.json",
                document={"type": "root"},
            )
        )
        session.add(
            Collection(
                dataset_id=DATASET_ID,
                url="/tmp/dataset123/plate/zarr.json",
                document={"type": "plate"},
            )
        )
        session.add(
            Collection(
                dataset_id=DATASET_ID,
                url="/tmp/dataset123/plate/B/03/zarr.json",
                document={"type": "well"},
            )
        )
        session.add(
            Collection(
                dataset_id=DATASET_ID,
                url="/tmp/dataset123/plate/B/03/0/zarr.json",
                document={"type": "image"},
            )
        )
        session.commit()


engine = create_engine(
    SQLALCHEMY_DB_URL,
    # echo=True,  # Include `echo=True` for debugging the SQL statements
)
Base.metadata.create_all(engine)

create_test_data(engine)

store = PostgresStore(dataset_id=DATASET_ID, engine=engine)

# get / success
assert (
    store.get("/tmp/dataset123/plate/zarr.json")
    == json.dumps({"type": "plate"}).encode()
)

# get / error
try:
    store.get("/tmp/dataset123/missing")
    raise RuntimeError("Unreachable branch")
except FileNotFoundError:
    print("OK (file not found, as expected)")

# put / success

store.put(
    "/tmp/dataset123/plate/b/99/0/zarr.json",
    json.dumps({"some": "thing"}).encode(),
)
assert "/tmp/dataset123/plate/b/99/0/zarr.json" in store

# put / failure

try:
    store.put(
        "/tmp/dataset123/plate/b/99/0/zarr.json",
        json.dumps({"some": "thing"}).encode(),
    )
    raise RuntimeError("Unreachable branch")
except IntegrityError:
    print("OK (cannot insert same url twice for the same dataset)")


# delete / success
store.delete("/tmp/dataset123/plate/b/99/0/zarr.json")
assert "/tmp/dataset123/plate/b/99/0/zarr.json" not in store

assert len(list(store.items())) == len(store)
