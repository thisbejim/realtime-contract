"""The documented Realtime GA event subset checked by this project.

This is intentionally a conservative profile rather than a claim to model every field in the
provider's generated SDK. Unknown events are retained as warnings so additive protocol changes
do not make a healthy transcript fail by default.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EventSpec:
    source: str | None = None
    required: tuple[str, ...] = ()


def _spec(source: str | None = None, *required: str) -> EventSpec:
    return EventSpec(source, required)


SPECS: dict[str, EventSpec] = {
    # Session and conversation lifecycle.
    "session.created": _spec("server", "session"),
    "session.updated": _spec("server", "session"),
    "session.update": _spec("client", "session"),
    "transcription_session.update": _spec("client", "session"),
    "transcription_session.updated": _spec("server", "session"),
    "conversation.created": _spec("server", "conversation"),
    "conversation.item.create": _spec("client", "item"),
    "conversation.item.created": _spec("server", "item"),
    "conversation.item.added": _spec("server", "item"),
    "conversation.item.done": _spec("server", "item"),
    "conversation.item.delete": _spec("client", "item_id"),
    "conversation.item.deleted": _spec("server", "item_id"),
    "conversation.item.retrieve": _spec("client", "item_id"),
    "conversation.item.retrieved": _spec("server", "item"),
    "conversation.item.truncate": _spec("client", "item_id", "content_index", "audio_end_ms"),
    "conversation.item.truncated": _spec("server", "item_id", "content_index", "audio_end_ms"),
    # Input audio and transcription.
    "input_audio_buffer.append": _spec("client", "audio"),
    "input_audio_buffer.clear": _spec("client"),
    "input_audio_buffer.cleared": _spec("server"),
    "input_audio_buffer.commit": _spec("client"),
    "input_audio_buffer.committed": _spec("server", "item_id"),
    "input_audio_buffer.speech_started": _spec("server", "audio_start_ms", "item_id"),
    "input_audio_buffer.speech_stopped": _spec("server", "audio_end_ms", "item_id"),
    "input_audio_buffer.timeout_triggered": _spec(
        "server", "audio_start_ms", "audio_end_ms", "item_id"
    ),
    "conversation.item.input_audio_transcription.delta": _spec("server", "item_id"),
    "conversation.item.input_audio_transcription.completed": _spec(
        "server", "item_id", "transcript"
    ),
    "conversation.item.input_audio_transcription.failed": _spec("server", "item_id", "error"),
    "conversation.item.input_audio_transcription.segment": _spec(
        "server", "item_id", "content_index", "id", "start", "end", "speaker", "text"
    ),
    # Response lifecycle and streamed output.
    "response.create": _spec("client"),
    "response.cancel": _spec("client"),
    "response.created": _spec("server", "response"),
    "response.done": _spec("server", "response"),
    "response.output_item.added": _spec("server", "response_id", "output_index", "item"),
    "response.output_item.done": _spec("server", "response_id", "output_index", "item"),
    "response.content_part.added": _spec(
        "server", "response_id", "item_id", "output_index", "content_index", "part"
    ),
    "response.content_part.done": _spec(
        "server", "response_id", "item_id", "output_index", "content_index", "part"
    ),
    "response.output_text.delta": _spec(
        "server", "response_id", "item_id", "output_index", "content_index", "delta"
    ),
    "response.output_text.done": _spec(
        "server", "response_id", "item_id", "output_index", "content_index", "text"
    ),
    "response.output_audio.delta": _spec(
        "server", "response_id", "item_id", "output_index", "content_index", "delta"
    ),
    "response.output_audio.done": _spec(
        "server", "response_id", "item_id", "output_index", "content_index"
    ),
    "response.output_audio_transcript.delta": _spec(
        "server", "response_id", "item_id", "output_index", "content_index", "delta"
    ),
    "response.output_audio_transcript.done": _spec(
        "server", "response_id", "item_id", "output_index", "content_index", "transcript"
    ),
    "response.function_call_arguments.delta": _spec(
        "server", "response_id", "item_id", "output_index", "call_id", "delta"
    ),
    "response.function_call_arguments.done": _spec(
        "server", "response_id", "item_id", "output_index", "call_id", "name", "arguments"
    ),
    "rate_limits.updated": _spec("server", "rate_limits"),
    "error": _spec("server", "error"),
}

SERVER_EVENTS = {name for name, spec in SPECS.items() if spec.source == "server"}

TERMINAL_RESPONSE_STATUSES = {"completed", "cancelled", "failed", "incomplete"}
KNOWN_RESPONSE_STATUSES = TERMINAL_RESPONSE_STATUSES | {"in_progress"}
