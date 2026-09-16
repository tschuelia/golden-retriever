# Recover the HTML hidden inside RTF

otteRTF 🦦 extracts the original HTML or plain text carried by a Microsoft
RTF encapsulation document. This is the `\fromhtml1` / `\fromtext` format
specified by
[MS-OXRTFEX](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfex/411d0d58-49f7-496c-b8c3-5859b045f6cf),
most often encountered through a message's `PidTagRtfCompressed` property.

The important idea is that this is not general RTF-to-HTML conversion. The RTF
contains two interleaved views of one message:

- fragments copied from the original HTML; and
- RTF produced so an RTF-only reader can display roughly the same body.

A de-encapsulator selects the original fragments and shared text while discarding
the RTF-only approximation. That makes retrieval deterministic; it does not need
to infer HTML formatting from RTF.

## Where to start

- [Getting started](getting-started.md) shows the public API.
- [Message files and RTF](message-files.md) explains how this payload relates to
  MAPI and `.msg` storage.
- [HTML encapsulation](encapsulation.md) introduces enough RTF syntax to read an
  encapsulated document by hand.
- [Extraction pipeline](extraction.md) maps the specification to this package.
- [Encodings and Unicode](encodings.md) covers the most failure-prone part of the
  format.
- [Diagnostics and security](diagnostics-and-security.md) explains recovery,
  strict mode, and trust boundaries.

## Supported input

The input is an in-memory `bytes` object containing **uncompressed RTF**. It must
have an encapsulation marker in its header:

- `\fromhtml1` for HTML; or
- `\fromtext` for plain text.

Ordinary RTF is recognized but not rendered. Parsing an `.msg` compound file and
decompressing `PidTagRtfCompressed` are upstream tasks.

## Design guarantees

- Standard-library-only runtime.
- Byte-level, single-pass parsing with no recursive descent through RTF groups.
- Font-aware Windows code-page decoding.
- Explicit diagnostics for every tolerated defect.
- No network access, attachment lookup, HTML execution, or sanitization.

Releases follow semantic versioning. During the `0.x` series, public APIs can
change between minor releases; incompatible changes are documented in the
release notes.
