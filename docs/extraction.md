# Extraction pipeline

The implementation follows MS-OXRTFEX §§2.2.3.1–2.2.3.3 as one streaming reader.
HTML and plain-text modes share the RTF machinery; HTML adds `HTMLTAG` handling.

## 1. Recognize the body type

`detect_content_type` tokenizes a bounded prefix. Within the default ten-token
window it accepts:

- `\fromhtml1` as HTML;
- `\fromtext` without a parameter as plain text; or
- neither as native RTF.

Detection ends when it sees a token other than a group start or control word,
except insignificant whitespace. A missing `\rtf1` heading is reported
separately so legacy input can still be recovered. This implements MS-OXRTFEX
§2.2.3.1 and Appendix A `<13>`/`<14>`.

## 2. Tokenize bytes, not decoded text

`tokenizer.py` recognizes group delimiters, control words, control symbols,
hexadecimal byte escapes, raw text runs, and `\binN` payloads. It consumes a
control word's optional delimiter and ignores bare CR/LF as required by RTF 1.9.1.

Decoding before tokenization would be incorrect: `\'HH` is explicitly a byte,
and the encoding of a raw byte run can change when `\fN` changes.

## 3. Maintain group state

`groups.py` uses an explicit stack rather than Python recursion. Every `{` copies
the current frame; every `}` restores its parent. A frame holds the destination,
current font, Unicode fallback count, HTMLRTF state, and related parser state.

Destination classification separates visible content from font tables,
`HTMLTAG`, and ignorable/non-visible groups. MS-OXRTFEX §2.2.3.2 requires all
standard non-visible destinations to be skipped except `\fonttbl`, and all
unknown `\*` destinations to be skipped except `HTMLTAG`.

## 4. Resolve fonts and code pages

`fonts.py` parses `\fonttbl`, remembers names and charset declarations, and
resolves each font to a Python codec. `codepages.py` contains the auditable
Microsoft charset/code-page mappings. See [Encodings and Unicode](encodings.md)
for the precedence rules.

## 5. Decide whether a token emits

The key decision table is:

| Location/state                    | Raw text byte encoding | Character controls       | Other controls          |
| --------------------------------- | ---------------------- | ------------------------ | ----------------------- |
| Inside `HTMLTAG`                  | document `\ansicpg`    | MS-OXRTFEX CONTENT table | ignored                 |
| Visible body, HTML mode           | current font code page | RTF text equivalents     | formatting ignored      |
| Visible body, text mode           | current font code page | RTF text equivalents     | formatting ignored      |
| `HTMLRTF` suppressed              | no output              | no output                | state still tracked     |
| Non-visible/ignorable destination | no output              | no output                | needed group state only |

Source: MS-OXRTFEX §§2.1.3.1.3, 2.1.3.1.4.2, 2.2.3.2, and 2.2.3.3.

State controls such as `\fN`, `\ucN`, `\ansicpgN`, `\deffN`, and destination
selection are processed even where output is suppressed. Otherwise later visible
text could use the wrong font, encoding, or Unicode fallback count.

## 6. Decode at safe boundaries

`emitter.py` buffers adjacent bytes while their codec is the same. It does not
decode each token independently because one multibyte character can be split
across raw text and `\'HH` tokens. The buffer is flushed when the codec or output
kind changes, or when a Unicode/control-character emission requires ordering.

Invalid bytes become U+FFFD and create an `undecodable-bytes` diagnostic. Unicode
surrogate halves are paired before output; an unpaired half likewise becomes
U+FFFD with a diagnostic.

## 7. Assemble an immutable result

`deencapsulate` returns `DeEncapsulationResult` with exactly one of `html` or
`text` populated. It also exposes the document encoding, resolved font table,
the HTML's declared charset, and ordered diagnostics. No output is post-processed
or sanitized.

## Complexity and limits

The parser is single-pass and uses an explicit group stack, so nesting does not
consume the Python call stack. Time and storage are proportional to the input and
output. The API accepts an in-memory `bytes` object; callers processing hostile
mailboxes should impose message, property, decompressed-size, and output-size
limits before calling it.
