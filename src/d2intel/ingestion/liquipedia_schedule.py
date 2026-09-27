"""Liquipedia — display-only источник расписания (ADR-008).

Данные матчей Liquipedia live только в rendered HTML (`action=parse&prop=text`):
wikitext-шаблоны `{{Match}}` — пустые плейсхолдеры, реальный контент хранится в
Match-сторе LP. Парсер работает по стабильной LP2-разметке
(`brkts-matchlist-match` строки: имена команд в `data-team-name`, время в
`data-timestamp`, счёт и формат в popup-заголовке).

Правила ADR-008 (обязательны):
- display-only: данные не входят в critical path модели;
- attribution CC BY-SA 3.0 рядом с данными;
- UA с контактом, интервал между запросами к Liquipedia >= 2 c;
- кэш на диске (artifacts/cache) с TTL; отказ источника -> честная ошибка,
  ручное расписание продолжает работать.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

LIQUIPEDIA_API = "https://liquipedia.net/dota2/api.php"
USER_AGENT = "d2intel/0.1 (local research tool; contact: zetkaruss@gmail.com)"
MIN_REQUEST_INTERVAL_SECONDS = 2.0
ATTRIBUTION = "Источник данных: Liquipedia (CC BY-SA 3.0)"
DEFAULT_TTL_HOURS = 6
#: Подстраницы турнира, в которых бывают матчи (относительно титула турнира).
DEFAULT_SUBPAGES = ("", "/Group Stage", "/Playoffs", "/Bracket")

_MATCH_ROW_MARKER = '<div class="brkts-matchlist-match'
_TEAM_NAME_RE = re.compile(r'data-team-name="([^"]+)"')
_TIMESTAMP_RE = re.compile(r'data-timestamp="(\d+)"')
_FINISHED_MARK = 'data-finished="finished"'
_SCORE_RE = re.compile(r'match-info-header-scoreholder-score[^>]*>(\d+)</span>')
_BESTOF_RE = re.compile(r"\(Bo(\d+)\)")
_TIMER_TEXT_RE = re.compile(r'<span class="timer-object[^"]*"[^>]*>([^<]+)</span>')


def fetch_page_html(session: httpx.Client | None, page: str) -> str:
    """Rendered HTML страницы Liquipedia (через api.php, с rate-limit дисциплиной)."""
    client = session or httpx.Client()
    response = client.get(
        LIQUIPEDIA_API,
        params={
            "action": "parse",
            "page": page,
            "prop": "text",
            "format": "json",
            "formatversion": 2,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise ValueError(f"Liquipedia: {body['error'].get('info', 'unknown error')}")
    return body["parse"]["text"]


def parse_matches_from_html(html: str, *, source_page: str) -> list[dict[str, Any]]:
    """Извлечь матчи из rendered HTML списка матчей LP2.

    Возвращает записи вида {teams, started_at, bestof, finished, score_a,
    score_b, winner, source_page}. Порядок полей в строке надёжен: первые два
    уникальных `data-team-name` — Team 1 и Team 2.
    """
    matches: list[dict[str, Any]] = []
    row_starts = [m.start() for m in re.finditer(re.escape(_MATCH_ROW_MARKER), html)]
    for index, start in enumerate(row_starts):
        end = row_starts[index + 1] if index + 1 < len(row_starts) else len(html)
        row = html[start:end]
        teams: list[str] = []
        for name in _TEAM_NAME_RE.findall(row):
            if name not in teams:
                teams.append(name)
        if len(teams) < 2:
            continue  # TBD/пустые плейсхолдеры — не матч
        timestamp = _TIMESTAMP_RE.search(row)
        scores = _SCORE_RE.findall(row)
        bestof = _BESTOF_RE.search(row)
        finished = _FINISHED_MARK in row
        timer_text = _TIMER_TEXT_RE.search(row)
        winner = None
        if finished and len(scores) >= 2 and teams:
            winner = (
                teams[0] if int(scores[0]) > int(scores[1]) else teams[1]
            ) if scores[0] != scores[1] else None
        matches.append(
            {
                "teams": teams[:2],
                "started_at": (
                    datetime.fromtimestamp(int(timestamp.group(1)), tz=UTC).isoformat()
                    if timestamp
                    else None
                ),
                "started_at_label": timer_text.group(1) if timer_text else None,
                "bestof": int(bestof.group(1)) if bestof else None,
                "finished": finished,
                "score": scores[:2] or None,
                "winner": winner,
                "source_page": source_page,
            }
        )
    return matches



# --------------------------------------------------------------------------- #
# Портал «Liquipedia:Matches» — расписание всех турниров (match-info блоки)
# ---------------------------------------------------------------------------

_TICKER_ROW_MARKER = "<div class=\"match-info\">"
_TICKER_TEAM_RE = re.compile(r'<a href="/dota2/[^"]*" title="([^"]+)"')
_TICKER_TOURNAMENT_RE = re.compile(
    r'match-info-tournament-name"><a href="[^"]*" title="[^"]*">\s*<span>([^<]+)</span>'
)
_REDLINK_SUFFIX = " (page does not exist)"


def parse_ticker_matches(html: str) -> list[dict[str, Any]]:
    """Матчи портала Liquipedia:Matches — все турниры, upcoming + completed.

    У предстоящих матчей спаны счёта пустые → score None, finished False.
    Имя турнира берётся из `match-info-tournament-name`.
    """
    matches: list[dict[str, Any]] = []
    starts = [m.start() for m in re.finditer(re.escape(_TICKER_ROW_MARKER), html)]
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(html)
        block = html[start:end]
        opponents: list[str] = []
        for part in block.split("match-info-header-opponent")[1:]:
            team_match = _TICKER_TEAM_RE.search(part)
            if team_match:
                name = team_match.group(1)
                if name.endswith(_REDLINK_SUFFIX):
                    name = name[: -len(_REDLINK_SUFFIX)]
                opponents.append(name)
        if len(opponents) < 2:
            continue
        timestamp = _TIMESTAMP_RE.search(block)
        scores = _SCORE_RE.findall(block)
        bestof = _BESTOF_RE.search(block)
        tournament = _TICKER_TOURNAMENT_RE.search(block)
        score_pair = scores[:2] if len(scores) >= 2 else None
        winner = None
        if score_pair and score_pair[0] != score_pair[1]:
            winner = opponents[0] if int(score_pair[0]) > int(score_pair[1]) else opponents[1]
        matches.append(
            {
                "teams": opponents[:2],
                "started_at": (
                    datetime.fromtimestamp(int(timestamp.group(1)), tz=UTC).isoformat()
                    if timestamp
                    else None
                ),
                "bestof": int(bestof.group(1)) if bestof else None,
                "finished": score_pair is not None,
                "score": score_pair,
                "winner": winner,
                "tournament": tournament.group(1) if tournament else None,
                "source_page": "Liquipedia:Matches",
            }
        )
    return matches


def refresh_matches_portal(
    cache_path: Path,
    *,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    force: bool = False,
    client: httpx.Client | None = None,
    page: str = "Liquipedia:Matches",
) -> dict[str, Any]:
    """Кэшированная выборка портала матчей всех турниров (ADR-008)."""
    cache = load_cached(cache_path)
    if not force and cache is not None and cache_is_fresh(cache, ttl_hours):
        return {**cache, "attribution": ATTRIBUTION, "cache": "fresh"}

    owned_client = client is None
    client = client or httpx.Client()
    try:
        html = fetch_page_html(client, page)
    finally:
        if owned_client:
            client.close()
    payload = {
        "page": page,
        "fetched_at": datetime.now(UTC).isoformat(),
        "matches": parse_ticker_matches(html),
        "pages_fetched": [page],
        "page_errors": [],
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {**payload, "attribution": ATTRIBUTION, "cache": "refreshed"}
def load_cached(cache_path: Path) -> dict[str, Any] | None:
    """Кэш: {fetched_at, page, matches}. Отсутствует — None."""
    if not cache_path.exists():
        return None
    return json.loads(cache_path.read_text(encoding="utf-8"))


def cache_is_fresh(cache: dict[str, Any] | None, ttl_hours: float) -> bool:
    if not cache:
        return False
    fetched = datetime.fromisoformat(cache["fetched_at"])
    return (datetime.now(UTC) - fetched).total_seconds() < ttl_hours * 3600


def refresh_schedule(
    page: str,
    cache_path: Path,
    *,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    force: bool = False,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Собрать расписание турнира с кэшем TTL и attribution (ADR-008).

    Подстраницы опрашиваются с интервалом >= 2 c (rate-limit LP). Уже
    существующий свежий кэш возвращается без сети, если не `force`.
    """
    cache = load_cached(cache_path)
    if not force and cache is not None and cache_is_fresh(cache, ttl_hours):
        return {**cache, "attribution": ATTRIBUTION, "cache": "fresh"}

    owned_client = client is None
    client = client or httpx.Client()
    matches: list[dict[str, Any]] = []
    fetched_pages: list[str] = []
    errors: list[str] = []
    try:
        for subpage in DEFAULT_SUBPAGES:
            full_page = f"{page}{subpage}"
            try:
                html = fetch_page_html(client, full_page)
            except ValueError as exc:
                errors.append(str(exc))  # подстраница ещё не создана — норма
                continue
            fetched_pages.append(full_page)
            matches.extend(parse_matches_from_html(html, source_page=full_page))
            if subpage != DEFAULT_SUBPAGES[-1]:
                time.sleep(MIN_REQUEST_INTERVAL_SECONDS)
    finally:
        if owned_client:
            client.close()

    payload = {
        "page": page,
        "fetched_at": datetime.now(UTC).isoformat(),
        "matches": matches,
        "pages_fetched": fetched_pages,
        "page_errors": errors,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {**payload, "attribution": ATTRIBUTION, "cache": "refreshed"}
