# Changelog

## 0.1.0 — 2026-09-11

Initial public release.

- Offline JSONL and stdin validation for the documented OpenAI Realtime GA event subset.
- Cross-event state checks for sessions, audio buffers, VAD ranges, conversations, responses,
  output parts, transcripts, and streamed function-call arguments.
- Payload-safe text, Markdown, JSON, and SARIF reports with stable finding codes and line numbers.
- Explicit unknown-event warnings, strict mode, sensitive-content opt-in, fixtures, tests, and CI.
