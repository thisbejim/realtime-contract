"""Small public data model used by the validator and renderers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EventRecord:
    """A decoded transcript row without retaining its original raw payload."""

    line: int
    event: dict[str, Any]
    source: str | None = None
    timestamp_ms: float | None = None


@dataclass(frozen=True)
class Finding:
    """A stable, payload-free diagnostic."""

    code: str
    severity: str
    message: str
    line: int | None = None
    event_type: str | None = None
    path: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
        }
        if self.line is not None:
            result["line"] = self.line
        if self.event_type is not None:
            result["event_type"] = self.event_type
        if self.path is not None:
            result["path"] = self.path
        return result


@dataclass
class Report:
    """A deterministic result suitable for CI or a human-readable renderer."""

    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    responses: list[dict[str, Any]] = field(default_factory=list)
    content_included: bool = False
    version: str = "0.1"

    @property
    def errors(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.severity == "warning"]

    @property
    def status(self) -> str:
        return "fail" if self.errors else "pass"

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status,
            "metrics": self.metrics,
            "responses": self.responses,
            "findings": [finding.as_dict() for finding in self.findings],
            "content_included": self.content_included,
        }
