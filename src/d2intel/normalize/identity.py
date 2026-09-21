"""DATA-001 — каноническая идентичность: стабильные canonical id.

Правило: canonical id **детерминирован** — `uuid5` от `(источник, тип
сущности, внешний id)`. Это даёт два свойства, требуемых карточкой:

* **стабильность** — повторная загрузка того же внешнего id даёт тот же
  canonical id, без поиска «похожей» записи и без слипания разных сущностей;
* **идемпотентность** — вставка с уже известным PK дешево гасится
  `ON CONFLICT DO NOTHING`.

Источник входит в ключ намеренно: внешний id уникален только внутри источника
(`DATA_MODEL.md` §1). Межисточниковые конфликты (одна команда — два внешних id)
не разрешаются здесь автоматически: это задача `DB-002` и карантина
неоднозначностей.
"""

from __future__ import annotations

import uuid

from d2intel.ingestion.contracts import OPENDOTA_SOURCE_ID

#: Пространство имён проекта. Фиксировано: от него зависят все canonical id.
CANONICAL_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/djajling/d2intel")


class EntityKind:
    """Типы сущностей, входящие в ключ canonical id."""

    TEAM = "team"
    PLAYER = "player"
    TOURNAMENT = "tournament"
    SERIES = "series"
    GAME = "game"
    PARTICIPANT = "game_participant"
    PERFORMANCE = "player_performance"
    ROSTER = "roster_membership"
    PATCH = "patch"


def canonical_id(*, source_id: str, entity_kind: str, external_id: str | int) -> uuid.UUID:
    """Стабильный canonical id сущности. Одинаковый вход → одинаковый uuid."""
    key = f"{source_id}:{entity_kind}:{external_id}"
    return uuid.uuid5(CANONICAL_NAMESPACE, key)


def team_id(external_id: str | int, *, source_id: str = OPENDOTA_SOURCE_ID) -> uuid.UUID:
    return canonical_id(source_id=source_id, entity_kind=EntityKind.TEAM, external_id=external_id)


def player_id(external_id: str | int, *, source_id: str = OPENDOTA_SOURCE_ID) -> uuid.UUID:
    return canonical_id(source_id=source_id, entity_kind=EntityKind.PLAYER, external_id=external_id)


def tournament_id(external_id: str | int, *, source_id: str = OPENDOTA_SOURCE_ID) -> uuid.UUID:
    return canonical_id(
        source_id=source_id, entity_kind=EntityKind.TOURNAMENT, external_id=external_id
    )


def series_id(series_key: str, *, source_id: str = OPENDOTA_SOURCE_ID) -> uuid.UUID:
    return canonical_id(source_id=source_id, entity_kind=EntityKind.SERIES, external_id=series_key)


def game_id(match_id: str | int, *, source_id: str = OPENDOTA_SOURCE_ID) -> uuid.UUID:
    return canonical_id(source_id=source_id, entity_kind=EntityKind.GAME, external_id=match_id)


def game_team_id(game: uuid.UUID, slot: int) -> uuid.UUID:
    """Команда в карте по слоту (0/1 — стороны A/B)."""
    return uuid.uuid5(CANONICAL_NAMESPACE, f"game_team:{game}:{slot}")


def participant_id(game: uuid.UUID, player: uuid.UUID) -> uuid.UUID:
    """Игрок в карте: ключ — пара (игра, игрок)."""
    return uuid.uuid5(CANONICAL_NAMESPACE, f"participant:{game}:{player}")


def performance_id(participant: uuid.UUID) -> uuid.UUID:
    """Финальная статистика: одна на участника карты."""
    return uuid.uuid5(CANONICAL_NAMESPACE, f"performance:{participant}")


def roster_membership_id(team: uuid.UUID, player: uuid.UUID, game: uuid.UUID) -> uuid.UUID:
    """Свидетельство состава: (команда, игрок, карта-свидетельство)."""
    return uuid.uuid5(CANONICAL_NAMESPACE, f"roster:{team}:{player}:{game}")


def patch_id(version_label: str, *, source_id: str = OPENDOTA_SOURCE_ID) -> uuid.UUID:
    return canonical_id(source_id=source_id, entity_kind=EntityKind.PATCH, external_id=version_label)
