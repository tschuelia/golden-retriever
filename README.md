# golden-retriever

[![CI](https://github.com/tschuelia/golden-retriever/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/tschuelia/golden-retriever/actions/workflows/ci.yml)

Recover the original HTML from RTF-encapsulated HTML — the `\fromhtml1` form that
Exchange and Outlook write into an email's `PidTagRtfCompressed` stream.

The extraction follows
[MS-OXRTFEX](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfex/906fbb0f-2467-490e-8c3e-bdc31c5e9d35)
and the [RTF Specification 1.9.1](https://go.microsoft.com/fwlink/?LinkId=120924).

> **Status: in development.** The API below is the target surface and is not yet
> complete. See [Implementation status](#implementation-status).

## Quickstart

```python
import golden_retriever as gr

raw_rtf: bytes = ...  # e.g. from an MSG's decompressed PidTagRtfCompressed stream

if gr.detect_content_type(raw_rtf) is gr.ContentType.NATIVE_RTF:
    ...  # not encapsulated content; nothing to de-encapsulate

result = gr.deencapsulate(raw_rtf)
print(result.content_type)  # ContentType.HTML or ContentType.TEXT
print(
    result.declared_html_charset
)  # what the extracted HTML claims, e.g. "windows-1252"
print(result.body)  # the extracted HTML or plain text, as str
```

`deencapsulate` returns `str`, so the extracted markup is already decoded. Its
`<meta>` charset declaration is left exactly as the producer wrote it — if you
are about to write the result out as UTF-8, fix the declaration first:

```python
html = gr.normalize_charset_declaration(result.body, "utf-8")
open("mail.html", "w", encoding="utf-8").write(html)
```

Everything that can go wrong raises a subclass of `GoldenRetrieverError`:

```python
try:
    result = gr.deencapsulate(raw_rtf)
except gr.NotEncapsulatedRtfError:
    ...  # native RTF, no encapsulated content
except gr.GoldenRetrieverError:
    ...  # malformed input
```

By default, the parser degrades rather than refuses: undecodable bytes become
U+FFFD, unknown fonts fall back to the document code page, and structural damage
is recorded in `result.diagnostics`. Pass `strict=True` to turn structural
problems into exceptions instead. `strict` never changes what characters come
out — only whether a problem is raised or reported.

## Specification conformance

| Section                                | Status                                              |
| -------------------------------------- | --------------------------------------------------- |
| §2.2.3.1 Recognizing encapsulated data | implemented                                         |
| §2.2.3.2 De-encapsulating HTML         | implemented                                         |
| §2.2.3.3 De-encapsulating plain text   | implemented                                         |
| §2.2.3.4 Attachment integration        | not implemented (see [Out of scope](#out-of-scope)) |

### Documented deviations

- **`\_`.** MS-OXRTFEX §2.1.3.1.4.2 maps `\_` to `&shy;` (U+00AD) inside HTMLTAG
  content, while RTF 1.9.1 defines `\_` as the _nonbreaking_ hyphen (U+2011) and
  `\-` as the optional hyphen (U+00AD). Both are honored in their own context:
  U+00AD inside HTMLTAG content, U+2011 in document body text. `\-` is U+00AD
  everywhere.
- **`\fcharset0` / `\fcharset1`.** Resolved to the document's `\ansicpg` code
  page rather than a hard-coded 1252. `ANSI_CHARSET` means "the system ANSI code
  page", and `\ansicpg` is the document's declaration of what that was. Only
  when `\ansicpg` is absent does the `fallback_codepage` argument apply.
- **Leniency.** Per MS-OXRTFEX Appendix A `<13>`/`<14>`, missing `{\rtf1` and a
  `\*`-less `\htmltag` are tolerated rather than rejected, with a diagnostic.
  `strict=True` rejects them.
- **HTMLTAG content uses the document code page.** The bytes of a tag decode
  with `\ansicpg` whatever `\fN` is in effect. MS-OXRTFEX §2.2.3.2 calls that
  "the default code page, as specified in the RTF header", and §2.1.3.1.4.2's
  CONTENT is a fragment of the original HTML rather than message text that a font
  describes how to render.
- **HTMLRTF inside HTMLTAG.** Entering an HTMLTAG destination clears HTMLRTF
  suppression for the duration of that group. A strict reading of §2.1.3.1.3
  would carry suppression in, but HTMLRTF exists to hide RTF-only markup and
  HTMLTAG content _is_ the HTML output. Real producers never nest the two, so the
  behaviors are indistinguishable on real input; this choice fails toward
  keeping content rather than silently dropping it.
- **State is tracked while suppressed.** §2.2.3.2 requires the current font to be
  tracked even where `\fN` sits inside a fragment an HTMLRTF control word
  disabled. The same treatment is given to the other control words that copy
  nothing and only carry state — `\ucN`, `\ansicpgN`, `\deffN`, and a group's
  destination, including `{\fonttbl…}`. Suppression stops output, not
  bookkeeping: losing one of these mojibakes or duplicates content that was
  never suppressed at all.
- **`\uN` is never skippable data.** RTF 1.9.1 counts "any RTF control word or
  symbol" as one character of the ANSI representation to be skipped after a
  `\uN`. A following `\uN` is exempt here, because skippable data is by
  definition an _ANSI_ representation and a `\uN` is not one — it is a character
  with no other spelling in the document. It is also what makes a surrogate pair
  written as `\u-10179\u-8704`, with no ANSI representation between the halves,
  come out as one character.

## Security

Treat both the input and the output as untrusted.

- The returned HTML is **not sanitized**, and this package will never sanitize
  it. Deciding what markup is acceptable is the caller's policy, not a parser's.
  If the result reaches a browser, run it through a sanitizer first.
- Never interpolate the result into a page, a shell command, or a template
  without escaping it for that context.
- No network access is ever performed. `\htmlbase`, `cid:` references, and
  external URLs are not resolved, fetched, or validated.
- The parser is single-pass and allocates proportionally to its input; it does
  not recurse on group nesting, so deeply nested input cannot exhaust the stack.

## Out of scope

- **Attachment and `cid:` resolution** (MS-OXRTFEX §2.2.3.4). Inline images stay
  as `cid:` references; mapping those to attachments needs the containing
  message, which this package never sees.
- **Native RTF rendering.** If the RTF is not encapsulated HTML or text, this is
  the wrong tool — `detect_content_type` tells you so.
- **HTML sanitization.** See [Security](#security).
- **RTF decompression.** `PidTagRtfCompressed` must already be decompressed;
  this package takes uncompressed RTF bytes.

## Provenance and licensing

golden-retriever is MIT licensed and has no runtime dependencies, so a downstream
license audit only ever sees `MIT`.

The implemented behavior is derived from three published Microsoft
specifications:

- [MS-OXRTFEX](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfex/906fbb0f-2467-490e-8c3e-bdc31c5e9d35)
- [Rich Text Format (RTF) Specification, version 1.9.1](https://go.microsoft.com/fwlink/?LinkId=120924)
- [Code Page Identifiers](https://learn.microsoft.com/en-us/windows/win32/intl/code-page-identifiers)

## Implementation status

Tracked against the module layout, not the spec:

- [ ] `exceptions.py`, `result.py` — public types
- [ ] `codepages.py` — `\fcharset` and `\ansicpg` resolution
- [ ] `charmap.py` — control word and control symbol tables
- [ ] `tokenizer.py` — byte-level RTF lexer
- [ ] `detect.py` — §2.2.3.1 recognition
- [ ] `emitter.py` — deferred decoding
- [ ] `groups.py` — group state and destination classification
- [ ] `deencapsulator.py` — §2.2.3.2 and §2.2.3.3 drivers
- [ ] `html_meta.py` — charset declaration helpers

## Development

Install the development environment and the package:

```console
pixi install
pixi run postinstall
```

Run the tests and quality checks:

```console
pixi run test
pixi run -e lint lint
```

`pixi run -e lint lint` runs everything CI runs: ruff, mypy, docformatter,
prettier, taplo, typos and zizmor. Install it as a pre-commit hook with
`pixi run -e lint pre-commit-install`.

The test suite is also available for every supported Python version:

```console
pixi run -e py312 test
pixi run -e py313 test
pixi run -e py314 test
```

Performance checks are marked `slow` and deselected by default:

```console
pixi run test-slow
```
