"""add pgvector extension and medical_knowledge table

Revision ID: 0002
Revises: 0001
Create Date: 2025-01-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "medical_knowledge",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=True),
        sa.Column("chunk_type", sa.String(30), nullable=True),
        sa.Column("metadata", postgresql.JSONB, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )

    op.create_index("ix_mk_source", "medical_knowledge", ["source"])
    op.create_index("ix_mk_entity_id", "medical_knowledge", ["entity_id"])

    # IVFFlat index for fast cosine similarity searches.
    # The index uses 100 lists — will be created after data is loaded
    # (IVFFlat needs data to build clusters; create manually after indexing).
    # For initial setup the exact scan is fine for <2000 rows.


def downgrade() -> None:
    op.drop_table("medical_knowledge")
    op.execute("DROP EXTENSION IF EXISTS vector")
