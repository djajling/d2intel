#!/usr/bin/env python
"""Закрытие серий по внешнему подтверждению Liquipedia (решение владельца 2026-09-27).

Проблема. `normalize/map_index.py` доказывает номера карт, только когда карт
ровно `best_of`. Для bo5, завершённой 3:0 или 3:1, это недостижимо из одного
OpenDota: карт физически три или четыре, «недостающие» не появятся никогда.
Такие серии висят `incomplete`, `game.map_number` остаётся NULL, и вердикт по
заморозке не сходится никогда — в частности по первому сбывшемуся прогнозу
`8987f801` (Yandex — NaVi, bo5, Liquipedia: finished 3:0).

Что делает скрипт. Берёт у портала Liquipedia (источник уже принят ADR-008
для расписания) **завершённые** матчи со счётом и, если число карт серии в
БД равно сумме счёта, признаёт серию полной: проставляет `map_number` по
порядку старта карт (1..N), `game.status = completed`, `series.status =
completed` и пишет provenance решения в `series.closure_evidence`.

Чего скрипт НЕ делает: не выдумывает недостающие карты, не доверяет счёту
без проверок, не трогает неизменяемые снимки. Расхождение счёта с нашими
победами, несовпадение команд или формата — честный `skipped`, а не закрытие.

Идемпотентен: трогает только карты с `map_number IS NULL` и серии со
статусом, отличным от `completed`.

Примеры:

    python scripts/close_finished_series.py --dry-run
    python scripts/close_finished_series.py --refresh
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

from d2intel.db import SessionLocal

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = REPO_ROOT / "artifacts" / "cache" / "liquipedia_matches_portal.json"

#: Окно, в котором серия считается «той же»: дата старта из портала против
#: времени серии в БД. Широкое специально — время в портале может быть
#: временем слота, а не первой карты.
MATCH_WINDOW = timedelta(hours=24)

CANDIDATE_SERIES_SQL = """
    SELECT DISTINCT s.id, s.best_of, s.status, s.event_time
    FROM series s
    JOIN game g ON g.series_id = s.id
    WHERE g.map_number IS NULL
      AND g.status = 'map_index_unresolved'
      AND s.status <> 'completed'
      AND s.event_time >= :since
"""

GAMES_SQL = """
    SELECT g.id, g.event_time, t.canonical_name AS winner
    FROM game g
    LEFT JOIN team t ON t.id = g.winner_team_id
    WHERE g.series_id = :series_id
    ORDER BY g.event_time, g.provider_match_id
"""

TEAMS_SQL = """
    SELECT DISTINCT t.canonical_name
    FROM game_team gt
    JOIN team t ON t.id = gt.team_id
    WHERE gt.game_id IN (SELECT id FROM game WHERE series_id = :series_id)
"""


@dataclass(frozen=True)
class SeriesInfo:
    """Серия в координатах нашей БД."""

    series_id: str
    best_of: int | None
    status: str
    event_time: datetime | None
    teams: frozenset[str]
    games: tuple[tuple[str, datetime | None], ...]
    wins_by_team: dict[str, int]


@dataclass(frozen=True)
class ClosureDecision:
    """Решение по одной серии: закрывать или нет и почему."""

    closed: bool
    reason: str
    evidence: dict[str, Any] | None = None
    ordering: tuple[str, ...] = ()


def _norm(name: str | None) -> str:
    return (name or "").strip().lower()


def parse_score(score: Any) -> tuple[int, int] | None:
    """Счёт портала `['3', '0']` → (3, 0). None, если счёта нет или он битый."""
    if not isinstance(score, list | tuple) or len(score) != 2:
        return None
    try:
        return int(score[0]), int(score[1])
    except (TypeError, ValueError):
        return None


def decide_closure(
    match: dict[str, Any], info: SeriesInfo, *, observed_at: str | None
) -> ClosureDecision:
    """Можно ли признать серию полной по записи портала.

    Проверки идут от грубых к тонким; любое расхождение — честный отказ,
    потому что цена ошибки — неверный номер карты и, значит, неверный вердикт.
    """
    if not match.get("finished"):
        return ClosureDecision(False, "портал: матч не завершён")
    score = parse_score(match.get("score"))
    if score is None:
        return ClosureDecision(False, "портал: счёт отсутствует или непарный")

    teams = match.get("teams") or []
    if len(teams) != 2 or not all(teams):
        return ClosureDecision(False, "портал: не две команды")
    if frozenset(_norm(t) for t in teams) != frozenset(_norm(t) for t in info.teams):
        return ClosureDecision(
            False, f"команды не совпали: портал {sorted(teams)} против БД {sorted(info.teams)}"
        )

    best_of = match.get("bestof")
    if info.best_of is not None and best_of is not None and int(best_of) != int(info.best_of):
        return ClosureDecision(False, f"формат не совпал: портал Bo{best_of} против БД {info.best_of}")
    if info.best_of is not None and score[0] + score[1] > int(info.best_of):
        return ClosureDecision(False, f"сумма счёта {score} больше формата Bo{info.best_of}")

    if match.get("started_at") and info.event_time is not None:
        try:
            started = datetime.fromisoformat(str(match["started_at"]))
        except ValueError:
            started = None
        if started is not None:
            gap = abs((info.event_time - started).total_seconds())
            if gap > MATCH_WINDOW.total_seconds():
                return ClosureDecision(False, f"время старта разошлось на {int(gap // 3600)} ч")

    expected_games = score[0] + score[1]
    if len(info.games) != expected_games:
        return ClosureDecision(
            False, f"карт в БД {len(info.games)}, по счёту портала должно быть {expected_games}"
        )

    # Сверка победителя: счёт должен сходиться с числом побед в наших картах.
    winner = match.get("winner")
    if winner and info.wins_by_team:
        leader, leader_wins = max(
            info.wins_by_team.items(), key=lambda item: (item[1], item[0])
        )
        if _norm(leader) != _norm(winner):
            return ClosureDecision(
                False, f"победитель не сошёлся: портал {winner}, по картам БД {leader}"
            )
        if leader_wins != max(score):
            return ClosureDecision(
                False, f"побед в БД {leader_wins}, по счёту портала {max(score)}"
            )

    ordering = tuple(
        game_id for game_id, _ in sorted(info.games, key=lambda item: (item[1] or datetime.min.replace(tzinfo=UTC), item[0]))
    )
    evidence = {
        "source": "liquipedia:matches",
        "finished": True,
        "score": [score[0], score[1]],
        "bestof": best_of,
        "winner": winner,
        "teams": list(teams),
        # Почему считаем серию полной: карт в БД ровно столько, сколько в счёте.
        "rule": "games_in_db == sum(score) — «недостающие» карты не существуют",
        "observed_at": observed_at,
        "assigned_at": datetime.now(UTC).isoformat(),
    }
    return ClosureDecision(True, "серия закрыта по подтверждению портала", evidence, ordering)


def load_portal(cache_path: Path, *, refresh: bool) -> dict[str, Any]:
    """Портал из кэша, при `--refresh` — с перезабором."""
    if refresh:
        import httpx

        from d2intel.ingestion.liquipedia_schedule import refresh_matches_portal

        return refresh_matches_portal(cache_path, force=True, client=httpx.Client())
    if not cache_path.exists():
        raise SystemExit(f"кэш портала не найден: {cache_path} (запустите с --refresh)")
    return json.loads(cache_path.read_text(encoding="utf-8"))


def collect_candidates(session: Any, *, since_days: int) -> list[SeriesInfo]:
    """Серии с недоказанными номерами карт за последние N дней."""
    since = datetime.now(UTC) - timedelta(days=since_days)
    rows = session.execute(text(CANDIDATE_SERIES_SQL), {"since": since}).all()
    result: list[SeriesInfo] = []
    for row in rows:
        game_rows = session.execute(text(GAMES_SQL), {"series_id": row.id}).all()
        games = [(str(game_id), event_time) for game_id, event_time, _ in game_rows]
        teams = frozenset(
            name
            for (name,) in session.execute(text(TEAMS_SQL), {"series_id": row.id}).all()
            if name
        )
        wins: dict[str, int] = {}
        for _, _, winner in game_rows:
            if winner:
                wins[winner] = wins.get(winner, 0) + 1
        result.append(
            SeriesInfo(
                series_id=str(row.id),
                best_of=row.best_of,
                status=row.status,
                event_time=row.event_time,
                teams=teams,
                games=tuple(games),
                wins_by_team=wins,
            )
        )
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Закрытие серий и доказательство номеров карт по счёту Liquipedia."
    )
    parser.add_argument("--dry-run", action="store_true", help="Только посчитать, не писать.")
    parser.add_argument("--refresh", action="store_true", help="Перезабрать портал Liquipedia.")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="Путь к кэшу портала.")
    parser.add_argument(
        "--since-days", type=int, default=7, help="Глубина поиска незакрытых серий в днях."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    portal = load_portal(args.cache, refresh=args.refresh)
    observed_at = portal.get("fetched_at")
    finished_matches = [m for m in portal.get("matches", []) if m.get("finished")]

    session = SessionLocal()
    closed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    try:
        candidates = collect_candidates(session, since_days=args.since_days)
        for info in candidates:
            # Причина для отчёта: если пара команд вообще не нашлась в портале,
            # сообщать «команды не совпали» про последний из 50 матчей — врать.
            # Берём первую причину от матча с той же парой, иначе — общую.
            decisions = [decide_closure(match, info, observed_at=observed_at) for match in finished_matches]
            closed_decision = next((item for item in decisions if item.closed), None)
            reason = "в портале нет завершённого матча с такой парой команд"
            for item in decisions:
                if not item.reason.startswith("команды не совпали"):
                    reason = item.reason
                    break
            if closed_decision is None:
                skipped.append(
                    {
                        "series_id": info.series_id,
                        "teams": sorted(info.teams),
                        "best_of": info.best_of,
                        "games": len(info.games),
                        "reason": reason,
                    }
                )
                continue
            decision = closed_decision

            assert decision.evidence is not None
            if not args.dry_run:
                for index, game_id in enumerate(decision.ordering, start=1):
                    session.execute(
                        text(
                            "UPDATE game SET map_number = :map_number, status = 'completed' "
                            "WHERE id = :id AND map_number IS NULL"
                        ),
                        {"map_number": index, "id": game_id},
                    )
                session.execute(
                    text(
                        "UPDATE series SET status = 'completed', closure_evidence = CAST(:evidence AS jsonb) "
                        "WHERE id = :id"
                    ),
                    {"evidence": json.dumps(decision.evidence, ensure_ascii=False), "id": info.series_id},
                )
            closed.append(
                {
                    "series_id": info.series_id,
                    "teams": sorted(info.teams),
                    "best_of": info.best_of,
                    "maps_assigned": len(decision.ordering),
                    "score": decision.evidence["score"],
                }
            )
        if not args.dry_run:
            session.commit()
    finally:
        session.close()

    print(
        json.dumps(
            {
                "dry_run": args.dry_run,
                "portal_finished_matches": len(finished_matches),
                "candidates": len(candidates),
                "closed": closed,
                "skipped": skipped,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
