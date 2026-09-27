"""Provenance закрытия серии: почему мы считаем серию полной (решение владельца 2026-09-27).

`normalize/map_index.py` доказывает номера карт только когда карт ровно
`best_of`. Для bo5, завершённой 3:0 или 3:1, это недостижимо из одного
OpenDota: физически карт три или четыре, и «недостающие» никогда не
появятся. Раньше такие серии висели `incomplete` forever, а вердикт по
заморозке не сходился никогда — в частности по первому сбывшемуся прогнозу
(`8987f801`, Yandex — NaVi, bo5 3:0).

Решение владельца: закрывать серию по внешнему подтверждению — Liquipedia
(источник уже принят ADR-008 для расписания) сообщает `finished` и счёт;
если число карт в БД равно сумме счёта, серия полна.

Колонка `closure_evidence` — НЕ наблюдаемый факт, а provenance решения:
кто подтвердил закрытие, каким счётом и когда мы это видели. NULL означает
«закрытие доказано по OpenDota» (карт ровно best_of) — старое правило.

Revision ID: 0006
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "series",
        sa.Column("closure_evidence", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("series", "closure_evidence")
