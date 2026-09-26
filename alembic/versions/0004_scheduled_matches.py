"""Расписание турниров и матчей (ручной ввод владельца).

Запланированные фикстуры вводятся владельцем вручную: легального
автоматического источника расписаний не существует (вердикт SRC-002),
поэтому таблица — локальный операционный список для prospective-контура,
а не evidence-данные. Freeze по фикстуре ссылается на immutable-файл
`artifacts/prospective/<freeze_id>.json`; наблюдаемый драфт хранится как
данные для Gate-2 (ADR-006) и НЕ является входом текущей модели.

Revision ID: 0004
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_match",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tournament_label", sa.Text(), nullable=False),
        sa.Column("team_a_label", sa.Text(), nullable=False),
        sa.Column("team_b_label", sa.Text(), nullable=False),
        sa.Column("stage_label", sa.Text()),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default="upcoming",
        ),
        sa.Column("freeze_id", sa.Uuid()),
        sa.Column("draft_observed", sa.JSON()),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('upcoming', 'frozen', 'played', 'cancelled')",
            name="scheduled_match_status",
        ),
        sa.CheckConstraint("team_a_label <> team_b_label", name="scheduled_match_teams_distinct"),
    )


def downgrade() -> None:
    op.drop_table("scheduled_match")
