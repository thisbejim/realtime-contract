"""Deterministic, payload-safe Realtime transcript validation."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from io import StringIO
from typing import Any

from .model import EventRecord, Finding, Report
from .parser import parse_lines, parse_stream
from .protocol import KNOWN_RESPONSE_STATUSES, SPECS, TERMINAL_RESPONSE_STATUSES


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _string(value: Any) -> bool:
    return isinstance(value, str)


def _event_id(event: Mapping[str, Any]) -> str | None:
    value = event.get("event_id")
    return value if isinstance(value, str) and value else None


def _response_id(event: Mapping[str, Any]) -> str | None:
    direct = event.get("response_id")
    if isinstance(direct, str) and direct:
        return direct
    response = event.get("response")
    if isinstance(response, Mapping):
        value = response.get("id")
        if isinstance(value, str) and value:
            return value
    return None


def _item_id(event: Mapping[str, Any]) -> str | None:
    direct = event.get("item_id")
    if isinstance(direct, str) and direct:
        return direct
    item = event.get("item")
    if isinstance(item, Mapping):
        value = item.get("id")
        if isinstance(value, str) and value:
            return value
    return None


@dataclass
class _PartState:
    started: bool = False
    done: bool = False
    text: str = ""
    transcript: str = ""
    audio_bytes: int = 0


@dataclass
class _ResponseState:
    response_id: str
    first_line: int
    created_line: int | None = None
    done_line: int | None = None
    status: str | None = None
    output_text: str = ""
    audio_transcript: str = ""
    audio_bytes: int = 0
    tool_arguments: dict[str, str] = field(default_factory=dict)
    tool_names: dict[str, str] = field(default_factory=dict)
    tool_argument_done: set[str] = field(default_factory=set)
    output_items: dict[int, str] = field(default_factory=dict)
    output_items_done: set[int] = field(default_factory=set)
    parts: dict[tuple[str, int, int], _PartState] = field(default_factory=dict)


class _Validator:
    def __init__(self, *, strict_unknown: bool, include_content: bool) -> None:
        self.strict_unknown = strict_unknown
        self.include_content = include_content
        self.findings: list[Finding] = []
        self.records = 0
        self.known_events = 0
        self.unknown_events = 0
        self.event_ids: dict[str, int] = {}
        self.previous_timestamp: float | None = None
        self.session_created = False
        self.server_events_seen = 0
        self.items: dict[str, dict[str, Any]] = {}
        self.deleted_items: set[str] = set()
        self.audio_buffer_bytes = 0
        self.input_audio_bytes = 0
        self.speech_item: str | None = None
        self.transcripts: dict[tuple[str, int], str] = {}
        self.responses: dict[str, _ResponseState] = {}
        self.client_response_creates = 0
        self.tool_outputs: set[str] = set()

    def add(
        self,
        code: str,
        severity: str,
        message: str,
        record: EventRecord | None = None,
        *,
        path: str | None = None,
    ) -> None:
        self.findings.append(
            Finding(
                code,
                severity,
                message,
                line=record.line if record else None,
                event_type=(record.event.get("type") if record else None),
                path=path,
            )
        )

    def require_fields(self, record: EventRecord, required: Iterable[str]) -> None:
        event = record.event
        for key in required:
            if key not in event:
                self.add(
                    "event.missing_field",
                    "error",
                    f"Required field '{key}' is missing.",
                    record,
                    path=f"$.{key}",
                )

    def field_type(self, record: EventRecord, key: str, expected: str) -> Any:
        value = record.event.get(key)
        valid = {
            "string": isinstance(value, str),
            "object": isinstance(value, Mapping),
            "array": isinstance(value, list),
            "integer": _is_int(value),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        }[expected]
        if not valid:
            self.add(
                "event.invalid_field_type",
                "error",
                f"Field '{key}' must be a {expected}.",
                record,
                path=f"$.{key}",
            )
        return value

    def check_common(self, record: EventRecord, event_type: str) -> None:
        spec = SPECS[event_type]
        self.known_events += 1
        if record.source and spec.source and record.source != spec.source:
            self.add(
                "event.wrong_source",
                "error",
                f"'{event_type}' is a {spec.source}-to-client event, but the capture "
                f"marks it as {record.source}.",
                record,
            )
        if record.source == "server":
            self.server_events_seen += 1
            if event_type != "error" and not _event_id(record.event):
                self.add(
                    "event.missing_event_id",
                    "error",
                    "Server events must include a non-empty event_id.",
                    record,
                    path="$.event_id",
                )
        event_id = _event_id(record.event)
        if event_id:
            earlier = self.event_ids.get(event_id)
            if earlier is not None:
                self.add(
                    "event.duplicate_id",
                    "error",
                    f"event_id is duplicated; the first occurrence is on line {earlier}.",
                    record,
                    path="$.event_id",
                )
            else:
                self.event_ids[event_id] = record.line
        self.require_fields(record, SPECS[event_type].required)

    def validate_indices(self, record: EventRecord, keys: Iterable[str]) -> None:
        for key in keys:
            if key in record.event:
                value = record.event[key]
                if not _is_int(value) or value < 0:
                    self.add(
                        "event.invalid_index",
                        "error",
                        f"'{key}' must be a non-negative integer.",
                        record,
                        path=f"$.{key}",
                    )

    def validate_audio(self, record: EventRecord, value: Any, *, field: str) -> int:
        if not isinstance(value, str):
            self.add(
                "audio.invalid_base64",
                "error",
                f"'{field}' must be a base64 string.",
                record,
                path=f"$.{field}",
            )
            return 0
        try:
            decoded = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            self.add(
                "audio.invalid_base64",
                "error",
                f"'{field}' is not valid base64 audio data.",
                record,
                path=f"$.{field}",
            )
            return 0
        return len(decoded)

    def response(self, record: EventRecord, *, create: bool = False) -> _ResponseState | None:
        response_id = _response_id(record.event)
        if response_id is None:
            return None
        result = self.responses.get(response_id)
        if result is None and create:
            result = _ResponseState(response_id, record.line)
            self.responses[response_id] = result
        return result

    def require_response(self, record: EventRecord) -> _ResponseState | None:
        state = self.response(record)
        if state is None:
            self.add(
                "response.unknown_id",
                "warning",
                "Response event refers to an ID that has not appeared in this capture.",
                record,
            )
        return state

    def part(self, state: _ResponseState, record: EventRecord) -> _PartState:
        event = record.event
        key = (
            _item_id(event) or "?",
            int(event.get("output_index", 0)) if _is_int(event.get("output_index")) else 0,
            int(event.get("content_index", 0)) if _is_int(event.get("content_index")) else 0,
        )
        result = state.parts.setdefault(key, _PartState())
        return result

    def process(self, record: EventRecord) -> None:
        self.records += 1
        event = record.event
        event_type = event.get("type")
        if not isinstance(event_type, str) or not event_type:
            self.add(
                "event.missing_type", "error", "Every event must have a non-empty type.", record
            )
            return
        if record.timestamp_ms is not None:
            if (
                self.previous_timestamp is not None
                and record.timestamp_ms < self.previous_timestamp
            ):
                self.add(
                    "time.non_monotonic",
                    "warning",
                    "Capture timestamp moves backwards; latency calculations for this "
                    "transcript may be misleading.",
                    record,
                )
            self.previous_timestamp = record.timestamp_ms
        if event_type not in SPECS:
            self.unknown_events += 1
            self.add(
                "event.unknown_type",
                "error" if self.strict_unknown else "warning",
                f"Event type '{event_type}' is outside the checked Realtime profile.",
                record,
                path="$.type",
            )
            return
        self.check_common(record, event_type)
        event = record.event
        # Basic type and shape checks for fields where a JSON object alone is not enough.
        for key in ("session", "conversation", "response", "item", "part", "error"):
            if key in event and not isinstance(event[key], Mapping):
                self.add(
                    "event.invalid_field_type",
                    "error",
                    f"Field '{key}' must be an object.",
                    record,
                    path=f"$.{key}",
                )
        for key in (
            "delta",
            "text",
            "transcript",
            "arguments",
            "name",
            "item_id",
            "response_id",
            "call_id",
        ):
            if key in event and not isinstance(event[key], str):
                self.add(
                    "event.invalid_field_type",
                    "error",
                    f"Field '{key}' must be a string.",
                    record,
                    path=f"$.{key}",
                )
        self.validate_indices(record, ("output_index", "content_index"))

        if event_type == "session.created":
            if self.session_created:
                self.add(
                    "session.duplicate_created",
                    "warning",
                    "More than one session.created event was captured.",
                    record,
                )
            self.session_created = True
        elif event_type == "session.updated" and not self.session_created:
            self.add(
                "session.updated_before_created",
                "warning",
                "session.updated precedes session.created in this capture.",
                record,
            )

        if event_type == "input_audio_buffer.append":
            size = self.validate_audio(record, event.get("audio"), field="audio")
            self.audio_buffer_bytes += size
            self.input_audio_bytes += size
        elif event_type == "input_audio_buffer.commit":
            if self.audio_buffer_bytes == 0:
                self.add(
                    "audio.commit_empty",
                    "error",
                    "input_audio_buffer.commit was sent with no appended audio in this capture.",
                    record,
                )
            self.audio_buffer_bytes = 0
        elif event_type == "input_audio_buffer.clear":
            self.audio_buffer_bytes = 0
        elif event_type == "input_audio_buffer.committed":
            self.audio_buffer_bytes = 0
        elif event_type == "input_audio_buffer.speech_started":
            if self.speech_item is not None:
                self.add(
                    "audio.speech_overlap",
                    "warning",
                    "A second speech_started arrived before speech_stopped.",
                    record,
                )
            self.speech_item = (
                event.get("item_id") if isinstance(event.get("item_id"), str) else "?"
            )
        elif event_type == "input_audio_buffer.speech_stopped":
            if self.speech_item is None:
                self.add(
                    "audio.speech_stopped_without_start",
                    "warning",
                    "speech_stopped has no preceding speech_started in this capture.",
                    record,
                )
            self.speech_item = None
            start = event.get("audio_start_ms")
            end = event.get("audio_end_ms")
            if (
                isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(end, int)
                and not isinstance(end, bool)
                and end < start
            ):
                self.add(
                    "audio.invalid_range",
                    "error",
                    "audio_end_ms is earlier than audio_start_ms.",
                    record,
                )
        elif event_type == "input_audio_buffer.timeout_triggered":
            start = event.get("audio_start_ms")
            end = event.get("audio_end_ms")
            if (
                isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(end, int)
                and not isinstance(end, bool)
                and end < start
            ):
                self.add(
                    "audio.invalid_range",
                    "error",
                    "audio_end_ms is earlier than audio_start_ms.",
                    record,
                )

        if event_type in {
            "conversation.item.create",
            "conversation.item.created",
            "conversation.item.added",
            "conversation.item.done",
        }:
            item = event.get("item")
            if isinstance(item, Mapping):
                item_id = item.get("id")
                if isinstance(item_id, str) and item_id:
                    if event_type == "conversation.item.create" and item_id in self.items:
                        self.add(
                            "conversation.duplicate_item",
                            "error",
                            f"Item '{item_id}' is created more than once.",
                            record,
                        )
                    self.items[item_id] = dict(item)
                    if item_id in self.deleted_items:
                        self.add(
                            "conversation.reused_deleted_item",
                            "error",
                            f"Deleted item '{item_id}' appears again.",
                            record,
                        )
                if item.get("type") == "function_call_output":
                    call_id = item.get("call_id")
                    if not isinstance(call_id, str) or not call_id:
                        self.add(
                            "tool.output_missing_call_id",
                            "error",
                            "function_call_output item has no call_id.",
                            record,
                            path="$.item.call_id",
                        )
                    elif not isinstance(item.get("output"), str):
                        self.add(
                            "tool.output_invalid",
                            "error",
                            "function_call_output item must contain a string output.",
                            record,
                            path="$.item.output",
                        )
                    else:
                        self.tool_outputs.add(call_id)
                if item.get("type") == "function_call" and item.get("call_id"):
                    call_id = item.get("call_id")
                    if isinstance(call_id, str):
                        self.tool_outputs.discard(call_id)
        elif event_type in {"conversation.item.delete", "conversation.item.deleted"}:
            item_id = event.get("item_id")
            if isinstance(item_id, str):
                if event_type == "conversation.item.delete" and item_id not in self.items:
                    self.add(
                        "conversation.delete_unknown_item",
                        "warning",
                        f"Item '{item_id}' was not seen earlier in this capture.",
                        record,
                    )
                if event_type == "conversation.item.deleted":
                    self.deleted_items.add(item_id)
        elif event_type == "conversation.item.truncate":
            if event.get("content_index") != 0:
                self.add(
                    "conversation.truncate_content_index",
                    "warning",
                    "The documented Realtime audio truncate operation uses content_index 0.",
                    record,
                )
        elif event_type == "conversation.item.truncated":
            audio_end_ms = event.get("audio_end_ms")
            if (
                isinstance(audio_end_ms, int)
                and not isinstance(audio_end_ms, bool)
                and audio_end_ms < 0
            ):
                self.add(
                    "conversation.invalid_truncation",
                    "error",
                    "audio_end_ms cannot be negative.",
                    record,
                )

        if event_type == "conversation.item.input_audio_transcription.delta":
            item_id = event.get("item_id")
            content_index = event.get("content_index", 0)
            if (
                isinstance(item_id, str)
                and isinstance(content_index, int)
                and not isinstance(content_index, bool)
                and isinstance(event.get("delta"), str)
            ):
                transcript_key: tuple[str, int] = (item_id, content_index)
                self.transcripts[transcript_key] = (
                    self.transcripts.get(transcript_key, "") + event["delta"]
                )
        elif event_type == "conversation.item.input_audio_transcription.completed":
            item_id = event.get("item_id")
            content_index = event.get("content_index", 0)
            if (
                isinstance(item_id, str)
                and isinstance(content_index, int)
                and not isinstance(content_index, bool)
                and isinstance(event.get("transcript"), str)
            ):
                transcript_key = (item_id, content_index)
                prior = self.transcripts.get(transcript_key)
                if prior is not None and prior != event["transcript"]:
                    self.add(
                        "transcript.done_mismatch",
                        "warning",
                        "Completed transcript differs from concatenated delta text.",
                        record,
                    )

        if event_type == "response.create":
            self.client_response_creates += 1
        elif event_type == "response.cancel":
            requested = event.get("response_id")
            if requested is None and not any(
                state.done_line is None for state in self.responses.values()
            ):
                self.add(
                    "response.cancel_without_active",
                    "warning",
                    "response.cancel has no active response in this capture.",
                    record,
                )
        elif event_type == "response.created":
            state = self.response(record, create=True)
            if state is not None:
                if state.created_line is not None:
                    self.add(
                        "response.duplicate_created",
                        "error",
                        "response.created repeats the same response ID.",
                        record,
                    )
                state.created_line = record.line
                response = event.get("response")
                if isinstance(response, Mapping):
                    status = response.get("status")
                    if isinstance(status, str):
                        state.status = status
        elif event_type == "response.done":
            state = self.require_response(record)
            response = event.get("response")
            if isinstance(response, Mapping):
                status = response.get("status")
                if not isinstance(status, str):
                    self.add(
                        "response.missing_status",
                        "error",
                        "response.done.response.status is required.",
                        record,
                        path="$.response.status",
                    )
                elif status not in KNOWN_RESPONSE_STATUSES:
                    self.add(
                        "response.unknown_status",
                        "error",
                        f"Unknown response status '{status}'.",
                        record,
                        path="$.response.status",
                    )
                elif status == "in_progress":
                    self.add(
                        "response.non_terminal_done",
                        "error",
                        "response.done must carry a terminal response status.",
                        record,
                        path="$.response.status",
                    )
                if state is not None:
                    state.status = status if isinstance(status, str) else state.status
            if state is not None:
                if state.done_line is not None:
                    self.add(
                        "response.duplicate_done",
                        "error",
                        "response.done repeats the same response ID.",
                        record,
                    )
                state.done_line = record.line
                if any(not part.done for part in state.parts.values()):
                    self.add(
                        "response.open_stream",
                        "warning",
                        "response.done arrived while one or more content parts were still open.",
                        record,
                    )
        elif event_type in {"response.output_item.added", "response.output_item.done"}:
            state = self.require_response(record)
            output_index = event.get("output_index")
            if (
                state is not None
                and isinstance(output_index, int)
                and not isinstance(output_index, bool)
            ):
                output_index_value: int = output_index
                item = event.get("item")
                item_id = item.get("id") if isinstance(item, Mapping) else None
                if event_type.endswith("added"):
                    if output_index_value in state.output_items:
                        self.add(
                            "response.duplicate_output_item",
                            "error",
                            "output_index is added more than once for a response.",
                            record,
                        )
                    state.output_items[output_index_value] = (
                        item_id if isinstance(item_id, str) else "?"
                    )
                elif output_index_value in state.output_items_done:
                    self.add(
                        "response.duplicate_output_item_done",
                        "error",
                        "output item is marked done more than once.",
                        record,
                    )
                else:
                    state.output_items_done.add(output_index_value)
        elif event_type in {"response.content_part.added", "response.content_part.done"}:
            state = self.require_response(record)
            if state is not None:
                part = self.part(state, record)
                if event_type.endswith("added"):
                    if part.started:
                        self.add(
                            "stream.duplicate_part_start",
                            "error",
                            "Content part is added more than once.",
                            record,
                        )
                    part.started = True
                elif part.done:
                    self.add(
                        "stream.duplicate_part_done",
                        "error",
                        "Content part is marked done more than once.",
                        record,
                    )
                else:
                    part.done = True
        elif event_type in {"response.output_text.delta", "response.output_text.done"}:
            state = self.require_response(record)
            if state is not None:
                part = self.part(state, record)
                if not part.started:
                    self.add(
                        "stream.delta_before_part",
                        "warning",
                        "Text output arrived before response.content_part.added.",
                        record,
                    )
                if part.done:
                    self.add(
                        "stream.delta_after_done",
                        "error",
                        "Text output arrived after its content part was done.",
                        record,
                    )
                if event_type.endswith("delta") and isinstance(event.get("delta"), str):
                    part.text += event["delta"]
                    state.output_text += event["delta"]
                elif (
                    isinstance(event.get("text"), str) and part.text and part.text != event["text"]
                ):
                    self.add(
                        "stream.done_mismatch",
                        "warning",
                        "Final text differs from concatenated text deltas.",
                        record,
                    )
        elif event_type in {"response.output_audio.delta", "response.output_audio.done"}:
            state = self.require_response(record)
            size = 0
            if event_type.endswith("delta"):
                size = self.validate_audio(record, event.get("delta"), field="delta")
            if state is not None:
                part = self.part(state, record)
                if not part.started:
                    self.add(
                        "stream.delta_before_part",
                        "warning",
                        "Audio output arrived before response.content_part.added.",
                        record,
                    )
                if part.done:
                    self.add(
                        "stream.delta_after_done",
                        "error",
                        "Audio output arrived after its content part was done.",
                        record,
                    )
                if event_type.endswith("delta"):
                    part.audio_bytes += size
                    state.audio_bytes += size
        elif event_type in {
            "response.output_audio_transcript.delta",
            "response.output_audio_transcript.done",
        }:
            state = self.require_response(record)
            if state is not None:
                part = self.part(state, record)
                if not part.started:
                    self.add(
                        "stream.delta_before_part",
                        "warning",
                        "Audio transcript arrived before response.content_part.added.",
                        record,
                    )
                if part.done:
                    self.add(
                        "stream.delta_after_done",
                        "error",
                        "Audio transcript arrived after its content part was done.",
                        record,
                    )
                if event_type.endswith("delta") and isinstance(event.get("delta"), str):
                    part.transcript += event["delta"]
                    state.audio_transcript += event["delta"]
                elif (
                    isinstance(event.get("transcript"), str)
                    and part.transcript
                    and part.transcript != event["transcript"]
                ):
                    self.add(
                        "stream.done_mismatch",
                        "warning",
                        "Final audio transcript differs from concatenated deltas.",
                        record,
                    )
        elif event_type in {
            "response.function_call_arguments.delta",
            "response.function_call_arguments.done",
        }:
            state = self.require_response(record)
            call_id = event.get("call_id")
            if isinstance(call_id, str):
                if event_type.endswith("delta") and isinstance(event.get("delta"), str):
                    if state is not None:
                        state.tool_arguments[call_id] = (
                            state.tool_arguments.get(call_id, "") + event["delta"]
                        )
                else:
                    arguments = event.get("arguments")
                    if isinstance(arguments, str):
                        previous = state.tool_arguments.get(call_id) if state is not None else None
                        if previous and previous != arguments:
                            self.add(
                                "tool.arguments_done_mismatch",
                                "warning",
                                "Final tool arguments differ from concatenated deltas.",
                                record,
                            )
                        try:
                            parsed = json.loads(arguments)
                            if not isinstance(parsed, dict):
                                self.add(
                                    "tool.arguments_not_object",
                                    "warning",
                                    "Tool arguments are valid JSON but not an object.",
                                    record,
                                )
                        except json.JSONDecodeError:
                            self.add(
                                "tool.arguments_invalid_json",
                                "error",
                                "Final tool arguments are not valid JSON.",
                                record,
                                path="$.arguments",
                            )
                        if state is not None:
                            state.tool_argument_done.add(call_id)
                            if isinstance(event.get("name"), str):
                                state.tool_names[call_id] = event["name"]

    def finish(self) -> Report:
        if self.audio_buffer_bytes:
            self.add(
                "audio.buffer_uncommitted",
                "warning",
                "The capture ends with audio still buffered and uncommitted.",
            )
        if self.speech_item is not None:
            self.add(
                "audio.speech_unclosed",
                "warning",
                "The capture ends after speech_started without speech_stopped.",
            )
        if self.server_events_seen and not self.session_created:
            self.add(
                "session.missing_created",
                "warning",
                "Server events were captured without session.created.",
            )
        response_rows: list[dict[str, Any]] = []
        total_text = 0
        total_transcript = 0
        total_audio = 0
        total_input_transcript = sum(len(value) for value in self.transcripts.values())
        completed = 0
        for state in self.responses.values():
            if state.done_line is None:
                self.add(
                    "response.missing_done",
                    "warning",
                    f"Response '{state.response_id}' has no response.done in this capture.",
                )
            if state.status in TERMINAL_RESPONSE_STATUSES:
                completed += 1
            total_text += len(state.output_text)
            total_transcript += len(state.audio_transcript)
            total_audio += state.audio_bytes
            row: dict[str, Any] = {
                "response_id": state.response_id,
                "status": state.status,
                "first_line": state.first_line,
                "created_line": state.created_line,
                "done_line": state.done_line,
                "text_chars": len(state.output_text),
                "audio_transcript_chars": len(state.audio_transcript),
                "audio_bytes": state.audio_bytes,
                "tool_calls": len(state.tool_argument_done),
                "duration_ms": None,
            }
            if self.include_content:
                row["text"] = state.output_text
                row["audio_transcript"] = state.audio_transcript
            response_rows.append(row)
        self.metrics = {
            "events": self.records,
            "known_events": self.known_events,
            "unknown_events": self.unknown_events,
            "responses": len(self.responses),
            "terminal_responses": completed,
            "client_response_creates": self.client_response_creates,
            "text_chars": total_text,
            "audio_transcript_chars": total_transcript,
            "audio_bytes": total_audio,
            "input_audio_bytes": self.input_audio_bytes,
            "input_transcript_chars": total_input_transcript,
            "findings": len(self.findings),
            "errors": sum(finding.severity == "error" for finding in self.findings),
            "warnings": sum(finding.severity == "warning" for finding in self.findings),
        }
        return Report(self.findings, self.metrics, response_rows, self.include_content)


def validate_transcript(
    records: Iterable[EventRecord],
    *,
    parse_findings: Iterable[Finding] = (),
    strict_unknown: bool = False,
    include_content: bool = False,
) -> Report:
    validator = _Validator(strict_unknown=strict_unknown, include_content=include_content)
    validator.findings.extend(parse_findings)
    for record in records:
        validator.process(record)
    return validator.finish()


def validate_text(
    text: str,
    *,
    strict_unknown: bool = False,
    include_content: bool = False,
) -> Report:
    records, findings = parse_lines(StringIO(text))
    return validate_transcript(
        records,
        parse_findings=findings,
        strict_unknown=strict_unknown,
        include_content=include_content,
    )


def validate_stream(
    stream: Any,
    *,
    strict_unknown: bool = False,
    include_content: bool = False,
) -> Report:
    records, findings = parse_stream(stream)
    return validate_transcript(
        records,
        parse_findings=findings,
        strict_unknown=strict_unknown,
        include_content=include_content,
    )
