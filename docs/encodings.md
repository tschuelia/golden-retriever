# Encodings and Unicode

Encoding is the main reason an RTF de-encapsulator must preserve parser state.
The input is bytes, different visible runs can use different code pages, and RTF
can mix byte text with Unicode escape controls.

## Document code page

`\ansicpgN` declares the ANSI code page for the document. For example,
`\ansicpg1252` selects Windows-1252. If no usable declaration exists,
`deencapsulate(..., fallback_codepage=1252)` supplies the default.

Inside `HTMLTAG`, raw text and hexadecimal escapes always use this document code
page, regardless of the selected font. MS-OXRTFEX §2.2.3.2 calls it the default
code page from the RTF header.

## Font-specific code pages

Outside `HTMLTAG`, text uses the currently selected font. The implementation
resolves a font in this order:

1. an explicit `\cpgN` in the font entry;
2. the Windows code page associated with `\fcharsetN`;
3. the document code page for `\fcharset0` (`ANSI_CHARSET`) and
   `\fcharset1` (`DEFAULT_CHARSET`), or when the entry provides neither; and
4. `fallback_codepage` when the document has no usable `\ansicpgN`.

Sources: RTF 1.9.1, “Font Table” and “Character Set” sections; MS-OXRTFEX
§2.2.3.2; Microsoft
[Code Page Identifiers](https://learn.microsoft.com/en-us/windows/win32/intl/code-page-identifiers).

`\fcharset2` is the Symbol character set, which is a glyph mapping rather than a
normal Windows code page. The reader falls back and records
`symbol-font-charset`. An unknown font selection similarly falls back and records
`unknown-font`.

## Byte runs and multibyte encodings

An escape such as `\'e9` means the byte `0xE9`; it does not directly mean “é”.
The selected codec decides that. Adjacent raw bytes and hex escapes are buffered
together before decoding, so a multibyte character remains valid even when RTF
syntax divides its bytes.

Unsupported code pages fall back in lenient mode and produce
`unsupported-codepage`. Undecodable sequences use the replacement character
U+FFFD and produce `undecodable-bytes`. In strict mode an unsupported code page
raises `UnsupportedCodePageError`; malformed byte content remains recoverable.

## `\uN` and `\ucN`

RTF represents Unicode with a signed 16-bit value in `\uN`. For compatibility
with old readers, it is normally followed by an ANSI approximation. `\ucN`
states how many fallback characters a Unicode-aware reader must skip; the
default is one.

```rtf
\uc1\u8364?        # emit € and skip the question-mark fallback
```

RTF 1.9.1's “Unicode RTF” rules count a control word or control symbol as one
fallback character, count a whole `\binN` construct as one, do not count the
delimiter space after a control word, and stop fallback skipping at a group
boundary. otteRTF 🦦 implements those token-level rules.

One project deviation is intentional: a second `\uN` cancels a pending fallback
skip instead of being consumed as the fallback. This preserves adjacent Unicode
escapes and permits a UTF-16 surrogate pair without an ANSI byte between its
halves.

## Surrogate pairs

Characters above U+FFFF arrive as two signed `\uN` values representing UTF-16
surrogates. The emitter combines a valid high/low pair into one Python character.
An isolated or reversed surrogate is replaced with U+FFFD and recorded as
`unpaired-surrogate`.

## RTF decoding versus HTML declaration

These are separate layers:

| Value                          | Meaning                                       |
| ------------------------------ | --------------------------------------------- |
| `result.document_encoding`     | Codec used to interpret default RTF byte runs |
| `result.fonts[n].encoding`     | Codec used for visible body bytes in font `n` |
| `result.declared_html_charset` | Literal value claimed by a `<meta>` element   |

The first two recover Python text from RTF bytes. The third is simply markup in
the recovered HTML and may disagree with how the RTF carried those characters.
Extraction preserves it for fidelity.

Before serializing to another encoding, update the declaration:

```python
html = result.body
html = ottertf.normalize_charset_declaration(html, "utf-8")
output_bytes = html.encode("utf-8")
```

The helper only searches the document head and recognizes `<meta charset=...>`
and the `http-equiv="Content-Type"` form. It is a targeted attribute rewrite,
not a general HTML parser.
