"""Полный драфт карты (picks/bans) как канонические данные Gate-2 (ADR-006/ADR-007).

Пара «драфт → исход» — учебный материал второго gate'а: прогноз после драфта.
Строки привязаны к канонической игре (`game.id`), поэтому исход берётся из
`game.winner_team_id`, а не из второго запроса к источнику.

Почему отдельная таблица, а не `scheduled_match.draft_observed`: заморозки
существуют только для отслеживаемых фикстур, а для набора пар нужны уже
сыгранные матчи, никакой фикстуре не соответствующие.

Почему без версионирования system_from/system_to: драфт карты не меняется
постфактум, а перезапись при уточнении источника обеспечивается
UNIQUE(game_id, ord). Временной конверт из docs/PRD_TEMPORAL.md при этом
обязателен — как и для любой другой canonical-таблицы: `event_time` это
время самой карты, `observed_at` — момент, когда мы забрали драфт у
источника, `source_published_at` остаётся NULL, потому что время публикации
OpenDota из ответа `/matches/{id}` не извлекается и выдумывать его нельзя.

Revision ID: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "picks_bans",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "game_id",
            sa.Uuid(),
            sa.ForeignKey("game.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Идентификатор в координатах провайдера (OpenDota match_id). Хранится
        # как провенанс; связь с канонией идёт через game_id, не через него.
        sa.Column("match_id", sa.BigInteger(), nullable=False),
        sa.Column("is_pick", sa.Boolean(), nullable=False),
        sa.Column("hero_id", sa.Integer(), nullable=False),
        # Конвенция OpenDota: 0 = radiant, 1 = dire.
        sa.Column("team", sa.SmallInteger(), nullable=False),
        sa.Column("ord", sa.SmallInteger(), nullable=False),
        # Временной конверт по PRD_TEMPORAL.md — обязателен для canonical.
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("source", sa.Text(), nullable=False, server_default="opendota_matches_api"),
        sa.UniqueConstraint("game_id", "ord", name="picks_bans_game_order"),
        sa.CheckConstraint("team IN (0, 1)", name="picks_bans_team_side"),
        sa.CheckConstraint("ord >= 0", name="picks_bans_order_non_negative"),
        sa.CheckConstraint("hero_id > 0", name="picks_bans_hero_positive"),
    )
    op.create_index("ix_picks_bans_game_id", "picks_bans", ["game_id"])
    op.create_index("ix_picks_bans_match_id", "picks_bans", ["match_id"])


def downgrade() -> None:
    op.drop_index("ix_picks_bans_match_id", table_name="picks_bans")
    op.drop_index("ix_picks_bans_game_id", table_name="picks_bans")
    op.drop_table("picks_bans")
