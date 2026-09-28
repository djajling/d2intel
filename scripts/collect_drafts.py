#!/usr/bin/env python
"""Сбор полного драфта (picks_bans) доигранных карт в draft_observed.

Учебные данные для Gate-2 (ADR-006/ADR-007): целевая переменная — исход первой
карты, но карты серии не выбрасываем — владельцу нужен полный материал. Поэтому
в `scheduled_match.draft_observed.maps` кладётся драфт КАЖДОЙ доигранной карты
с пометкой `map_number`, когда номер карты доказан, и `null` + явным статусом,
когда не доказан. Номер карты не придумывается: правило репозиториума про
map index остаётся в силе (см. prospective_reconcile.py).

Источник — OpenDota `/api/matches/{provider_match_id}` (уже используемый
провайдер, новый внешний источник не вводится → ADR на него не нужен).
`game.provider_match_id` берётся из канонической таблицы `game`.

Гарантии:

* ничего не перетирается: существующие ключи draft_observed (включая
  ручной ввод `draft`/`match_id`/`radiant_win`) сохраняются, добавляется
  только `maps`/`source`/`collected_at`;
* «нет данных» не подменяется пустым списком: если у матча в источнике нет
  picks_bans — `draft` остаётся null с `draft_status = absent_in_source`;
* если имя героя неизвестно — `hero` остаётся null, `hero_id` сохраняется;
* запись идёт только для доигранных игр с доказанным победителем.

Пример:

    python scripts/collect_drafts.py --all
    python scripts/collect_drafts.py --fixture-id <uuid>

Коды возврата: 0 собрано/нечего собирать, 1 были ошибки запроса к источнику,
3 фикстура не найдена, 64 bad args.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.db import SessionLocal
from d2intel.ingestion.live_draft import USER_AGENT, load_hero_names

FREEZE_DIR = Path("artifacts/prospective")
MATCH_URL = "https://api.opendota.com/api/matches/{match_id}"

#: Пауза между запросами тяжёлых /matches/{id} (бесплатный тир OpenDota).
FETCH_INTERVAL_SECONDS = 1.0

SOURCE_LABEL = "opendota_matches_api"

#: Игры между теми же командами после cutoff, которые доиграны.
#:
#: «Доиграна» определяется по winner_team_id, а НЕ по status: в БД два статуса —
#: `completed` и `map_index_unresolved` (8 826 игр), и у обоих победитель уже
#: есть. Второй означает лишь то, что номер карты не доказан, пока серия не
#: закрыта. Отбор по status='completed' молча выбросил бы большинство свежих
#: карт — то самое подменение «нет данных» фильтром.
CANDIDATE_SQL = """
    SELECT
        g.id AS game_id,
        g.map_number AS map_number,
        g.status AS status,
        g.provider_match_id AS provider_match_id,
        g.event_time AS event_time,
        g.winner_team_id AS winner_team_id
    FROM game AS g
    JOIN game_team AS gta ON gta.game_id = g.id AND gta.slot = 0
    JOIN game_team AS gtb ON gtb.game_id = g.id AND gtb.slot = 1
    WHERE g.provider_match_id IS NOT NULL
      AND g.winner_team_id IS NOT NULL
      AND g.event_time IS NOT NULL
      AND g.event_time >= CAST(:cutoff AS timestamptz)
      AND gta.team_id IN (CAST(:team_a AS uuid), CAST(:team_b AS uuid))
      AND gtb.team_id IN (CAST(:team_a AS uuid), CAST(:team_b AS uuid))
      AND gta.team_id <> gtb.team_id
    ORDER BY g.event_time
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Собрать picks_bans доигранных карт в draft_observed."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Все фикстуры с freeze_id.")
    group.add_argument("--fixture-id", help="Конкретная фикстура schedule.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать, что было бы собрано, без записи в БД (запросы к источнику идут).",
    )
    return parser.parse_args(argv)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _load_freeze_context(freeze_id: str) -> dict[str, Any] | None:
    """team_a/team_b/cutoff из immutable-артефакта заморозки."""
    path = FREEZE_DIR / f"{freeze_id}.json"
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        freeze = json.load(handle)
    return {
        "team_a_id": str(freeze["team_a"]["id"]),
        "team_b_id": str(freeze["team_b"]["id"]),
        "cutoff": datetime.fromisoformat(str(freeze["cutoff_at"])),
        "cutoff_source": "freeze_cutoff",
    }


def _load_schedule_context(db: Session, fixture_id: str, freeze_id: str | None) -> dict[str, Any] | None:
    """Фоллбек: team id по каноническому имени, cutoff = время старта фикстуры."""
    if not freeze_id:
        return None
    row = db.execute(
        text("SELECT team_a_label, team_b_label, scheduled_at FROM scheduled_match WHERE id = CAST(:id AS uuid)"),
        {"id": fixture_id},
    ).first()
    if row is None:
        return None
    teams = []
    for label in (row.team_a_label, row.team_b_label):
        team = db.execute(
            text("SELECT id FROM team WHERE lower(canonical_name) = lower(:label) LIMIT 1"),
            {"label": label},
        ).first()
        if team is None:
            return None
        teams.append(str(team.id))
    if row.scheduled_at is None:
        return None
    return {
        "team_a_id": teams[0],
        "team_b_id": teams[1],
        "cutoff": row.scheduled_at,
        "cutoff_source": "fixture_scheduled_at",
    }


def _fetch_match_detail(match_id: str, client: httpx.Client) -> dict[str, Any]:
    response = client.get(
        MATCH_URL.format(match_id=match_id),
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    if response.status_code == 404:
        return {}
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code} для {match_id}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"не-объект ответ для {match_id}")
    return payload


def build_map_entry(
    *,
    game: dict[str, Any],
    payload: dict[str, Any],
    hero_names: dict[int, str],
    cutoff_source: str,
) -> dict[str, Any]:
    """Одна доигранная карта -> запись в draft_observed.maps.

    `map_number` берётся из канонической игры; если он не доказан — null со
    статусом `unresolved`, а не угаданный по порядку в серии.
    """
    raw_picks = payload.get("picks_bans")
    picks: list[dict[str, Any]] | None
    if isinstance(raw_picks, list) and raw_picks:
        picks = []
        for row in raw_picks:
            hero_id = row.get("hero_id")
            picks.append(
                {
                    "hero": hero_names.get(int(hero_id)) if isinstance(hero_id, int) else None,
                    "hero_id": hero_id,
                    # Конвенция OpenDota, сверенная с ручным вводом владельца:
                    # team 0 = radiant, 1 = dire (см. live_draft._side_name).
                    "team": "radiant" if row.get("team") == 0 else "dire",
                    "order": row.get("order"),
                    "is_pick": row.get("is_pick"),
                }
            )
    else:
        picks = None

    map_number = game.get("map_number")
    return {
        "match_id": str(game.get("provider_match_id")),
        "game_id": str(game.get("game_id")),
        "map_number": int(map_number) if isinstance(map_number, int) else None,
        "map_number_status": "proven" if isinstance(map_number, int) else "unresolved",
        "game_status": game.get("status"),
        "event_time": _iso(game.get("event_time")),
        "radiant_win": payload.get("radiant_win"),
        "duration": payload.get("duration"),
        "league_id": payload.get("leagueid"),
        "opendota_series_id": payload.get("series_id"),
        "cutoff_source": cutoff_source,
        "draft_status": "ok" if picks else "absent_in_source",
        "draft": picks,
    }


def merge_maps(existing: dict[str, Any], entries: list[dict[str, Any]]) -> dict[str, Any]:
    """Добавить/обновить записи в existing, не трогая чужие ключи.

    Ручной ввод владельца (`draft`, `match_id`, `radiant_win`) остаётся на месте:
    перезапись учебных данных, которые человек занёс руками, недопустима.
    """
    result = dict(existing)
    by_match: dict[str, dict[str, Any]] = {
        str(item.get("match_id")): dict(item)
        for item in (result.get("maps") or [])
        if isinstance(item, dict) and item.get("match_id") is not None
    }
    for entry in entries:
        by_match[str(entry["match_id"])] = entry
    merged = sorted(
        by_match.values(),
        key=lambda item: (item.get("event_time") or "", str(item.get("match_id"))),
    )
    result["maps"] = merged
    result["source"] = SOURCE_LABEL
    result["collected_at"] = datetime.now(UTC).isoformat()
    result["map_note"] = (
        "map_number берётся из канонической игры; null + map_number_status=unresolved "
        "означает, что номер карты не доказан — такие записи в пары Gate-2 не идут."
    )
    return result


def _process_fixture(db: Session, fixture_id: str, *, dry_run: bool) -> dict[str, Any]:
    row = db.execute(
        text(
            "SELECT id, freeze_id, team_a_label, team_b_label FROM scheduled_match "
            "WHERE id = CAST(:id AS uuid)"
        ),
        {"id": fixture_id},
    ).first()
    if row is None:
        raise LookupError(fixture_id)

    report: dict[str, Any] = {"fixture": fixture_id, "fetched": [], "skipped": [], "errors": []}

    context = _load_freeze_context(str(row.freeze_id)) if row.freeze_id else None
    if context is None:
        context = _load_schedule_context(db, fixture_id, str(row.freeze_id) if row.freeze_id else None)
    if context is None:
        report["skipped"].append("нет freeze-артефакта и не разрешены team id — пропущено")
        return report

    games = [
        dict(game._mapping)
        for game in db.execute(
            text(CANDIDATE_SQL),
            {
                "team_a": context["team_a_id"],
                "team_b": context["team_b_id"],
                "cutoff": context["cutoff"],
            },
        ).all()
    ]
    if not games:
        report["skipped"].append("доигранных карт между этими командами после cutoff нет")
        return report

    existing_row = db.execute(
        text("SELECT draft_observed FROM scheduled_match WHERE id = CAST(:id AS uuid)"),
        {"id": fixture_id},
    ).first()
    existing = existing_row.draft_observed or {}
    if not isinstance(existing, dict):
        existing = {}
    already = {
        str(item.get("match_id"))
        for item in (existing.get("maps") or [])
        if isinstance(item, dict)
    }

    hero_names = load_hero_names()
    entries: list[dict[str, Any]] = []
    with httpx.Client() as client:
        for index, game in enumerate(games):
            match_id = str(game["provider_match_id"])
            if match_id in already:
                report["skipped"].append(f"{match_id}: уже собрана")
                continue
            if index:
                time.sleep(FETCH_INTERVAL_SECONDS)
            try:
                payload = _fetch_match_detail(match_id, client)
            except (httpx.HTTPError, RuntimeError) as exc:
                report["errors"].append(f"{match_id}: {exc}")
                continue
            if not payload:
                report["errors"].append(f"{match_id}: 404 в источнике")
                continue
            entries.append(
                build_map_entry(
                    game=game,
                    payload=payload,
                    hero_names=hero_names,
                    cutoff_source=str(context["cutoff_source"]),
                )
            )
            report["fetched"].append(match_id)

    if not entries or dry_run:
        if entries:
            report["skipped"].append(f"dry-run: записано было бы {len(entries)} карт")
        return report

    updated = merge_maps(existing, entries)
    db.execute(
        text(
            "UPDATE scheduled_match SET draft_observed = CAST(:draft AS json), "
            "updated_at = now() WHERE id = CAST(:id AS uuid)"
        ),
        {"draft": json.dumps(updated, ensure_ascii=False), "id": fixture_id},
    )
    db.commit()
    return report


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    db = SessionLocal()
    try:
        if args.fixture_id:
            rows = [args.fixture_id]
        else:
            rows = [
                str(r.id)
                for r in db.execute(
                    text("SELECT id FROM scheduled_match WHERE freeze_id IS NOT NULL ORDER BY scheduled_at")
                ).all()
            ]
        if not rows:
            print("no fixtures with freeze_id")
            return 0

        failures = 0
        for fixture_id in rows:
            try:
                report = _process_fixture(db, fixture_id, dry_run=args.dry_run)
            except LookupError:
                print(f"fixture not found: {fixture_id}", file=sys.stderr)
                return 3
            print(f"fixture {fixture_id}")
            for match_id in report["fetched"]:
                print(f"  collected {match_id}")
            for note in report["skipped"]:
                print(f"  skip {note}")
            for note in report["errors"]:
                print(f"  ERROR {note}", file=sys.stderr)
            failures += len(report["errors"])
        return 1 if failures else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
