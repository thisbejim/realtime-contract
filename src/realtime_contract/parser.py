"""Input decoding for JSONL and lightweight capture envelopes."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any, TextIO

from .model import EventRecord, Finding


def _source(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"client", "outbound", "send", "sent", "c"}:
        return "client"
    if normalized in {"server", "inbound", "receive", "received", "s"}:
        return "server"
    return normalized or None


def _timestamp_ms(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) * 1000 if abs(float(value)) < 10_000_000_000 else float(value)
    if isinstance(value, str):
        try:
            return _timestamp_ms(float(value))
        except ValueError:
            pass
        candidate = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(candidate).timestamp() * 1000
        except ValueError:
            return None
    return None


def _looks_like_json(value: str) -> bool:
    return bool(re.match(r"^\s*[\[{]", value))


def parse_lines(lines: Iterable[str]) -> tuple[list[EventRecord], list[Finding]]:
    """Parse raw events or ``{source,event,timestamp}`` capture envelopes.

    The parser intentionally drops malformed/raw payload text from diagnostics. This keeps a
    pasted API key or prompt out of a CI report while still pointing at the exact line.
    """

    records: list[EventRecord] = []
    findings: list[Finding] = []
    for line_number, raw_line in enumerate(lines, 1):
        if not raw_line.strip():
            continue
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            findings.append(
                Finding(
                    "input.invalid_json",
                    "error",
                    f"Line is not valid JSON ({exc.msg}).",
                    line=line_number,
                )
            )
            continue
        if not isinstance(value, dict):
            findings.append(
                Finding(
                    "input.event_not_object",
                    "error",
                    "Each non-empty line must decode to a JSON object.",
                    line=line_number,
                )
            )
            continue

        source = _source(value.get("source", value.get("direction")))
        timestamp = _timestamp_ms(value.get("timestamp", value.get("time", value.get("ts"))))
        event_value: Any = value
        if "event" in value:
            event_value = value["event"]
        elif (
            isinstance(value.get("data"), str)
            and "type" not in value
            and _looks_like_json(value["data"])
        ):
            try:
                event_value = json.loads(value["data"])
            except json.JSONDecodeError:
                findings.append(
                    Finding(
                        "input.invalid_event_data",
                        "error",
                        "The capture envelope's data field is not valid JSON.",
                        line=line_number,
                    )
                )
                continue

        if not isinstance(event_value, dict):
            findings.append(
                Finding(
                    "input.event_not_object",
                    "error",
                    "The event payload must be a JSON object.",
                    line=line_number,
                )
            )
            continue
        if timestamp is None and any(key in value for key in ("timestamp", "time", "ts")):
            findings.append(
                Finding(
                    "input.invalid_timestamp",
                    "warning",
                    "Timestamp was present but could not be interpreted; ordering checks "
                    "skipped for this line.",
                    line=line_number,
                )
            )
        records.append(EventRecord(line_number, event_value, source, timestamp))
    return records, findings


def parse_stream(stream: TextIO) -> tuple[list[EventRecord], list[Finding]]:
    return parse_lines(stream)
