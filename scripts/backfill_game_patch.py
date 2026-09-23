#!/usr/bin/env python
"""Дозаполнение `game.patch_id` для карт, записанных до появления справочника патчей.

`patch_id` — **производный** атрибут: патч, действовавший в момент `event_time`.
Он не является наблюдаемым фактом, поэтому дозаполнение NULL не переписывает
наблюдение. Семантика ровно та же, что в `normalize.pipeline._resolve_patch`:
последний патч с `effective_from <= event_time < effective_to`.

Скрипт идемпотентен: трогает только строки с `patch_id IS NULL`.
Неизменяемые снимки (`feature_snapshot`, `prediction_snapshot`) не затрагиваются.

Примеры:

    python scripts/backfill_game_patch.py --dry-run   # только посчитать
    python scripts/backfill_game_patch.py             # записать
"""

from __future__ import annotations

import argparse
import json

from sqlalchemy import text

from d2intel.db import SessionLocal

RESOLVE_SQL = """
    SELECT id FROM patch
     WHERE effective_from <= :at
       AND (effective_to IS NULL OR effective_to > :at)
     ORDER BY effective_from DESC
     LIMIT 1
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Дозаполнение game.patch_id по справочнику патчей (производный атрибут)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Посчитать, сколько строк будет заполнено, но не писать.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    session = SessionLocal()
    try:
        rows = session.execute(
            text("SELECT id, event_time FROM game WHERE patch_id IS NULL")
        ).all()
        resolved = 0
        unresolved = 0
        for row in rows:
            patch_id = session.execute(text(RESOLVE_SQL), {"at": row.event_time}).scalar()
            if patch_id is None:
                unresolved += 1
                continue
            resolved += 1
            if not args.dry_run:
                session.execute(
                    text("UPDATE game SET patch_id = :patch_id WHERE id = :id"),
                    {"patch_id": patch_id, "id": row.id},
                )
        if not args.dry_run:
            session.commit()

        still_null = session.execute(
            text("SELECT count(*) FROM game WHERE patch_id IS NULL")
        ).scalar_one()
        print(
            json.dumps(
                {
                    "dry_run": args.dry_run,
                    "candidates": len(rows),
                    "resolved": resolved,
                    "unresolved_no_patch": unresolved,
                    "patch_id_null_after": int(still_null),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
