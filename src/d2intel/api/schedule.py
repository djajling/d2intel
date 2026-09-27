"""Расписание турниров и матчей — ручной ввод владельца + freeze по фикстуре.

Легального автоматического источника расписаний не существует (вердикт
SRC-002), поэтому фикстуры вводятся владельцем вручную (турнир, команды,
время) и живут в `scheduled_match` (миграция 0004). Это операционный список
для prospective-контура, не evidence-данные.

Действия над фикстурой:

- `POST /api/schedule/{id}/freeze` — запускает проверенный CLI
  `scripts/prospective_freeze.py` (LR champion, cutoff = now, immutable
  файл в artifacts/prospective) и связывает freeze_id с фикстурой. Ошибки
  резолва команд/модели возвращаются честно, статус не меняется.
- `POST /api/schedule/{id}/draft` — сохраняет НАБЛЮДАЕМЫЙ драфт (введён
  владельцем с трансляции) как данные для Gate-2 (ADR-006). Текущая модель
  драфт-информированной НЕ является: поле — сбор данных, а не вход прогноза,
  что явно отражено в ответе.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.db import get_db
from d2intel.ingestion.liquipedia_schedule import (
    refresh_matches_portal,
    refresh_schedule,
)
from d2intel.ingestion.live_draft import live_match_view, load_hero_names

router = APIRouter(prefix="/api/schedule", tags=["schedule"])

REPO_ROOT = Path(__file__).resolve().parents[3]  # (уже определён ниже — оставить один)
DEFAULT_LIQUIPEDIA_PAGE = "BLAST/SLAM/8"
#: Какой турнир автоцикл считает «своим» (решение владельца 2026-09-27:
#: Wallachia S9 закрыт 27.09, следующий целевой турнир — BLAST Slam VIII,
#: матчи 29–30.09).
#: Сравнение по подстроке без регистра: портал отдаёт названия вида
#: «BLAST SLAM VIII - Group B». Имя страницы проверено через Liquipedia API
#: (BLAST/SLAM/8 — есть, 8 матчей; BLAST/Slam/VIII — не существует).
TOURNAMENT_FILTER = "blast slam viii"
CACHE_DIR = Path("artifacts/cache")

REPO_ROOT = Path(__file__).resolve().parents[3]
FREEZE_SCRIPT = REPO_ROOT / "scripts" / "prospective_freeze.py"
FREEZE_TIMEOUT_SECONDS = 300

_SCHEDULE_SQL = """
    SELECT
        id, tournament_label, team_a_label, team_b_label, stage_label,
        scheduled_at, status, freeze_id, draft_observed, notes, created_at, updated_at
    FROM scheduled_match
"""

def notify_telegram(text: str) -> bool:
    """Push в Telegram владельца (ключ/чат в .env, в git не попадают)."""
    import os

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        env_path = REPO_ROOT / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    token = line.split("=", 1)[1].strip()
                elif line.startswith("TELEGRAM_CHAT_ID="):
                    chat_id = line.split("=", 1)[1].strip()
    if not token or not chat_id:
        return False
    try:
        import httpx as _httpx

        response = _httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": int(chat_id), "text": text},
            timeout=15,
        )
        return response.status_code == 200
    except Exception:  # noqa: BLE001 — push не должен ломать основной поток
        return False


_DRAFT_NOTE = (
    "Драфт сохранён как наблюдение для будущего Gate-2 (ADR-006): текущая "
    "модель драфт-информированной не является, прогноз от этого не меняется."
)


class ScheduleCreate(BaseModel):
    """Ручной ввод фикстуры владельцем."""

    tournament_label: str = Field(min_length=1, max_length=200)
    team_a_label: str = Field(min_length=1, max_length=100)
    team_b_label: str = Field(min_length=1, max_length=100)
    stage_label: str | None = Field(default=None, max_length=200)
    scheduled_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)


class DraftObservation(BaseModel):
    """Наблюдаемый драфт (evidence для Gate-2), структура свободная."""

    draft: dict[str, Any]


def _row_dict(row: Any) -> dict[str, Any]:
    data = dict(row._mapping)
    for key in ("scheduled_at", "created_at", "updated_at"):
        if data.get(key) is not None:
            data[key] = data[key].isoformat()
    return data


def _load_row(db: Session, fixture_id: str) -> dict[str, Any]:
    row = db.execute(
        text(_SCHEDULE_SQL + " WHERE id = CAST(:id AS uuid)"), {"id": fixture_id}
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фикстура не найдена")
    return _row_dict(row)


@router.get("")
def list_schedule(
    status_filter: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict[str, Any]]:
    """Расписание: сначала предстоящие (по времени), затем остальные."""
    query = _SCHEDULE_SQL
    params: dict[str, Any] = {}
    if status_filter:
        query += " WHERE status = :status"
        params["status"] = status_filter
    query += " ORDER BY (status = 'upcoming') DESC, scheduled_at ASC NULLS LAST, created_at DESC"
    return [_row_dict(row) for row in db.execute(text(query), params).all()]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_fixture(payload: ScheduleCreate, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    """Добавить фикстуру вручную (ручной ввод — единственный честный путь)."""
    if payload.team_a_label.strip().lower() == payload.team_b_label.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Команды должны различаться"
        )
    row = db.execute(
        text(
            """
            INSERT INTO scheduled_match
                (tournament_label, team_a_label, team_b_label, stage_label,
                 scheduled_at, notes)
            VALUES
                (:tournament, :team_a, :team_b, :stage, :scheduled_at, :notes)
            RETURNING id
            """
        ),
        {
            "tournament": payload.tournament_label.strip(),
            "team_a": payload.team_a_label.strip(),
            "team_b": payload.team_b_label.strip(),
            "stage": payload.stage_label,
            "scheduled_at": payload.scheduled_at,
            "notes": payload.notes,
        },
    ).scalar_one()
    db.commit()
    return _load_row(db, str(row))


@router.delete("/{fixture_id}")
def delete_fixture(fixture_id: str, db: Session = Depends(get_db)) -> dict[str, str]:  # noqa: B008
    """Удалить фикстуру (локальный операционный список, не evidence)."""
    deleted = db.execute(
        text(
            "DELETE FROM scheduled_match WHERE id = CAST(:id AS uuid) "
            "RETURNING id"
        ),
        {"id": fixture_id},
    ).first()
    if deleted is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Фикстура не найдена")
    db.commit()
    return {"deleted": fixture_id}


@router.post("/{fixture_id}/freeze")
def freeze_fixture(fixture_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    """Заморозить prospective-прогноз по фикстуре (cutoff = now, immutable)."""
    fixture = _load_row(db, fixture_id)
    if fixture["status"] == "frozen":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Фикстура уже заморожена: freeze_id={fixture['freeze_id']}",
        )
    completed = subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(FREEZE_SCRIPT),
            "--team-a",
            str(fixture["team_a_label"]),
            "--team-b",
            str(fixture["team_b_label"]),
        ],
        capture_output=True,
        text=True,
        timeout=FREEZE_TIMEOUT_SECONDS,
        cwd=str(REPO_ROOT),
    )
    if completed.returncode != 0:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Заморозка не удалась: "
                f"{(completed.stderr or completed.stdout).strip()[-400:]}"
            ),
        )
    freeze_id = _parse_freeze_id(completed.stdout)
    if freeze_id is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Заморозка отработала, но freeze_id не найден в выводе",
        )
    db.execute(
        text(
            "UPDATE scheduled_match SET status = 'frozen', freeze_id = :freeze_id, "
            "updated_at = now() WHERE id = CAST(:id AS uuid)"
        ),
        {"freeze_id": freeze_id, "id": fixture_id},
    )
    db.commit()
    updated = _load_row(db, fixture_id)
    updated["freeze_output"] = completed.stdout.strip()
    return updated


def _parse_freeze_id(stdout: str) -> str | None:
    for line in stdout.splitlines():
        if line.startswith("frozen "):
            return line.split(maxsplit=1)[1].strip()
    return None


@router.get("/external")
def external_schedule(
    page: str = Query(default=DEFAULT_LIQUIPEDIA_PAGE, max_length=120),
    refresh: bool = Query(default=False),
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Расписание с Liquipedia (ADR-008, display-only, кэш TTL + attribution)."""
    del db  # внешний источник, БД не используется
    slug = page.replace("/", "_")
    cache_path = CACHE_DIR / f"liquipedia_schedule_{slug}.json"
    try:
        data = refresh_schedule(
            page,
            cache_path,
            force=refresh,
            client=httpx.Client(),
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Liquipedia недоступен ({exc}). Ручное расписание продолжает "
                "работать — добавьте фикстуру вручную."
            ),
        ) from exc
    return data


@router.get("/external/matches")
def external_matches_portal(
    refresh: bool = Query(default=False),
) -> dict[str, Any]:
    """Матчи ВСЕХ турниров с портала Liquipedia:Matches (ADR-008)."""
    cache_path = CACHE_DIR / "liquipedia_matches_portal.json"
    try:
        data = refresh_matches_portal(
            cache_path,
            force=refresh,
            client=httpx.Client(),
        )
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Liquipedia недоступен ({exc}). Ручное расписание работает.",
        ) from exc
    return data


@router.post("/auto-freeze")
def auto_freeze(db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    """Авто-заморозка (разрешение владельца 2026-09-27): портал → импорт → freeze.

    Идемпотентно и безопасно для повторных вызовов:
    1. Новые предстоящие матчи целевого турнира (`TOURNAMENT_FILTER`) с
       портала импортируются (без дублей по паре команд среди upcoming).
    2. Фикстуры, до старта которых осталось <= 10 минут, замораживаются
       (через тот же честный CLI; после старта — не замораживаются никогда).
    3. Фикстуры, чей старт прошёл без заморозки, помечаются `missed_start`
       вместо фальшивой заморозки.
    """
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    imported: list[dict[str, Any]] = []
    frozen: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    # 1. Портал: новые upcoming-матчи целевого турнира → импорт без дублей.
    cache_path = CACHE_DIR / "liquipedia_matches_portal.json"
    try:
        portal = refresh_matches_portal(cache_path, client=httpx.Client())
    except (httpx.HTTPError, ValueError, OSError) as exc:
        portal = {"matches": [], "page_errors": [str(exc)]}
    existing_labels = {
        (row[0].strip().lower(), row[1].strip().lower())
        for row in db.execute(
            text(
                "SELECT team_a_label, team_b_label FROM scheduled_match "
                "WHERE status IN ('upcoming', 'frozen', 'played')"
            )
        ).all()
    }
    for match in portal.get("matches", []):
        if match.get("finished"):
            continue
        if TOURNAMENT_FILTER not in (match.get("tournament") or "").lower():
            continue
        pair = (match["teams"][0].strip().lower(), match["teams"][1].strip().lower())
        if pair in existing_labels:
            continue
        row = db.execute(
            text(
                """
                INSERT INTO scheduled_match
                    (tournament_label, team_a_label, team_b_label, stage_label,
                     scheduled_at, notes)
                VALUES
                    (:tournament, :team_a, :team_b, :stage, :scheduled_at, :notes)
                RETURNING id
                """
            ),
            {
                "tournament": match.get("tournament") or "Liquipedia",
                "team_a": match["teams"][0],
                "team_b": match["teams"][1],
                "stage": f"Bo{match['bestof']}" if match.get("bestof") else None,
                "scheduled_at": (
                    datetime.fromisoformat(match["started_at"])
                    if match.get("started_at")
                    else None
                ),
                "notes": "auto-import from Liquipedia portal (auto-freeze)",
            },
        ).scalar_one()
        existing_labels.add(pair)
        imported.append({"id": str(row), "teams": f"{match['teams'][0]} vs {match['teams'][1]}"})
    db.commit()

    # 2. Freeze за 10 минут до старта; после старта — честный skipped.
    upcoming_rows = db.execute(
        text(
            "SELECT id, team_a_label, team_b_label, scheduled_at FROM scheduled_match "
            "WHERE status = 'upcoming' AND scheduled_at IS NOT NULL"
        )
    ).all()
    for row in upcoming_rows:
        start = row.scheduled_at
        if start.tzinfo is None:
            from datetime import UTC

            start = start.replace(tzinfo=UTC)
        label = f"{row.team_a_label} vs {row.team_b_label}"
        if now >= start:
            db.execute(
                text(
                    "UPDATE scheduled_match SET status = 'cancelled', notes = "
                    "COALESCE(notes || ' | ', '') || 'missed_start: старт прошёл без заморозки', "
                    "updated_at = now() WHERE id = CAST(:id AS uuid)"
                ),
                {"id": str(row.id)},
            )
            skipped.append({"teams": label, "reason": "старт уже прошёл — честная заморозка невозможна"})
            continue
        if start - now <= timedelta(minutes=10):
            try:
                result = freeze_fixture(str(row.id), db)
                frozen.append(
                    {
                        "teams": label,
                        "freeze_id": result.get("freeze_id"),
                        "start": start.isoformat(),
                    }
                )
            except HTTPException as exc:
                skipped.append({"teams": label, "reason": str(exc.detail)[:200]})
    db.commit()
    if imported or frozen:
        lines = []
        if imported:
            lines.append("Импортировано: " + "; ".join(i["teams"] for i in imported))
        for f_item in frozen:
            lines.append(
                f"Заморожено: {f_item['teams']} (freeze {str(f_item['freeze_id'])[:8]}, старт {f_item['start']})"
            )
        notify_telegram("d2intel:\n" + "\n".join(lines))
    return {
        "checked_at": now.isoformat(),
        "imported": imported,
        "frozen": frozen,
        "skipped": skipped,
        "portal_errors": portal.get("page_errors", []),
    }


def _stratz_key() -> str | None:
    """Ключ STRATZ из .env (в git не попадает)."""
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("STRATZ_API_KEY="):
            return line.split("=", 1)[1].strip() or None
    return None


class _StratzThrottled(ValueError):
    """Ожидаемая пауза по квоте free-tier. Показывать владельцу не нужно.

    Это не отказ источника: живой вид и так даёт OpenDota, а STRATZ по квоте
    доступен лишь эпизодически. Писать «STRATZ недоступен» при каждом опросе
    UI (каждые 10–15 с) значило бы врать о поломке.
    """


STRATZ_ENDPOINT = "https://api.stratz.com/graphql"
# Free-tier: «You cannot use more than 2 IP Addresses every 15 minutes» —
# фактически не более 2 запросов за окно 15 минут (403 + текст про
# освобождение слота). UI опрашивает live-draft каждые 10–15 с, поэтому без
# собственного троттлинга квота сгорает за минуту, а403 потом висит 15 минут.
# 8 минут между запросами → меньше 2 за окно с запасом.
STRATZ_MIN_INTERVAL_SECONDS = 8 * 60
STRATZ_COOLDOWN_SECONDS = 15 * 60

# Только поля, подтверждённые интроспекцией 2026-09-27
# (scripts/stratz_introspect.py): MatchLiveType, MatchLivePlayerType,
# MatchLivePlaybackDataType, MatchLivePickBanType. Старый запрос падал с 400:
# `slot` и `team` в схеме НЕТ — реальные имена `playerSlot` и `isRadiant`.
# У LeagueType/TeamType состав полей не проверен, поэтому вложенных выборок
# из них избегаем: лишний неподтверждённый алиас =400 = потерянный слот квоты.
#
# Пики и баны в live-схеме ЕСТЬ — но не на MatchLiveType, а во вложенном
# playbackData.pickBans (isPick/heroId/bannedHeroId/isRadiant/order).
# Ранний комментарий «банов в live-полях нет» опровергнут интроспекцией
# playbackData: на верхнем уровне их правда нет, но вложенный блок есть.
STRATZ_LIVE_QUERY = (
    "{ live { matches { matchId gameState gameTime leagueId "
    "radiantScore direScore "
    "players { heroId playerSlot isRadiant steamAccountId name } "
    "playbackData { pickBans { isPick heroId bannedHeroId isRadiant order } } } } }"
)

# Состояние квоты живёт в процессе (проект без Redis/Celery — ADR) и
# дополнительно на диске: сервер перезапускают часто, а после рестарта память
# пустая — сторож слепнеет и тратит слоты квоты, которых и так два на окно.
# Файл переживает рестарт: квота — внешний ресурс, а не состояние процесса.
# Время — wall clock (time.time), иначе отметки не переживают рестарт.
STRATZ_STATE_PATH = REPO_ROOT / "artifacts" / "cache" / "stratz_quota.json"

_STRATZ_STATE: dict[str, Any] = {
    "last_attempt_at": 0.0,
    "cooldown_until": 0.0,
}


def _stratz_load_state() -> None:
    """Поднять состояние квоты с диска; битый/отсутствующий файл — не беда.

    Отметку из будущего (скачок часов, перенос файла) отбрасываем: иначе
    сторож залипнет на паузе, которой в реальности нет.
    """
    try:
        raw = json.loads(STRATZ_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(raw, dict):
        return
    now = time.time()
    for key in ("last_attempt_at", "cooldown_until"):
        value = raw.get(key)
        if not isinstance(value, (int, float)):
            continue
        value = float(value)
        if value <= 0:
            continue
        if key == "last_attempt_at" and value > now:
            continue
        _STRATZ_STATE[key] = value


def _stratz_save_state() -> None:
    """Записать состояние квоты. Best-effort: отказ диска не ломает запрос —
    хуже потерять ответ UI, чем запись (сторож просто станет мягче)."""
    try:
        STRATZ_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = STRATZ_STATE_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(
                {key: float(value) for key, value in _STRATZ_STATE.items()},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        tmp_path.replace(STRATZ_STATE_PATH)
    except OSError:
        pass


def _stratz_reset_state() -> None:
    """Сброс состояния квоты (тесты): память и файл по текущему пути.

    Тесты подменяют STRATZ_STATE_PATH на tmp_path, поэтому реальный файл
    квоты прогон не обнуляет — иначе после каждого pytest сторож слеп.
    """
    _STRATZ_STATE["last_attempt_at"] = 0.0
    _STRATZ_STATE["cooldown_until"] = 0.0
    try:
        STRATZ_STATE_PATH.unlink(missing_ok=True)
    except OSError:
        pass


_stratz_load_state()


def _stratz_live_matches(*, client: httpx.Client) -> list[dict[str, Any]]:
    """Один запрос live-матчей STRATZ с троттлингом и честными ошибками.

    Квота учитывается до запроса: после 403 ставится пауза, между запросами —
    минимальный интервал. Тело не-200 ответа сохраняется в тексте ошибки:
    именно там живёт GraphQL `errors`, и раньше оно терялось в
    `raise_for_status()` — из-за этого причина400 была не видна.
    """
    key = _stratz_key()
    if key is None:
        raise _StratzThrottled("STRATZ_API_KEY не задан")

    now = time.time()
    cooldown_until = float(_STRATZ_STATE["cooldown_until"])
    if now < cooldown_until:
        raise _StratzThrottled(f"STRATZ: пауза по квоте ещё {int(cooldown_until - now)} с")
    last = float(_STRATZ_STATE["last_attempt_at"])
    if last and now - last < STRATZ_MIN_INTERVAL_SECONDS:
        raise _StratzThrottled(
            f"STRATZ: интервал {STRATZ_MIN_INTERVAL_SECONDS} с между запросами ещё не прошёл"
        )
    _STRATZ_STATE["last_attempt_at"] = now
    _stratz_save_state()

    try:
        response = client.post(
            STRATZ_ENDPOINT,
            json={"query": STRATZ_LIVE_QUERY},
            headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": "STRATZ_API",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        raise ValueError(f"STRATZ: сеть {type(exc).__name__}: {exc}") from exc

    if response.status_code == 403:
        _STRATZ_STATE["cooldown_until"] = now + STRATZ_COOLDOWN_SECONDS
        _stratz_save_state()
        raise ValueError(f"STRATZ rate-limit: {response.text[:200]}")
    if response.status_code != 200:
        raise ValueError(f"STRATZ HTTP {response.status_code}: {response.text[:300]}")
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise ValueError(f"STRATZ: не-JSON ответ: {response.text[:200]}") from exc

    errors = payload.get("errors") or []
    if errors:
        raise ValueError(
            "STRATZ GraphQL errors: " + json.dumps(errors, ensure_ascii=False)[:300]
        )
    matches = ((payload.get("data") or {}).get("live") or {}).get("matches")
    if matches is None:
        raise ValueError("STRATZ: data.live отсутствует в ответе")
    return matches


def _stratz_pick_live_match(
    *,
    accounts_a: set[int],
    accounts_b: set[int],
    label_a: str,
    label_b: str,
    client: httpx.Client,
) -> tuple[dict[str, Any], str, str] | None:
    """Наша живая игра в STRATZ: опознание строго по steamAccountId игроков.

    Возвращает (матч, имя radiant-стороны, имя dire-стороны) или None.
    Правило порога то же, что в OpenDota-пути: >=4 совпадений суммарно И обе
    стороны представлены. Совпадение по названиям команд не используется —
    оно слабее и ломается на смене сторон между картами; фоллбека по лиге нет.
    """
    matches = _stratz_live_matches(client=client)
    best: tuple[int, dict[str, Any]] | None = None
    for match in matches:
        ids = {p.get("steamAccountId") for p in match.get("players") or []}
        overlap = len((ids & accounts_a) | (ids & accounts_b))
        both_sides = bool(ids & accounts_a) and bool(ids & accounts_b)
        if overlap >= 4 and both_sides and (best is None or overlap > best[0]):
            best = (overlap, match)
    if best is None:
        return None
    match = best[1]
    radiant_ids = {
        p.get("steamAccountId")
        for p in match.get("players") or []
        if p.get("isRadiant")
    }
    hit_a = len(radiant_ids & accounts_a)
    hit_b = len(radiant_ids & accounts_b)
    if hit_a or hit_b:
        radiant_label, dire_label = (
            (label_a, label_b) if hit_a >= hit_b else (label_b, label_a)
        )
    else:
        # Сторону опознать не удалось — не присваиваем имена наугад.
        radiant_label, dire_label = "Radiant", "Dire"
    return match, radiant_label, dire_label


def _team_accounts(db: Session, label: str) -> set[int]:
    """Известные account_id игроков команды (roster evidence из нашей БД)."""
    rows = db.execute(
        text(
            """
            SELECT DISTINCT p.account_id
            FROM roster_membership rm
            JOIN team t ON t.id = rm.team_id
            JOIN player p ON p.id = rm.player_id
            WHERE t.canonical_name = :label AND p.account_id IS NOT NULL
            """
        ),
        {"label": label},
    ).scalars()
    return {int(a) for a in rows}


@router.get("/live-draft")
def live_draft_snapshot(db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    """Живой драфт для ближайшей замороженной фикстуры (ADR-008 фаза 2)."""
    row = db.execute(
        text(
            "SELECT team_a_label, team_b_label, tournament_label "
            "FROM scheduled_match "
            "WHERE status = 'frozen' ORDER BY scheduled_at ASC NULLS LAST LIMIT 1"
        )
    ).first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Нет замороженных фикстур для live-наблюдения",
        )
    accounts_a = _team_accounts(db, row.team_a_label)
    accounts_b = _team_accounts(db, row.team_b_label)

    # Приоритет 1: STRATZ (live-пики; квота free-tier ~2 запроса за 15 минут,
    # поэтому троттлинг тут норма, а не поломка источника).
    try:
        stratz_pick = _stratz_pick_live_match(
            accounts_a=accounts_a,
            accounts_b=accounts_b,
            label_a=row.team_a_label,
            label_b=row.team_b_label,
            client=httpx.Client(),
        )
    except _StratzThrottled:
        # Ожидаемая пауза: не трактуем как отказ и не пугаем владельца
        # ложной ошибкой при каждом опросе UI (каждые 10–15 с).
        stratz_pick, stratz_note = None, ""
    except (httpx.HTTPError, ValueError) as exc:
        # Реальная ошибка — тело ответа сохраняем: раньше оно терялось
        # в raise_for_status() и причина400 была не видна.
        stratz_pick, stratz_note = None, f"STRATZ недоступен: {str(exc)[:200]}. "
    else:
        stratz_note = ""

    if stratz_pick is not None:
        stratz_match, radiant_label, dire_label = stratz_pick
        hero_names = load_hero_names()
        radiant_players: list[dict[str, Any]] = []
        dire_players: list[dict[str, Any]] = []
        for player in stratz_match.get("players", []):
            hero_id = player.get("heroId")
            entry = {
                "name": player.get("name") or "—",
                "hero": hero_names.get(int(hero_id)) if hero_id else None,
                "team_tag": None,
            }
            (radiant_players if player.get("isRadiant") else dire_players).append(entry)

        # Live-баны: playbackData.pickBans, бан = isPick=false + bannedHeroId,
        # сторона = isRadiant, порядок хода = order. Поле может отсутствовать
        # (карта ещё в стадии пиков/источник не отдал) — тогда честный пустой
        # список, нулями не подменяем.
        pick_bans = ((stratz_match.get("playbackData") or {}).get("pickBans")) or []
        pick_bans = sorted(pick_bans, key=lambda m: m.get("order") or 0)
        radiant_bans: list[dict[str, Any]] = []
        dire_bans: list[dict[str, Any]] = []
        radiant_picks: list[int] = []
        dire_picks: list[int] = []
        for move in pick_bans:
            side_bans, side_picks = (
                (radiant_bans, radiant_picks)
                if move.get("isRadiant")
                else (dire_bans, dire_picks)
            )
            if move.get("isPick"):
                hero_id = move.get("heroId")
                if hero_id:
                    side_picks.append(int(hero_id))
            else:
                banned = move.get("bannedHeroId")
                if banned:
                    side_bans.append(
                        {"hero": hero_names.get(int(banned)), "order": move.get("order")}
                    )

        return {
            "found": True,
            "source": "stratz",
            # matchId STRATZ — чужое ID-пространство: под series_id не
            # подставляем, иначе подписан укажет на наш series_key из OpenDota.
            # Официальных series_id в live-схеме STRATZ нет (интроспекция).
            "stratz_match_id": stratz_match.get("matchId"),
            "series_id": None,
            "game_time_seconds": stratz_match.get("gameTime"),
            "radiant": {
                "name": radiant_label,
                "kills": stratz_match.get("radiantScore"),
                "players": radiant_players,
            },
            "dire": {
                "name": dire_label,
                "kills": stratz_match.get("direScore"),
                "players": dire_players,
            },
            "bans": {"radiant": radiant_bans, "dire": dire_bans},
            "picks_by_order": {"radiant": radiant_picks, "dire": dire_picks},
            "note": (
                "Данные STRATZ (live-пики и live-баны из playbackData.pickBans; "
                "схема подтверждена интроспекцией 2026-09-27)."
            ),
        }

    # Приоритет 2: OpenDota /api/live (только пики), опознание по account_id.
    result = live_match_view(
        team_a=row.team_a_label,
        team_b=row.team_b_label,
        accounts_a=accounts_a,
        accounts_b=accounts_b,
        client=httpx.Client(),
    )
    if stratz_note:
        result["message"] = f"{stratz_note} {result.get('message', '')}".strip()
    return result


@router.post("/{fixture_id}/draft")
def save_draft_observation(
    fixture_id: str, payload: DraftObservation, db: Session = Depends(get_db)  # noqa: B008
) -> dict[str, Any]:
    """Сохранить наблюдаемый драфт как данные Gate-2 (не вход модели)."""
    _load_row(db, fixture_id)
    db.execute(
        text(
            "UPDATE scheduled_match SET draft_observed = CAST(:draft AS jsonb), "
            "updated_at = now() WHERE id = CAST(:id AS uuid)"
        ),
        {"draft": json.dumps(payload.draft, ensure_ascii=False), "id": fixture_id},
    )
    db.commit()
    updated = _load_row(db, fixture_id)
    updated["draft_note"] = _DRAFT_NOTE
    return updated
