"""Stable text, Markdown, JSON, and SARIF renderers."""

from __future__ import annotations

import json
from typing import Any

from .model import Finding, Report


def render_json(report: Report) -> str:
    return json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n"


def _severity_label(finding: Finding) -> str:
    return finding.severity.upper()


def render_text(report: Report) -> str:
    metrics = report.metrics
    lines = [
        f"Realtime Contract: {report.status.upper()}",
        (
            f"Events {metrics.get('events', 0)} | known {metrics.get('known_events', 0)} | "
            f"unknown {metrics.get('unknown_events', 0)} | responses {metrics.get('responses', 0)}"
        ),
        (
            f"Output: {metrics.get('text_chars', 0)} text chars | "
            f"{metrics.get('audio_transcript_chars', 0)} transcript chars | "
            f"{metrics.get('audio_bytes', 0)} audio bytes"
        ),
    ]
    if report.responses:
        lines.append("Responses:")
        for response in report.responses:
            lines.append(
                "  "
                + str(response["response_id"])
                + f"  {response.get('status') or 'unknown'}"
                + f"  text={response.get('text_chars', 0)} chars"
                + f"  audio={response.get('audio_bytes', 0)} bytes"
                + f"  tools={response.get('tool_calls', 0)}"
            )
    if report.findings:
        lines.append("Findings:")
        for finding in report.findings:
            location = f"line {finding.line}: " if finding.line is not None else ""
            lines.append(
                f"  {_severity_label(finding)} {location}{finding.code} — {finding.message}"
            )
    else:
        lines.append("Findings: none")
    return "\n".join(lines) + "\n"


def render_markdown(report: Report) -> str:
    metrics = report.metrics
    lines = [
        f"# Realtime Contract: {report.status.upper()}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Events | {metrics.get('events', 0)} |",
        f"| Known events | {metrics.get('known_events', 0)} |",
        f"| Unknown events | {metrics.get('unknown_events', 0)} |",
        f"| Responses | {metrics.get('responses', 0)} |",
        f"| Terminal responses | {metrics.get('terminal_responses', 0)} |",
        f"| Text characters | {metrics.get('text_chars', 0)} |",
        f"| Audio bytes | {metrics.get('audio_bytes', 0)} |",
        "",
    ]
    if report.responses:
        lines.extend(
            [
                "## Responses",
                "",
                "| Response | Status | Text | Audio | Tools |",
                "| --- | --- | ---: | ---: | ---: |",
            ]
        )
        for response in report.responses:
            lines.append(
                f"| `{response['response_id']}` | {response.get('status') or 'unknown'} | "
                f"{response.get('text_chars', 0)} chars | {response.get('audio_bytes', 0)} bytes | "
                f"{response.get('tool_calls', 0)} |"
            )
        lines.append("")
    lines.extend(["## Findings", ""])
    if report.findings:
        for finding in report.findings:
            location = f" (line {finding.line})" if finding.line is not None else ""
            lines.append(
                f"- **{_severity_label(finding)}** `{finding.code}`{location}: {finding.message}"
            )
    else:
        lines.append("No findings.")
    lines.append("")
    return "\n".join(lines)


def render_sarif(report: Report, *, uri: str = "transcript.jsonl") -> str:
    results: list[dict[str, Any]] = []
    rules: dict[str, dict[str, str]] = {}
    for finding in report.findings:
        rules.setdefault(finding.code, {"id": finding.code, "name": finding.code})
        result: dict[str, Any] = {
            "ruleId": finding.code,
            "level": "error" if finding.severity == "error" else "warning",
            "message": {"text": finding.message},
        }
        if finding.line is not None:
            result["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": uri},
                        "region": {"startLine": finding.line},
                    }
                }
            ]
        results.append(result)
    payload = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "realtime-contract",
                        "version": report.version,
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
