from __future__ import annotations

import json
from pathlib import Path

from realtime_contract import validate_text
from realtime_contract.render import render_json, render_markdown, render_sarif, render_text

ROOT = Path(__file__).parents[1]


def read_fixture(name: str) -> str:
    return (ROOT / "examples" / name).read_text(encoding="utf-8")


def codes(report):
    return {finding.code for finding in report.findings}


def test_valid_text_fixture_passes_without_retaining_content() -> None:
    report = validate_text(read_fixture("valid-text.jsonl"))

    assert report.status == "pass"
    assert report.errors == []
    assert report.metrics == {
        "events": 14,
        "known_events": 14,
        "unknown_events": 0,
        "responses": 1,
        "terminal_responses": 1,
        "client_response_creates": 1,
        "text_chars": 12,
        "audio_transcript_chars": 0,
        "audio_bytes": 0,
        "input_audio_bytes": 0,
        "input_transcript_chars": 0,
        "findings": 0,
        "errors": 0,
        "warnings": 0,
    }
    assert "text" not in report.responses[0]


def test_valid_text_reconstructs_content_when_explicitly_requested() -> None:
    report = validate_text(read_fixture("valid-text.jsonl"), include_content=True)

    assert report.status == "pass"
    assert report.responses[0]["text"] == "Hello there!"
    assert report.content_included is True


def test_tool_fixture_reassembles_and_validates_json_arguments() -> None:
    report = validate_text(read_fixture("valid-tool.jsonl"))

    assert report.status == "pass"
    assert report.metrics["responses"] == 1
    assert report.metrics["text_chars"] == 0
    assert report.responses[0]["tool_calls"] == 1


def test_audio_fixture_counts_decoded_bytes_and_transcript() -> None:
    report = validate_text(read_fixture("valid-audio.jsonl"))

    assert report.status == "pass"
    assert report.metrics["input_audio_bytes"] == 4
    assert report.metrics["input_transcript_chars"] == 5
    assert "audio.buffer_uncommitted" not in codes(report)


def test_invalid_fixture_reports_multiple_independent_failures() -> None:
    report = validate_text(read_fixture("invalid.jsonl"))

    assert report.status == "fail"
    assert {
        "audio.commit_empty",
        "event.duplicate_id",
        "response.non_terminal_done",
        "tool.arguments_invalid_json",
        "input.invalid_json",
    } <= codes(report)
    assert all("not-json" not in finding.message for finding in report.findings)


def test_unknown_event_is_warning_by_default_and_error_in_strict_mode() -> None:
    normal = validate_text(read_fixture("unknown-event.jsonl"))
    strict = validate_text(read_fixture("unknown-event.jsonl"), strict_unknown=True)

    assert normal.status == "pass"
    assert normal.warnings[0].code == "event.unknown_type"
    assert strict.status == "fail"
    assert strict.errors[0].code == "event.unknown_type"


def test_source_direction_and_duplicate_part_are_actionable() -> None:
    text = "\n".join(
        [
            json.dumps(
                {
                    "source": "server",
                    "event": {"type": "session.created", "event_id": "s", "session": {}},
                }
            ),
            json.dumps(
                {
                    "source": "server",
                    "event": {"type": "session.update", "event_id": "wrong", "session": {}},
                }
            ),
            json.dumps(
                {
                    "source": "server",
                    "event": {
                        "type": "response.created",
                        "event_id": "r",
                        "response": {"id": "resp", "status": "in_progress"},
                    },
                }
            ),
            json.dumps(
                {
                    "source": "server",
                    "event": {
                        "type": "response.content_part.added",
                        "event_id": "p1",
                        "response_id": "resp",
                        "item_id": "item",
                        "output_index": 0,
                        "content_index": 0,
                        "part": {"type": "text"},
                    },
                }
            ),
            json.dumps(
                {
                    "source": "server",
                    "event": {
                        "type": "response.content_part.added",
                        "event_id": "p2",
                        "response_id": "resp",
                        "item_id": "item",
                        "output_index": 0,
                        "content_index": 0,
                        "part": {"type": "text"},
                    },
                }
            ),
        ]
    )

    report = validate_text(text)

    assert "event.wrong_source" in codes(report)
    assert "stream.duplicate_part_start" in codes(report)


def test_malformed_base64_and_bad_indices_are_rejected() -> None:
    text = json.dumps(
        {
            "source": "server",
            "event": {
                "type": "response.output_audio.delta",
                "event_id": "e1",
                "response_id": "resp",
                "item_id": "item",
                "output_index": -1,
                "content_index": 0,
                "delta": "!!!",
            },
        }
    )

    report = validate_text(text)

    assert "event.invalid_index" in codes(report)
    assert "audio.invalid_base64" in codes(report)


def test_parser_accepts_data_envelope_and_invalid_timestamp_warning() -> None:
    text = "\n".join(
        [
            json.dumps(
                {
                    "source": "server",
                    "time": "not-a-time",
                    "data": json.dumps({"type": "session.created", "event_id": "e", "session": {}}),
                }
            ),
            json.dumps(
                {
                    "source": "server",
                    "data": json.dumps(
                        {"type": "rate_limits.updated", "event_id": "r", "rate_limits": []}
                    ),
                }
            ),
        ]
    )

    report = validate_text(text)

    assert report.status == "pass"
    assert "input.invalid_timestamp" in codes(report)


def test_renderers_are_machine_readable_and_payload_safe() -> None:
    report = validate_text(read_fixture("invalid.jsonl"))

    payload = json.loads(render_json(report))
    sarif = json.loads(render_sarif(report))
    markdown = render_markdown(report)
    plain = render_text(report)

    assert payload["status"] == "fail"
    assert sarif["version"] == "2.1.0"
    assert "## Findings" in markdown
    assert "Realtime Contract: FAIL" in plain
    assert "not-json" not in render_json(report)
