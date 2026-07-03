"""This module will likely live elsewhere, e.g. within the Fractal backend."""

from typing import Any

from sqlalchemy.types import JSON
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import DeclarativeBase

from sqlalchemy import UniqueConstraint


class Base(DeclarativeBase):
    """Inherits DeclarativeBase, base class for mapped objects."""

    # FIXME: Review the precise column type (JSON, JSONB, or BYTEA).
    type_annotation_map = {dict[str, Any]: JSON}


class Collection(Base):
    __tablename__ = "collection"
    __table_args__ = (UniqueConstraint("dataset_id", "url", name="dataset_url_unique"),)

    url: Mapped[str] = mapped_column(primary_key=True)
    dataset_id: Mapped[int]  # This will be a foreign-key, in a backend implementation.
    document: Mapped[dict[str, Any]]
