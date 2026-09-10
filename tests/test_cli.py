from __future__ import annotations

import json
from pathlib import Path

from realtime_contract.cli import main

ROOT = Path(__file__).parents[1]


def test_cli_text_success(capsys) -> None:
    code = main(["check", str(ROOT / "examples" / "valid-text.jsonl")])

    captured = capsys.readouterr()
    assert code == 0
    assert "Realtime Contract: PASS" in captured.out
    assert captured.err == ""


def test_cli_json_failure_and_output_file(tmp_path, capsys) -> None:
    output = tmp_path / "report.json"
    code = main(
        [
            "check",
            str(ROOT / "examples" / "invalid.jsonl"),
            "--format",
            "json",
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    report = json.loads(output.read_text(encoding="utf-8"))
    assert code == 1
    assert captured.out == ""
    assert report["status"] == "fail"


def test_cli_warning_can_be_promoted_to_failure(capsys) -> None:
    code = main(["check", str(ROOT / "examples" / "unknown-event.jsonl"), "--fail-on-warning"])

    captured = capsys.readouterr()
    assert code == 1
    assert "event.unknown_type" in captured.out


def test_cli_stdin_and_sarif(capsys, monkeypatch) -> None:
    import io

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO((ROOT / "examples" / "valid-text.jsonl").read_text(encoding="utf-8")),
    )
    code = main(["check", "-", "--format", "sarif"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert code == 0
    assert payload["runs"][0]["tool"]["driver"]["name"] == "realtime-contract"


def test_cli_missing_input_returns_usage_error(capsys) -> None:
    code = main(["check", "/definitely/not/a/transcript.jsonl"])

    captured = capsys.readouterr()
    assert code == 2
    assert "cannot read" in captured.err
