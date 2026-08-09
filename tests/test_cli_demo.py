from __future__ import annotations

import json
from pathlib import Path

from pricewitness.cli import main
from pricewitness.demo import create_demo


def test_cli_full_workflow(tmp_path: Path, capsys: object) -> None:
    demo = tmp_path / "demo"
    assert main(["demo", "--output", str(demo)]) == 0
    payload = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]
    assert payload["ok"] is True

    analysis = tmp_path / "analysis.json"
    assert main(["analyze", str(demo / "pricewitness.db"), "--output", str(analysis)]) == 0
    assert analysis.exists()
    capsys.readouterr()  # type: ignore[attr-defined]

    report = tmp_path / "report.html"
    assert main(["report", str(demo / "pricewitness.db"), "--output", str(report)]) == 0
    assert report.exists()
    capsys.readouterr()  # type: ignore[attr-defined]

    export = tmp_path / "export.csv"
    assert main(["export", str(demo / "pricewitness.db"), "--output", str(export)]) == 0
    assert export.exists()


def test_cli_init_ingest_rematch_and_verify(tmp_path: Path, capsys: object) -> None:
    database = tmp_path / "ledger.db"
    assert main(["init", str(database)]) == 0
    source = tmp_path / "receipt.txt"
    source.write_text("Shop\n2026-01-02\nTEA 20CT $4.00\nTOTAL $4.00\n", encoding="utf-8")
    aliases = tmp_path / "aliases.json"
    assert (
        main(
            [
                "aliases",
                "add",
                str(aliases),
                "--product-key",
                "tea",
                "--product-name",
                "Black tea",
                "--pattern",
                "TEA 20CT",
                "--package",
                "20 ct",
            ]
        )
        == 0
    )
    assert main(["aliases", "validate", str(aliases)]) == 0
    assert main(["ingest", str(database), str(source), "--aliases", str(aliases)]) == 0
    assert main(["rematch", str(database), "--aliases", str(aliases)]) == 0
    assert main(["verify", str(database), str(source)]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]


def test_cli_reports_user_error(tmp_path: Path, capsys: object) -> None:
    assert main(["aliases", "validate", str(tmp_path / "missing.json")]) == 2
    assert "pricewitness:" in capsys.readouterr().err  # type: ignore[attr-defined]
    assert main(["verify", str(tmp_path / "missing.db")]) == 1


def test_demo_refuses_nonempty_output(tmp_path: Path) -> None:
    destination = tmp_path / "demo"
    destination.mkdir()
    (destination / "keep.txt").write_text("keep", encoding="utf-8")
    try:
        create_demo(destination)
    except ValueError as exc:
        assert "not empty" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected a nonempty demo directory to be rejected")
