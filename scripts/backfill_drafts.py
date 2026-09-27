#!/usr/bin/env python
"""Бэкфилл picks_bans из уже сыгранных игр — учебные пары Gate-2 (ADR-006/007).

Пары «драфт → исход» нужны для второго gate'а, но заморозки существуют только
для отслеживаемых фикстур, а плей-офф в основном уже сыгран. Здесь драфт
берётся из OpenDota `/api/matches/{id}` по канонической игре (`game.id` уже
есть в БД с победителем), исход остаётся каноническим `game.winner_team_id`.

Это исторические обучающие данные. Они НЕ являются оценкой прогноза:
ретроспективу за живой прогноз не выдаём (железное правило проекта).

Гарантии:

* отсутствие picks_bans в источнике не записывается — игра попадает в
  `skipped` с причиной, пустых строк не создаётся;
* уже собранное пропускается (ON CONFLICT + проверка NOT EXISTS);
* при rate-limit остановка, а не долбление: 429/403 → честный отказ и выход.

Пример:

    python scripts/backfill_drafts.py --limit 20 --sleep 1.0   # проба
    python scripts/backfill_drafts.py --limit 300              # пачка

Коды возврата: 0 готово/нечего делать, 1 были ошибки, 5 остановлено по
rate-limit источника, 64 bad args.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.db import SessionLocal
from d2intel.ingestion.live_draft import USER_AGENT

MATCH_URL = "https://api.opendota.com/api/matches/{match_id}"

SOURCE_LABEL = "opendota_matches_api"

RATE_LIMIT_STATUSES = (403, 429)

CURRENT_PATCH_SQL = """
    SELECT patch_id
    FROM game
    WHERE patch_id IS NOT NULL AND winner_team_id IS NOT NULL
    ORDER BY event_time DESC
    LIMIT 1
"""

CANDIDATES_SQL = """
    SELECT g.id AS game_id, g.provider_match_id AS match_id, g.event_time AS event_time
    FROM game AS g
    WHERE g.provider_match_id IS NOT NULL
      AND g.winner_team_id IS NOT NULL
      AND g.patch_id = CAST(:patch AS uuid)
      AND NOT EXISTS (
          SELECT 1 FROM picks_bans AS pb WHERE pb.game_id = g.id
      )
    ORDER BY g.event_time DESC
    LIMIT :limit
"""

INSERT_SQL = """
    INSERT INTO picks_bans
        (game_id, match_id, is_pick, hero_id, team, ord, event_time, source)
    VALUES
        (CAST(:game_id AS uuid), :match_id, :is_pick, :hero_id, :team, :ord,
         CAST(:event_time AS timestamptz), :source)
    ON CONFLICT (game_id, ord) DO NOTHING
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Собрать picks_bans сыгранных игр текущего патча в БД."
    )
    parser.add_argument("--limit", type=int, default=300, help="Сколько игр максимум (по умолчанию 300).")
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.0,
        help="Пауза между запросами /matches/{id} в секундах (по умолчанию 1.0).",
    )
    parser.add_argument(
        "--patch",
        default=None,
        help="patch_id (uuid); по умолчанию — патч самой свежей сыгранной игры.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать кандидатов и ответ источника, ничего не записывая.",
    )
    return parser.parse_args(argv)


class RateLimited(RuntimeError):
    """Источник попросил остановиться (403/429)."""


class SourceHasNoDrafts(RuntimeError):
    """У матча в источнике нет picks_bans.

    Это состояние данных, а не сбой: такую игру мы НЕ записываем («нет
    данных» не подменяем пустым списком) и НЕ считаем ошибкой — иначе
    каждый запуск в cron врал бы exit 1. Игра остаётся кандидатом и
    повторится в следующем запуске, когда источник её распарсит.
    """


def _fetch_picks_bans(match_id: str, client: httpx.Client) -> list[dict[str, Any]]:
    """picks_bans матча. RateLimited/SourceHasNoDrafts — честные отказы."""
    try:
        response = client.get(
            MATCH_URL.format(match_id=match_id),
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"сеть {type(exc).__name__}: {exc}") from exc
    if response.status_code in RATE_LIMIT_STATUSES:
        raise RateLimited(f"HTTP {response.status_code}: {response.text[:200]}")
    if response.status_code == 404:
        raise SourceHasNoDrafts("404 — матч в источнике не найден")
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("не-JSON ответ") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("ответ не объект")
    picks = payload.get("picks_bans")
    if not isinstance(picks, list) or not picks:
        raise SourceHasNoDrafts("picks_bans отсутствуют в источнике")
    return picks


def _rows_for_game(
    game_id: str, match_id: str, event_time: Any, picks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = []
    for item in picks:
        hero_id = item.get("hero_id")
        order = item.get("order")
        team = item.get("team")
        is_pick = item.get("is_pick")
        if not isinstance(hero_id, int) or hero_id <= 0:
            continue
        if not isinstance(order, int) or order < 0:
            continue
        if team not in (0, 1) or not isinstance(is_pick, bool):
            continue
        rows.append(
            {
                "game_id": game_id,
                "match_id": int(match_id),
                "is_pick": is_pick,
                "hero_id": hero_id,
                "team": team,
                "ord": order,
                "event_time": event_time,
                "source": SOURCE_LABEL,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit < 1:
        print("--limit должен быть положительным", file=sys.stderr)
        return 64

    db = SessionLocal()
    try:
        patch = args.patch or db.execute(text(CURRENT_PATCH_SQL)).scalar()
        if patch is None:
            print("нет игр с patch_id — нечего бэкфиллить")
            return 0
        candidates = [
            dict(row._mapping)
            for row in db.execute(
                text(CANDIDATES_SQL), {"patch": str(patch), "limit": args.limit}
            ).all()
        ]
        if not candidates:
            print(f"кандидатов нет (патч {patch}) — все уже собраны")
            return 0

        print(f"патч {patch}: кандидатов {len(candidates)}")
        inserted = 0
        skipped: list[tuple[str, str]] = []
        errors: list[tuple[str, str]] = []
        rate_limited: str | None = None

        with httpx.Client() as client:
            for index, game in enumerate(candidates):
                if index:
                    time.sleep(args.sleep)
                match_id = str(game["match_id"])
                try:
                    picks = _fetch_picks_bans(match_id, client)
                except RateLimited as exc:
                    rate_limited = f"{match_id}: {exc}"
                    break
                except SourceHasNoDrafts as exc:
                    skipped.append((match_id, str(exc)))
                    continue
                except RuntimeError as exc:
                    errors.append((match_id, str(exc)))
                    continue
                rows = _rows_for_game(
                    str(game["game_id"]), match_id, game["event_time"], picks
                )
                if not rows:
                    skipped.append((match_id, "после валидации не осталось строк"))
                    continue
                if args.dry_run:
                    print(f"  would write {len(rows)} rows for {match_id}")
                    continue
                for row in rows:
                    db.execute(text(INSERT_SQL), row)
                db.commit()
                inserted += len(rows)
                print(f"  {match_id}: {len(rows)} строк")

        if args.dry_run:
            print("dry-run: ничего не записано")
            return 0

        games_with_draft = db.execute(
            text(
                "SELECT count(DISTINCT game_id) FROM picks_bans"
            )
        ).scalar()
        print(
            f"записано строк: {inserted}; игр с драфтом в БД: {games_with_draft}; "
            f"пропущено: {len(skipped)}; ошибок: {len(errors)}"
        )
        for match_id, reason in errors:
            print(f"  ERROR {match_id}: {reason}", file=sys.stderr)
        for match_id, reason in skipped[:5]:
            print(f"  нет драфта {match_id}: {reason}")
        if len(skipped) > 5:
            print(f"  ... и ещё {len(skipped) - 5} без драфта в источнике")
        if rate_limited:
            print(
                f"rate-limit источника — остановлено: {rate_limited}. "
                "Продолжить позже тем же запуском (уже собранное пропускается).",
                file=sys.stderr,
            )
            return 5
        return 1 if errors else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
