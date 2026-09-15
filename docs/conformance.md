# Conformance

## Specification coverage

| Specification section                                  | Coverage     |
| ------------------------------------------------------ | ------------ |
| MS-OXRTFEX §2.2.3.1, recognizing encapsulated data     | Implemented  |
| MS-OXRTFEX §2.2.3.2, extracting HTML                   | Implemented  |
| MS-OXRTFEX §2.2.3.3, extracting plain text             | Implemented  |
| MS-OXRTFEX §2.2.3.4, attachment integration            | Out of scope |
| RTF 1.9.1 syntax needed by those algorithms            | Implemented  |
| Windows charset/code-page resolution used by font runs | Implemented  |

Every spec-derived table or rule in source has a nearby section citation. Test
fixtures are hand-authored from the specifications so the conformance evidence
does not inherit another parser's assumptions.

## Deliberate deviations and recovery choices

### `\_` depends on context

MS-OXRTFEX §2.1.3.1.4.2 maps `\_` to `&shy;` (U+00AD) inside HTMLTAG content.
RTF 1.9.1 defines it as a nonbreaking hyphen (U+2011), with `\-` as the optional
hyphen (U+00AD). The implementation honors each table in its own context:
`\_` produces U+00AD in HTMLTAG and U+2011 in body text; `\-` produces U+00AD.

### ANSI/default font charsets follow `\ansicpg`

`\fcharset0` and `\fcharset1` resolve to the document's `\ansicpg` rather than
hard-coded code page 1252. These charset values describe the system/default ANSI
set, while `\ansicpg` records the relevant document code page. The caller's
`fallback_codepage` applies only when that declaration is absent or unusable.

Source: RTF 1.9.1 “Font Table” and “Character Set”; MS-OXRTFEX §2.2.3.2.

### Missing `\rtf1` is recoverable

MS-OXRTFEX §2.2.3.1 first checks the RTF heading. Appendix A `<13>` records
Microsoft implementations that attempt de-encapsulation without it. Lenient mode
does the same and emits `missing-rtf-magic`; strict mode rejects it.

Appendix A `<14>` concerns implementations looking beyond the recommended first
ten tokens. It does **not** describe an omitted `\*` on HTMLTAG.

### Unprefixed HTMLTAG is a project recovery policy

The normative grammar in MS-OXRTFEX §2.1.3.1.4 uses an ignorable destination:
`{\*\htmltag...}`. Lenient mode also accepts `{\htmltag...}` and emits
`unprefixed-htmltag`; strict mode rejects it. This tolerance is explicitly not
claimed as Microsoft product behavior.

### HTMLTAG bytes use the document code page

MS-OXRTFEX §2.2.3.2 requires remaining HTMLTAG text to use the default code page
from the RTF header. Therefore an in-effect `\fN` does not change HTMLTAG byte
decoding. Font-specific code pages apply to visible text outside that destination.

### HTMLTAG clears inherited HTMLRTF suppression

Entering an HTMLTAG group clears output suppression for that group. A strictly
literal composition of the group and toggle rules could carry suppression into a
nested HTMLTAG. The implementation instead treats explicit original-HTML content
as visible. Normal producers do not nest these constructs, so the choice affects
only malformed or unusual input and favors content recovery.

Source context: MS-OXRTFEX §§2.1.3.1.3, 2.1.3.1.4, and 2.2.3.2.

### State is tracked while output is suppressed

MS-OXRTFEX §2.2.3.2 specifically says to track `\fN` inside HTMLRTF-suppressed
fragments. The implementation also processes non-emitting state controls such as
`\ucN`, `\ansicpgN`, `\deffN`, and destination/font-table transitions. Suppression
stops output, not bookkeeping; otherwise later visible content can be decoded or
skipped incorrectly.

### A following `\uN` is not ANSI fallback

RTF 1.9.1 says a control word counts as one character while skipping the ANSI
representation after `\uN`. This implementation exempts another `\uN`: Unicode
is not an ANSI representation, and consuming it would delete an adjacent
character or the low half of a surrogate pair. All other documented skip-count
rules are retained.

## Explicitly out of scope

- RTF compression and decompression (MS-OXRTFCP).
- Compound-file and `.msg` parsing (MS-OXMSG).
- Rendering native RTF into HTML.
- Attachment insertion or `cid:` resolution (MS-OXRTFEX §2.2.3.4).
- HTML sanitization, URL validation, and external resource fetching.
- Producing RTF-encapsulated HTML.

## Normative references

- [MS-OXRTFEX: RTF Extensions Algorithm](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfex/411d0d58-49f7-496c-b8c3-5859b045f6cf)
- [Rich Text Format 1.9.1](<https://learn.microsoft.com/en-us/previous-versions/office/developer/office-2007/dd351035(v=office.12)>)
- [Code Page Identifiers](https://learn.microsoft.com/en-us/windows/win32/intl/code-page-identifiers)
