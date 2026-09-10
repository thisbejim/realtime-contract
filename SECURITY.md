# Security policy

## Data handling

`realtime-contract` processes input locally. It does not make network requests, collect telemetry,
write a cache, or upload event payloads. Reports omit raw lines and reconstructed content by
default. `--include-content` is an explicit opt-in and may expose prompts, transcripts, tool
arguments, or other sensitive data in the chosen report file.

## Untrusted event content

All event fields are treated as data. The validator never executes function arguments, tool output,
audio, paths, URLs, or shell-like strings. Base64 audio is decoded only for validation and byte
counting. JSON parsing uses the standard library and does not use unsafe deserialization.

## Reporting a vulnerability

Please open a private GitHub security advisory if one is enabled for the repository. Otherwise open
an issue with a minimal reproduction that contains no credentials, customer prompts, audio, or
personal data. Do not attach an unredacted production transcript.
