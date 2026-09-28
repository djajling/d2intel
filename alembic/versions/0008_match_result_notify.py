"""Новый вид уведомлений: итог матча (NOTIF-002).

Авто-цикл присылает старт/драфт до и во время игры, но исхода в нём не было:
владелец просил «после матча — кто реально победил и какой предикт давали мы».
Триггер `match_result` читает reconciled-заморозку (immutable-артефакт +
каноническая оценка `prediction_evaluation`) и пушит факт вместе с предиктом.

Только CHECK-констрейнт видов — таблица и идемпотентность не меняются.

Revision ID: 0008
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

OLD_CHECK = "kind IN ('tournament_start', 'match_start', 'draft_ready')"
NEW_CHECK = (
    "kind IN ('tournament_start', 'match_start', 'draft_ready', 'match_result')"
)
NEW_COMMENT = "tournament_start | match_start | draft_ready | match_result"


def upgrade() -> None:
    op.drop_constraint(
        "scheduled_match_notify_kind",
        "scheduled_match_notify_state",
        type_="check",
    )
    op.create_check_constraint(
        "scheduled_match_notify_kind",
        "scheduled_match_notify_state",
        NEW_CHECK,
    )
    op.alter_column(
        "scheduled_match_notify_state",
        "kind",
        existing_type=sa.Text(),
        comment=NEW_COMMENT,
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM scheduled_match_notify_state WHERE kind = 'match_result'"
        )
    )
    op.drop_constraint(
        "scheduled_match_notify_kind",
        "scheduled_match_notify_state",
        type_="check",
    )
    op.create_check_constraint(
        "scheduled_match_notify_kind",
        "scheduled_match_notify_state",
        OLD_CHECK,
    )
    op.alter_column(
        "scheduled_match_notify_state",
        "kind",
        existing_type=sa.Text(),
        comment="tournament_start | match_start | draft_ready",
        existing_nullable=False,
    )
