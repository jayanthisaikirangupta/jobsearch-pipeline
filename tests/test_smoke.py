"""Import + light unit tests. Heavy integration tests live elsewhere."""
from __future__ import annotations


def test_imports() -> None:
    import jobsearch.cli  # noqa: F401
    import jobsearch.config  # noqa: F401
    import jobsearch.ingest.base  # noqa: F401
    import jobsearch.ingest.runner  # noqa: F401
    import jobsearch.score.scorer  # noqa: F401
    import jobsearch.sponsors.filter  # noqa: F401
    import jobsearch.sponsors.register  # noqa: F401
    import jobsearch.tailor.picker  # noqa: F401
    import jobsearch.tailor.runner  # noqa: F401
    import jobsearch.tracker.db  # noqa: F401


def test_score_salary_band() -> None:
    from jobsearch.score.scorer import _score_salary
    assert _score_salary(20_000, 33_400, 38_290) == 0
    assert _score_salary(34_000, 33_400, 38_290) > 0
    assert _score_salary(60_000, 33_400, 38_290) == 20
    assert _score_salary(None, 33_400, 38_290) == 10


def test_score_grade_bands() -> None:
    from jobsearch.score.scorer import ScoreBreakdown
    assert ScoreBreakdown(20, 20, 20, 20, 15).grade == "A"
    assert ScoreBreakdown(15, 15, 15, 15, 15).grade == "B"
    assert ScoreBreakdown(12, 12, 12, 12, 8).grade == "C"
    assert ScoreBreakdown(10, 10, 10, 5, 5).grade == "D"
    assert ScoreBreakdown(5, 5, 5, 5, 5).grade == "F"


def test_tracker_roundtrip(tmp_path, monkeypatch) -> None:
    from jobsearch import config as cfg
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    cfg.get_settings.cache_clear()
    from jobsearch.tracker import db

    db.upsert_application("j1", "AI Engineer", "Acme", "https://x", "A", 90)
    assert db.get("j1")["status"] == "discovered"
    assert db.set_status("j1", "applied")
    assert db.get("j1")["status"] == "applied"
    rows = db.list_apps(status="applied")
    assert len(rows) == 1


def test_norm_company() -> None:
    from jobsearch.sponsors.filter import _norm
    assert _norm("Kuehne + Nagel Ltd.") == "kuehne nagel"
    assert _norm("Acme (UK) Limited") == "acme"
