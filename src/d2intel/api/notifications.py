"""Уведомления владельца в Telegram (NOTIF-001).

Три вида уведомлений по фикстуре:

* ``tournament_start`` — турнир начался: какие пары сегодня играют и когда.
  Рассылка идёт по группе фикстур одного турнира, а не по одной партии,
  чтобы не получить 8 пушей в стартовый день BLAST Slam VIII.
* ``match_start`` — игра началась (или вот-вот начнётся): команды и
  замороженная вероятность, если freeze уже есть.
* ``draft_ready`` — драфт собран: пики/баны по сторонам + вероятность из
  заморозки (модель не принята — пометка обязательна).

Идемпотентность — таблица ``scheduled_match_notify_state``: ключ
``(fixture_id, kind)``. Авто-цикл дёргает эндпоинт раз в 5 минут; без
фиксации состояния он слал бы одно и то же сообщение каждые 5 минут,
пока окно не закроется. ``force=True`` — ручной повтор владельца.

Честность (правила AGENTS.md / ADR-007):

* вероятность отправляется всегда, но с явной пометкой, если модель не
  принята (точность ниже порога 0.70). Владелец видит число и его статус,
  а не «уверенный прогноз»;
* отсутствие данных (нет freeze, нет драфта, источник молчит) никогда не
  подменяется нулями или правдоподобным текстом — отправляется честное
  «нет данных» или уведомление не уходит;
* уведомление не пишет в evidence-данные и не меняет заморозку.

Содержимое — display-only, источником расписания остаётся Liquipedia
(CC BY-SA 3.0); атрибуция присутствует в тексте о начале турнира.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

#: Виды уведомлений. Любое добавление — миграция CHECK-констрейнта 0006.
TOURNAMENT_START = "tournament_start"
MATCH_START = "match_start"
DRAFT_READY = "draft_ready"
KINDS = (TOURNAMENT_START, MATCH_START, DRAFT_READY)

#: Пометка о статусе модели: порог ADR-007 (0.70) не достигнут ни одной
#: из обученных моделей (ML-001 0.56, ML-002/ML-003 0.60–0.67 на малых n).
#: Отправляется дословно, без «уверенного» рерайта.
MODEL_NOT_ACCEPTED_NOTE = (
    "модель не принята: порог ADR-007 (0.70) не достигнут, "
    "точность на тесте 0.60–0.67 при малой выборке — число индикативное"
)

ATTRIBUTION = "Расписание: Liquipedia (CC BY-SA 3.0)"


def _format_dt(value: Any) -> str:
    """Понятная человеку дата/время или честное «—»."""
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return str(value)
    if not isinstance(value, datetime):
        return str(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.strftime("%d.%m %H:%M %Z").replace("UTC", "UTC")


def _freezed_probability(db: Session, fixture_id: str) -> tuple[float | None, str | None]:
    """Вероятность из immutable-артефакта заморозки.

    Возвращает (p_a, freeze_id). Если заморозки нет — (None, None):
    чужой ретроспективный прогноз не подменяет prospective-заморозку.
    """
    row = db.execute(
        text("SELECT freeze_id FROM scheduled_match WHERE id = CAST(:id AS uuid)"),
        {"id": fixture_id},
    ).first()
    if row is None or row.freeze_id is None:
        return None, None
    from d2intel.api.schedule import REPO_ROOT

    path = REPO_ROOT / "artifacts" / "prospective" / f"{row.freeze_id}.json"
    if not path.exists():
        return None, str(row.freeze_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, str(row.freeze_id)
    p_a = payload.get("p_a")
    return (float(p_a) if isinstance(p_a, int | float) else None), str(row.freeze_id)


def _already_sent(
    db: Session, fixture_id: str, kind: str
) -> tuple[bool, str | None]:
    """Отправлялось ли уже уведомление (и какой хэш содержимого)."""
    row = db.execute(
        text(
            "SELECT message_kind_hash FROM scheduled_match_notify_state "
            "WHERE fixture_id = CAST(:fid AS uuid) AND kind = :kind"
        ),
        {"fid": fixture_id, "kind": kind},
    ).first()
    if row is None:
        return False, None
    return True, str(row.message_kind_hash)


def _mark_sent(db: Session, fixture_id: str, kind: str, content_hash: str) -> None:
    """Зафиксировать отправку (upsert: force-повтор увеличивает счётчик)."""
    db.execute(
        text(
            """
            INSERT INTO scheduled_match_notify_state
                (fixture_id, kind, message_kind_hash, sent_kind_count)
            VALUES (CAST(:fid AS uuid), :kind, :hash, 1)
            ON CONFLICT (fixture_id, kind) DO UPDATE
            SET sent_at = now(),
                message_kind_hash = EXCLUDED.message_kind_hash,
                sent_kind_count =
                    scheduled_match_notify_state.sent_kind_count + 1
            """
        ),
        {"fid": fixture_id, "kind": kind, "hash": content_hash},
    )


def _content_hash(text_body: str) -> str:
    return hashlib.sha256(text_body.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Форматирование сообщений
# ---------------------------------------------------------------------------

def _probability_block(p_a: float | None, team_a: str, team_b: str) -> str:
    """Блок вероятности с честной пометкой статуса модели."""
    if p_a is None:
        return "Вероятность: нет заморозки (прогноз не делался)"
    pct = round(p_a * 100)
    other = round((1.0 - p_a) * 100)
    return (
        f"Вероятность: {team_a} {pct}% — {team_b} {other}% "
        f"({MODEL_NOT_ACCEPTED_NOTE})"
    )


def _draft_block(draft: dict[str, Any] | list[Any] | None, hero_names: dict[int, str]) -> str:
    """Пики и баны по сторонам из draft_observed (одна карта)."""
    if not draft:
        return "Драфт: в источнике отсутствует (absent_in_source)"
    picks = draft if isinstance(draft, list) else (draft.get("picks") or [])
    if not picks:
        return "Драфт: в источнике отсутствует (absent_in_source)"

    def _fmt_side(side: str) -> str:
        picked = [
            (hero_names.get(int(p["hero_id"])) if p.get("hero_id") else None)
            for p in picks
            if p.get("team") == side and p.get("is_pick")
        ]
        banned = [
            (hero_names.get(int(p["hero_id"])) if p.get("hero_id") else None)
            for p in picks
            if p.get("team") == side and not p.get("is_pick")
        ]
        picked_names = [n for n in picked if n]
        banned_names = [n for n in banned if n]
        lines = [f"  {side.capitalize()}: пики — {', '.join(picked_names) or '—'}"]
        if banned_names:
            lines.append(f"  {side.capitalize()}: баны — {', '.join(banned_names)}")
        return "\n".join(lines)

    return "Драфт:\n" + "\n".join([_fmt_side("radiant"), _fmt_side("dire")])


def build_tournament_start_message(
    *,
    tournament: str,
    fixtures: list[dict[str, Any]],
) -> str | None:
    """Сообщение о старте турнира по группе фикстур.

    Возвращает None, если ни одной предстоящей фикстуры нет (пушить нечего).
    """
    upcoming = [f for f in fixtures if f.get("scheduled_at") is not None]
    if not upcoming:
        return None
    lines = [f"d2intel: турнир начался — {tournament}", ""]
    for fixture in sorted(upcoming, key=lambda f: str(f.get("scheduled_at"))):
        lines.append(
            f"{_format_dt(fixture['scheduled_at'])}  "
            f"{fixture['team_a_label']} vs {fixture['team_b_label']}"
            + (f"  ({fixture['stage_label']})" if fixture.get("stage_label") else "")
        )
    lines.append("")
    lines.append(ATTRIBUTION)
    return "\n".join(lines)


def build_match_start_message(
    *,
    tournament: str,
    fixture: dict[str, Any],
    p_a: float | None,
) -> str:
    """Сообщение о начале матча."""
    lines = [
        f"d2intel: игра началась — {fixture['team_a_label']} vs {fixture['team_b_label']}",
        f"Турнир: {tournament}",
    ]
    if fixture.get("stage_label"):
        lines.append(f"Формат: {fixture['stage_label']}")
    lines.append(_probability_block(p_a, fixture["team_a_label"], fixture["team_b_label"]))
    return "\n".join(lines)


def build_draft_message(
    *,
    tournament: str,
    fixture: dict[str, Any],
    map_entry: dict[str, Any],
    hero_names: dict[int, str],
    p_a: float | None,
) -> str:
    """Сообщение о готовом драфте одной карты."""
    lines = [
        f"d2intel: драфт готов — {fixture['team_a_label']} vs {fixture['team_b_label']}",
        f"Турнир: {tournament}",
    ]
    map_number = map_entry.get("map_number")
    lines.append(
        f"Карта: {map_number}" if isinstance(map_number, int) else "Карта: номер не доказан"
    )
    lines.append(_draft_block(map_entry.get("draft"), hero_names))
    lines.append(_probability_block(p_a, fixture["team_a_label"], fixture["team_b_label"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Отправка
# ---------------------------------------------------------------------------

def send_notification(
    db: Session,
    *,
    kind: str,
    fixture_id: str,
    text_body: str,
    force: bool = False,
    sender: Any = None,
    skip_mark: bool = False,
) -> dict[str, Any]:
    """Отправить уведомление с идемпотентностью по (fixture_id, kind).

    ``sender`` — callable(text) -> bool, по умолчанию реальный Telegram-пуш.
    Тесты и ``dry_run`` подменяют его, чтобы не слать в чужой чат.
    ``skip_mark=True`` — доставка прошла, но состояние не фиксируется:
    режим dry-run (сообщение собрано и показано, но не «отправлено»).
    """
    if kind not in KINDS:
        raise ValueError(f"Неизвестный вид уведомления: {kind}")

    sent, _prev_hash = _already_sent(db, fixture_id, kind)
    if sent and not force:
        return {"fixture_id": fixture_id, "kind": kind, "status": "already_sent"}

    deliver = sender or _default_telegram_sender
    try:
        delivered = deliver(text_body)
    except Exception:  # noqa: BLE001 — пуш не должен ронять авто-цикл
        return {"fixture_id": fixture_id, "kind": kind, "status": "send_failed"}

    if not delivered:
        return {"fixture_id": fixture_id, "kind": kind, "status": "send_failed"}

    if not skip_mark:
        _mark_sent(db, fixture_id, kind, _content_hash(text_body))
        db.commit()
    return {"fixture_id": fixture_id, "kind": kind, "status": "sent"}


def _default_telegram_sender(text_body: str) -> bool:
    from d2intel.api.schedule import notify_telegram

    return notify_telegram(text_body)


# ---------------------------------------------------------------------------
# Триггеры (вызываются авто-циклом)
# ---------------------------------------------------------------------------

def trigger_tournament_start(
    db: Session,
    *,
    tournament: str,
    now: datetime | None = None,
    sender: Any = None,
    force: bool = False,
    skip_mark: bool = False,
) -> list[dict[str, Any]]:
    """Уведомление о старте турнира.

    Условие: есть предстоящие (upcoming) фикстуры этого турнира, до старта
    первой из которых осталось меньше суток. Все они уходят одним пушем,
    иначе в первый день BLAST Slam VIII придётся 8 сообщений подряд.
    """
    now = now or datetime.now(UTC)
    pattern = f"%{tournament}%"
    rows = db.execute(
        text(
            """
            SELECT id, tournament_label, team_a_label, team_b_label, stage_label, scheduled_at
            FROM scheduled_match
            WHERE tournament_label ILIKE :pattern
              AND status = 'upcoming'
              AND scheduled_at IS NOT NULL
            ORDER BY scheduled_at
            """
        ),
        {"pattern": pattern},
    ).all()
    if not rows:
        return [{"tournament": tournament, "status": "no_upcoming"}]

    fixtures = [dict(r._mapping) for r in rows]
    first_start = min(
        f["scheduled_at"].replace(tzinfo=UTC) if f["scheduled_at"].tzinfo is None else f["scheduled_at"]
        for f in fixtures
    )
    if (first_start - now).total_seconds() > 24 * 3600:
        return [{"tournament": tournament, "status": "too_early"}]

    # Одна запись на турнир: используем id первой фикстуры как якорь ключа
    # идемпотентности. Пуш групповой, поэтому (fixture_id, kind) достаточно.
    anchor_id = str(fixtures[0]["id"])
    sent, _ = _already_sent(db, anchor_id, TOURNAMENT_START)
    if sent and not force:
        return [{"tournament": tournament, "status": "already_sent"}]

    # Реальное имя турнира из БД (фильтр — подстрока), для честного заголовка.
    label = str(fixtures[0]["tournament_label"])
    message = build_tournament_start_message(tournament=label, fixtures=fixtures)
    if message is None:
        return [{"tournament": tournament, "status": "nothing_to_send"}]
    result = send_notification(
        db,
        kind=TOURNAMENT_START,
        fixture_id=anchor_id,
        text_body=message,
        force=force,
        sender=sender,
        skip_mark=skip_mark,
    )
    result["tournament"] = tournament
    return [result]


def trigger_match_start(
    db: Session,
    *,
    fixture_id: str,
    now: datetime | None = None,
    sender: Any = None,
    force: bool = False,
    skip_mark: bool = False,
) -> dict[str, Any]:
    """Уведомление о начале матча.

    Условие: фикстура upcoming/frozen и время старта наступило. Замороженные
    уходят с вероятностью, незамороженные — с честным «нет заморозки».
    """
    now = now or datetime.now(UTC)
    row = db.execute(
        text(
            """
            SELECT id, tournament_label, team_a_label, team_b_label, stage_label,
                   scheduled_at, status
            FROM scheduled_match
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": fixture_id},
    ).first()
    if row is None:
        return {"fixture_id": fixture_id, "status": "not_found"}

    fixture = dict(row._mapping)
    if fixture["status"] not in ("upcoming", "frozen"):
        return {"fixture_id": fixture_id, "status": f"status_{fixture['status']}"}

    start = fixture["scheduled_at"]
    if start is None:
        return {"fixture_id": fixture_id, "status": "no_scheduled_at"}
    if start.tzinfo is None:
        start = start.replace(tzinfo=UTC)
    if now < start:
        return {"fixture_id": fixture_id, "status": "not_started_yet"}

    p_a, _freeze_id = _freezed_probability(db, fixture_id)
    message = build_match_start_message(
        tournament=fixture["tournament_label"],
        fixture=fixture,
        p_a=p_a,
    )
    result = send_notification(
        db,
        kind=MATCH_START,
        fixture_id=fixture_id,
        text_body=message,
        force=force,
        sender=sender,
        skip_mark=skip_mark,
    )
    if result["status"] == "sent":
        result["p_a"] = p_a
    return result


def trigger_draft_ready(
    db: Session,
    *,
    fixture_id: str,
    sender: Any = None,
    force: bool = False,
    skip_mark: bool = False,
) -> dict[str, Any]:
    """Уведомление о готовом драфте.

    Условие: у фикстуры есть ``draft_observed.maps`` с драфтом, который ещё
    не рассылался. Драфт — данные Gate-2, входом текущей модели НЕ является
    (ADR-006): вероятность в пуше остаётся pre-draft из заморозки, а состав
    героев прилагается отдельным блоком.
    """
    row = db.execute(
        text(
            """
            SELECT id, tournament_label, team_a_label, team_b_label, stage_label,
                   draft_observed
            FROM scheduled_match
            WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": fixture_id},
    ).first()
    if row is None:
        return {"fixture_id": fixture_id, "status": "not_found"}

    fixture = dict(row._mapping)
    observed = fixture.get("draft_observed") or {}
    if not isinstance(observed, dict):
        observed = {}
    maps = observed.get("maps") or []
    if not maps:
        return {"fixture_id": fixture_id, "status": "no_draft"}

    # Берём последнюю карту: именно её драфт наиболее свежий и полный.
    map_entry = maps[-1]
    if not isinstance(map_entry, dict):
        return {"fixture_id": fixture_id, "status": "no_draft"}
    draft = map_entry.get("draft")
    if not draft:
        return {"fixture_id": fixture_id, "status": "draft_absent"}

    from d2intel.ingestion.live_draft import load_hero_names

    hero_names = load_hero_names()
    p_a, _freeze_id = _freezed_probability(db, fixture_id)
    message = build_draft_message(
        tournament=fixture["tournament_label"],
        fixture=fixture,
        map_entry=map_entry,
        hero_names=hero_names,
        p_a=p_a,
    )
    result = send_notification(
        db,
        kind=DRAFT_READY,
        fixture_id=fixture_id,
        text_body=message,
        force=force,
        sender=sender,
        skip_mark=skip_mark,
    )
    if result["status"] == "sent":
        result["p_a"] = p_a
    return result
