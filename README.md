# realtime-contract

Offline contract and lifecycle checks for OpenAI Realtime API event transcripts.

Realtime sessions are not ordinary request/response calls. A WebSocket capture can contain
hundreds of valid-looking JSON objects while the session is still broken: a response delta can
arrive after its content is complete, a tool argument can be truncated, an audio buffer can be
committed while empty, or a response can close without a terminal event. Those failures are
usually discovered by a voice UI or an SDK exception long after the useful evidence has scrolled
past.

`realtime-contract` turns a saved JSONL capture into a deterministic state-machine report. It
checks the documented Realtime GA event subset, correlates response/item/content IDs, reconstructs
text and tool arguments, counts audio bytes, and gives each finding a line number and stable code.
It never opens a WebSocket, calls a model, executes tool arguments, or sends a transcript anywhere.

## Quick start

Requires Python 3.10+.

```console
$ python -m venv .venv
$ .venv/bin/python -m pip install -e .
$ realtime-contract check examples/valid-text.jsonl
Realtime Contract: PASS
Events 14 | known 14 | unknown 0 | responses 1
Output: 12 text chars | 0 transcript chars | 0 audio bytes
Responses:
  resp_text  completed  text=12 chars  audio=0 bytes  tools=0
Findings: none
```

Use stdin in a shell pipeline:

```console
$ cat capture.jsonl | realtime-contract check - --format markdown > report.md
```

CI can consume JSON or SARIF. The command exits `1` for errors and `0` for a clean report; use
`--fail-on-warning` when a capture must be fully closed and known.

```console
$ realtime-contract check capture.jsonl --format sarif --output realtime.sarif
$ realtime-contract check capture.jsonl --strict-unknown
```

## Input

One JSON object per line may be either a raw event:

```json
{"type":"response.output_text.delta","event_id":"e9","response_id":"resp_1","item_id":"item_1","output_index":0,"content_index":0,"delta":"Hi"}
```

or a capture envelope. Envelopes keep direction and timing without changing the event payload:

```json
{"source":"server","timestamp":1710000000.125,"event":{"type":"session.created","event_id":"e1","session":{"id":"sess_1","type":"realtime"}}}
```

`source` accepts `client`/`outbound` and `server`/`inbound`. `timestamp`/`time`/`ts` may be Unix
seconds, Unix milliseconds, or an ISO-8601 string. A raw event without a source is still checked;
direction checks are simply skipped.

The parser also accepts an envelope with a JSON string `data` field. Blank lines are ignored.
Malformed rows are reported without echoing their raw contents, which keeps accidental prompts or
credentials out of the report.

## What it checks

The built-in profile covers the commonly used GA event lifecycle:

- session and conversation creation/update/delete/truncate events;
- input audio append/clear/commit, VAD speech boundaries, and transcription deltas/completions;
- response creation/cancellation/completion;
- output item and content-part ordering;
- text, audio, and audio-transcript deltas and terminal events;
- streamed function-call arguments and JSON validity;
- server error and rate-limit envelopes.

Diagnostics include:

- missing fields, wrong directions, wrong JSON types, negative indexes, duplicate event IDs;
- empty audio commits, invalid base64, impossible speech ranges, and unclosed buffers;
- response IDs that never appeared, repeated `response.created`/`response.done`, and non-terminal
  `response.done` statuses;
- deltas after a completed part, duplicate part boundaries, final text/transcript mismatches, and
  invalid function-call arguments;
- unknown event types (warnings by default, errors with `--strict-unknown`), so additive provider
  events remain inspectable without pretending they were checked.

Reports intentionally contain counts and identifiers, not payloads. Add `--include-content` only
when a local JSON or library report needs reconstructed text or audio transcripts; treat that output
as sensitive. Markdown remains summary-only.

## Why this is a separate tool

The official OpenAI clients and Realtime Console are useful for connecting, rendering, and
normalizing live sessions. SDK testing helpers can script an application's normalized model
boundary. They do not provide a portable, post-run check for a raw WebSocket transcript that a
team can put in CI or attach to a bug report.

`stream-contract` in the surrounding workspace audits HTTP/SSE Chat Completions and Responses
streams; `responses-chain` audits non-realtime Responses state; `tool-call-audit` audits tool
arguments against a schema. This project owns the missing Realtime transport boundary and its
cross-event lifecycle. It complements those tools rather than replacing them.

## Why frontier-AI developers would care

Voice and multimodal agents use long-lived Realtime sessions where audio, transcripts, tool calls,
interruptions, and response state interleave. Reproducing a bug from a raw capture is cheaper and
more reliable than asking a model to fail in the same way again. A line-addressable, payload-safe
contract report can run beside WebSocket relays, OpenAI Agents SDK integrations, local Realtime
servers, and compatibility layers such as vLLM-Omni without a provider account or GPU.

## Offline and optional integrations

Everything in `realtime-contract check` works offline against a file or stdin. The project has no
network client, telemetry, account system, hosted dashboard, or required model. A caller may feed
it captures produced by OpenAI, Azure, a local Realtime-compatible server, or a test double, but
the validator does not assume that any provider is correct or official.

## Library API

```python
from realtime_contract import validate_text

report = validate_text(open("capture.jsonl", encoding="utf-8").read())
if report.errors:
    raise SystemExit("Realtime contract failed")
print(report.metrics["audio_bytes"])
```

`validate_transcript` accepts decoded `EventRecord` objects. Renderers for JSON, Markdown, text,
and SARIF live in `realtime_contract.render`.

## Development

```console
$ uv sync --extra dev
$ uv run pytest
$ uv run ruff check .
$ uv run ruff format --check .
$ uv run mypy
```

The fixture-first suite uses no API key, network, audio device, or model. Fixtures include valid
text, audio, tool-call, interruption, unknown-event, malformed, and truncated sessions.

## Security and privacy

See [SECURITY.md](SECURITY.md). The validator treats every event field as untrusted data. It never
executes `arguments`, `output`, `audio`, paths, or shell-like strings. Findings omit raw malformed
lines and reconstructed content is excluded unless explicitly requested.

## License

MIT. See [LICENSE](LICENSE).

## Evidence and references

The opportunity is grounded in public protocol and issue evidence:

- [OpenAI Node Realtime guide](https://github.com/openai/openai-node/blob/main/docs/realtime.md)
  describes bidirectional client/server events and warns that a socket can close before
  `response.done`; its generated types define the response, audio, transcript, and function-call
  event fields this profile checks.
- [OpenAI Realtime Console issue #62](https://github.com/openai/openai-realtime-console/issues/62)
  shows a real captured session with interleaved audio, transcript, VAD, cancellation, truncation,
  and response lifecycle events while debugging a stopped console.
- [openai-python issue #2698](https://github.com/openai/openai-python/issues/2698) records a
  mismatched Realtime audio-transcript event type that surfaced as a typed parsing failure.
- [Hugging Face speech-to-speech issue #447](https://github.com/huggingface/speech-to-speech/issues/447)
  documents a `content_index` sequencing bug in streamed audio deltas.
- The [OpenAI Agents SDK testing guide](https://openai.github.io/openai-agents-python/testing/)
  explicitly separates normalized in-memory Realtime tests from raw transport, authentication,
  network recovery, and audio behavior—the boundary this utility checks from saved evidence.
