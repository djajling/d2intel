"""Идемпотентное состояние отправленных уведомлений (NOTIF-001).

Уведомления отправляет рекуррентный авто-цикл (каждые 5 минут), а не
одноразовый вызов. Без фиксации «что уже отправлено» каждое окно цикла
будет слать одно и то же сообщение. Состояние — не evidence-данные: это
локальный операционный追随, связанный с фикстурой.

Ключ уведомления — `(fixture_id, kind)`: для данной фикстуры уведомление
данного вида отправляется ровно один раз. Повторная отправка возможна
только явным API-вызовом с `force=True` (ручной повтор владельцем).

Revision ID: 0007
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scheduled_match_notify_state",
        sa.Column(
            "id",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("fixture_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Text(),
            nullable=False,
            comment="tournament_start | match_start | draft_ready",
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "message_kind_hash",
            sa.Text(),
            nullable=False,
            comment="Хэш содержимого — повторная смена модели/состава не молча умножает пуш",
        ),
        sa.Column(
            "sent_kind_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
            comment="Счётчик отправок (увеличивается при force-повторе)",
        ),
        sa.UniqueConstraint("fixture_id", "kind", name="uq_notify_state_fixture_kind"),
        sa.ForeignKeyConstraint(["fixture_id"], ["scheduled_match.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "kind IN ('tournament_start', 'match_start', 'draft_ready')",
            name="scheduled_match_notify_kind",
        ),
    )
    op.create_index(
        "ix_notify_state_lookup",
        "scheduled_match_notify_state",
        ["fixture_id", "kind"],
        unique=True,
    )


def downgrade() -> None:
    import sqlalchemy as sa

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "scheduled_match_notify_state" not in inspector.get_table_names():
        return
    op.drop_index(
        "ix_notify_state_lookup", table_name="scheduled_match_notify_state", if_exists=True
    )
    op.drop_table("scheduled_match_notify_state")
