"""DATA-001 — детерминированность canonical id."""

from __future__ import annotations

from uuid import UUID, uuid5

from d2intel.ingestion.contracts import OPENDOTA_SOURCE_ID
from d2intel.normalize import identity


def test_canonical_id_is_stable() -> None:
    """Один и тот же внешний id всегда даёт один canonical id."""
    first = identity.team_id(36)
    second = identity.team_id(36)
    assert first == second
    assert isinstance(first, UUID)


def test_namespace_is_derived_from_project_url() -> None:
    """Пространство имён задано явно, а не «каким-то» UUID."""
    expected = uuid5(identity.uuid.NAMESPACE_URL, "https://github.com/djajling/d2intel")
    assert expected == identity.CANONICAL_NAMESPACE


def test_different_kinds_do_not_collide() -> None:
    """Одинаковый внешний id у разных типов сущностей — разные uuid."""
    assert identity.team_id(36) != identity.player_id(36)
    assert identity.team_id(36) != identity.tournament_id(36)


def test_different_sources_do_not_collide() -> None:
    """Внешний id уникален только внутри источника."""
    assert identity.team_id(36, source_id=OPENDOTA_SOURCE_ID) != identity.team_id(
        36, source_id="liquipedia"
    )


def test_derived_ids_are_stable() -> None:
    """Составные id (участник, статистика, свидетельство) тоже детерминированы."""
    game = identity.game_id(9000000001)
    player = identity.player_id(100)
    team = identity.team_id(36)
    assert identity.participant_id(game, player) == identity.participant_id(game, player)
    assert identity.performance_id(player) != identity.participant_id(game, player)
    assert identity.roster_membership_id(team, player, game) == identity.roster_membership_id(
        team, player, game
    )
    assert identity.game_team_id(game, 0) != identity.game_team_id(game, 1)


def test_string_and_int_external_ids_agree() -> None:
    """«36» и 36 — один и тот же внешний id."""
    assert identity.team_id("36") == identity.team_id(36)
