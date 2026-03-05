"""initial schema

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- jobs ---
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(), primary_key=True, index=True),
        sa.Column("file_path", sa.String(), nullable=False),
        sa.Column("locale", sa.String(), server_default="en-IN"),
        sa.Column("context", sa.String(), server_default="auto"),
        sa.Column("status", sa.String(), server_default="queued"),
        sa.Column("stage", sa.String(), server_default="uploading"),
        sa.Column("progress", sa.Integer(), server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_jobs_status_created_at", "jobs", ["status", "created_at"])

    # --- results ---
    op.create_table(
        "results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        sa.Column(
            "result_json",
            sa.JSON().with_variant(postgresql.JSONB, "postgresql"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), server_default="0.0"),
        sa.Column("processing_time", sa.Integer(), nullable=True),
        sa.Column("llm_provider", sa.String(), nullable=True),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("cached", sa.Boolean(), server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )

    # --- feedback ---
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.String(), index=True, nullable=False),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("feedback")
    op.drop_table("results")
    op.drop_index("ix_jobs_status_created_at", table_name="jobs")
    op.drop_table("jobs")
