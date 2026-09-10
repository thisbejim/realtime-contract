# Product specification: realtime-contract

## Target developer

An engineer operating a voice, audio, or multimodal agent over the OpenAI Realtime WebSocket
protocol, including maintainers of relays, SDK adapters, local compatible servers, and CI fixtures.

## Problem

When a Realtime session misbehaves, the only durable evidence is often a JSON event log. Individual
events can validate in isolation while the sequence violates the lifecycle (for example, an audio
delta arrives after its part is done, a function-call argument is truncated, or a socket closes
before `response.done`). Developers otherwise write one-off notebook/state-machine scripts or
reproduce the failure against a live model.

## Evidence

Public sources show the recurring job:

1. The OpenAI Node guide documents a bidirectional event protocol and says a WebSocket can close
   before `response.done`, requiring clients to track terminal state.
2. The OpenAI Realtime Console issue tracker contains a long, manually inspected event timeline
   covering VAD, cancellation, truncation, audio, transcripts, and multiple response lifecycles.
3. The OpenAI Python SDK issue tracker records typed parsing failures caused by a mismatched audio
   transcript event name.
4. The Hugging Face speech-to-speech tracker records `content_index` sequencing errors in audio
   deltas.
5. The OpenAI Agents SDK testing guide says normalized Realtime tests do not cover raw provider
   events, authentication, network recovery, or audio transport.

## Existing workflow and alternatives

- OpenAI Realtime Console: excellent interactive inspector, but requires a running app/API session
  and does not act as a portable CI gate for an already captured transcript.
- OpenAI Node/Python SDKs: typed event parsing and normalized testing are useful at runtime, but
  they stop at client behavior and do not emit a provider-neutral post-run lifecycle report.
- OpenAI Agents SDK scripted Realtime model: deterministic orchestration tests, intentionally below
  the raw transport boundary.
- Generic JSON/SSE validators: can check syntax, not cross-event IDs, item/part ordering, audio
  buffer state, or response terminal semantics.

## Gap and product thesis

For Realtime/voice-agent engineers, `realtime-contract` turns a captured WebSocket transcript into
a line-addressable, payload-safe lifecycle report better than a console or SDK because it is local,
deterministic, CI-friendly, and designed for the raw event boundary.

## Core workflow

```text
JSONL/WebSocket capture
        ↓
realtime-contract check
        ↓
state-machine findings + response summary + JSON/Markdown/SARIF
```

## Non-goals

- Connecting to a provider, sending prompts, or claiming compatibility certification.
- Audio playback, speech-quality scoring, model-quality evaluation, or latency benchmarking.
- Executing tool calls, repairing a transcript, or inferring intent from its content.
- Modeling every future or provider-specific Realtime event; unknown events remain explicit.

## Interface and independence

The primary interface is a Unix-style CLI with stdin/stdout and meaningful exit codes. The Python
library is a thin wrapper for test suites and custom capture readers. Core validation requires no
account, paid API, network, database, telemetry, or proprietary dependency.
