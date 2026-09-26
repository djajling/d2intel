"""Static contract checks for prediction-workbench client interactions."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SITE_DIR = REPO_ROOT / "site"


def test_prediction_journal_controls_have_matching_client_handlers() -> None:
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")
    app = (SITE_DIR / "app.js").read_text(encoding="utf-8")

    for element_id in (
        "prediction-search",
        "prediction-filter",
        "export-predictions",
        "journal-visible-count",
        "journal-evaluated-count",
        "journal-retrospective-stats",
        "journal-observed-stats",
    ):
        assert f'id="{element_id}"' in html
    assert "prediction-search" in app
    assert "prediction-filter" in app
    assert "export-predictions" in app
    assert "journal-retrospective" in app
    assert "journal-observed" in app

    assert "$('#prediction-search').addEventListener('input'" in app
    assert "$('#prediction-filter').addEventListener('change'" in app
    assert "$('#export-predictions').addEventListener('click'" in app
    assert "function exportVisiblePredictions()" in app
    assert "URL.createObjectURL(blob)" in app
    assert "function isSnapshotAbstention(snapshot)" in app
    assert "snapshot.abstention_reason" in app


def test_retrospective_and_prospective_metrics_remain_separate() -> None:
    app = (SITE_DIR / "app.js").read_text(encoding="utf-8")
    html = (SITE_DIR / "index.html").read_text(encoding="utf-8")

    assert "['retrospective_reconstructed', 'journal-retrospective']" in app
    assert "['prospective_observed', 'journal-observed']" in app
    assert "getSnapshotMode(snapshot) === mode" in app
    assert "Ретроспективные и проспективные когорты не смешиваются." in html


def test_csv_export_escapes_cells_and_guards_spreadsheet_formulas() -> None:
    app = (SITE_DIR / "app.js").read_text(encoding="utf-8")

    assert "function csvField(value)" in app
    assert """replaceAll('"', '""')""" in app
    assert r"^[\t\r ]*[=+\-@]" in app
    assert "? `'${text}` : text" in app
    assert "text/csv;charset=utf-8" in app
