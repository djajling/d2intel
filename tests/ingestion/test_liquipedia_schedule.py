"""ADR-008 — тесты парсера Liquipedia на сохранённой фикстуре (без сети).

Фикстура `tests/fixtures/liquipedia_matchlist_sample.html` — реальные 3 строки
`brkts-matchlist-match` со страницы PGL/Wallachia/9/Group Stage (обрезанные
popup'ы сохранены: парсер не должен ломаться на вложенной разметке).
"""

from __future__ import annotations

from pathlib import Path

from d2intel.ingestion.liquipedia_schedule import (
    parse_matches_from_html,
)

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "liquipedia_matchlist_sample.html"


def _parse_sample() -> list[dict]:
    return parse_matches_from_html(FIXTURE.read_text(encoding="utf-8"), source_page="PGL/Wallachia/9/Group Stage")


def test_parses_three_real_match_rows() -> None:
    matches = _parse_sample()
    assert len(matches) == 3
    first = matches[0]
    assert first["teams"][0] == "1w Team"
    assert first["teams"][1] == "Team Nemesis"
    assert first["bestof"] == 3
    assert first["finished"] is True
    assert first["score"] == ["1", "2"]
    assert first["winner"] == "Team Nemesis"
    assert first["started_at"] is not None


def test_started_at_is_utc_iso_from_unix_timestamp() -> None:
    """data-timestamp=1789801200 → 2026-09-19T10:00:00+03:00 == 07:00 UTC."""
    first = _parse_sample()[0]
    assert first["started_at"] == "2026-09-19T07:00:00+00:00"


def test_teams_deduplicated_from_popup_markup() -> None:
    """Popup повторяет команды — берутся первые два уникальных по порядку."""
    matches = _parse_sample()
    for match in matches:
        assert len(match["teams"]) == 2
        assert match["teams"][0] != match["teams"][1]


def test_rows_without_two_teams_are_skipped() -> None:
    """TBD-плейсхолдеры (меньше двух имён) не превращаются в матчи."""
    html = (
        '<div class="brkts-matchlist-match"><div>ничего полезного</div></div>'
        + FIXTURE.read_text(encoding="utf-8")
    )
    matches = parse_matches_from_html(html, source_page="test")
    assert len(matches) == 3  # только реальные строки фикстуры


def test_score_draw_has_no_winner() -> None:
    """При равном счёте (несыгранная серия) winner — None."""
    import re

    html = FIXTURE.read_text(encoding="utf-8")
    # синтетический случай: второй счёт первой строки → 1 (паттерн с атрибутами)
    patched = re.sub(
        r"(match-info-header-scoreholder-score[^>]*>)2</span>",
        r"\g<1>1</span>",
        html,
        count=1,
    )
    patched_matches = parse_matches_from_html(patched, source_page="t")
    assert patched_matches[0]["score"] == ["1", "1"]
    assert patched_matches[0]["winner"] is None


# --------------------------------------------------------------------------- #
# Портал Liquipedia:Matches — все турниры
# ---------------------------------------------------------------------------

PORTAL_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "liquipedia_matches_portal_sample.html"


def _parse_portal() -> list[dict]:
    from d2intel.ingestion.liquipedia_schedule import parse_ticker_matches

    return parse_ticker_matches(PORTAL_FIXTURE.read_text(encoding="utf-8"))


def test_portal_parses_upcoming_matches_with_tournament() -> None:
    matches = _parse_portal()
    assert matches, "тикер не распознан"
    first = matches[0]
    assert first["teams"] == ["YBN Team", "Stray Team"]
    assert first["tournament"] == "BB Streamers Battle 15 - Playoffs"
    assert first["bestof"] == 3
    assert first["finished"] is False  # у upcoming счёт пустой
    assert first["started_at"] == "2026-09-27T12:00:00+00:00"


def test_portal_upcoming_has_no_fake_scores() -> None:
    """Пустые спаны счёта → score None, не «0:0» (masking vs zero)."""
    for match in _parse_portal():
        assert match["score"] is None
        assert match["winner"] is None
