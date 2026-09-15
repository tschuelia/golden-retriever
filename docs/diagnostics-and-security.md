# Diagnostics and security

## Recovery policy

Mailbox software routinely encounters old, truncated, and producer-specific
documents. The default parser therefore returns the best recoverable content and
records what went wrong. Diagnostics are ordered and carry a stable code plus a
human-readable message.

`strict=True` escalates structural conditions. Content damage that no stricter
interpretation can repair remains a diagnostic.

| Diagnostic code        | Lenient behavior                                    | Strict behavior                 |
| ---------------------- | --------------------------------------------------- | ------------------------------- |
| `missing-rtf-magic`    | Continue when encapsulation is otherwise recognized | `MalformedRtfError`             |
| `unprefixed-htmltag`   | Treat the group as HTMLTAG                          | `MalformedRtfError`             |
| `unbalanced-groups`    | Return content recovered before the mismatch        | `MalformedRtfError`             |
| `truncated-bin`        | Consume the available payload                       | `MalformedRtfError`             |
| `missing-font-table`   | Use the document/fallback code page                 | `MissingFontTableError`         |
| `unsupported-codepage` | Use a supported fallback codec                      | `UnsupportedCodePageError`      |
| `unknown-font`         | Use the document encoding                           | Diagnostic                      |
| `undecodable-bytes`    | Insert U+FFFD                                       | Diagnostic                      |
| `unpaired-surrogate`   | Insert U+FFFD                                       | Diagnostic                      |
| `symbol-font-charset`  | Use the document encoding                           | Diagnostic                      |
| `skipped-destination`  | Reserved; routine spec-required skips are silent    | Reserved; not currently emitted |

The missing-heading recovery is supported by MS-OXRTFEX §2.2.3.1 Appendix A
`<13>`. Accepting `\htmltag` without its specified `\*` prefix is a project
recovery policy, not Appendix A behavior; the normative group grammar is
MS-OXRTFEX §2.1.3.1.4.

`NotEncapsulatedRtfError` is independent of strictness. It means the detector did
not find an encapsulated body; it does not mean the package failed to render
ordinary RTF, because rendering is not attempted.

## Exception boundary

All intentional parser exceptions inherit `GoldenRetrieverError`. Programming
contract errors remain standard exceptions: a non-`bytes` input can raise
`TypeError`, and an invalid fallback code-page argument can raise `ValueError`.

```python
try:
    result = golden_retriever.deencapsulate(raw_rtf, strict=True)
except golden_retriever.NotEncapsulatedRtfError:
    use_an_rtf_renderer(raw_rtf)
except golden_retriever.GoldenRetrieverError as error:
    quarantine_message(error)
```

## Trust boundary

Both input and output are untrusted.

- **HTML is not sanitized.** Scripts, event handlers, dangerous URLs, forms, CSS,
  and active embedded content can remain in the result. Apply a maintained HTML
  sanitizer with a policy appropriate to the destination.
- **No resources are resolved.** `cid:`, `data:`, and external URLs are copied as
  text. The library performs no network or attachment access.
- **No contextual escaping is applied.** Do not interpolate the result into SQL,
  shells, templates, headers, or markup without the escaping required there.
- **Charset normalization is not sanitization.** It changes one declaration; it
  does not parse or make the document safe.

## Resource controls

The parser is linear and non-recursive, but it accepts the complete payload in
memory and creates output and parser state proportional to it. A boundary that
handles hostile messages should limit:

- `.msg` and property sizes before allocation;
- the uncompressed size advertised by the RTF compression header;
- decompression expansion and CRC failures;
- the size passed to `deencapsulate`; and
- the amount retained or rendered after extraction.

Those policies belong around the library because only the caller knows the
mailbox, queue, or service limits.
