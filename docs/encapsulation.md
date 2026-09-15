# HTML encapsulation

## RTF in five minutes

RTF is an ASCII-compatible control language around byte-oriented text:

- `{` starts a group and `}` ends it. State is inherited on entry and restored
  on exit.
- `\word` is a control word. It can have a signed decimal parameter, as in
  `\f2` or `\u8364`.
- A space can delimit a control word; that delimiter is consumed and is not
  text.
- `\\`, `\{`, and `\}` escape literal syntax characters.
- `\'e9` represents one byte (`0xE9`), not inherently U+00E9. A code page gives
  it meaning.
- `\*` marks a destination that old readers may ignore when they do not know it.

These rules come from the
[RTF 1.9.1 specification](<https://learn.microsoft.com/en-us/previous-versions/office/developer/office-2007/dd351035(v=office.12)>).
They explain why regular expressions are insufficient: braces are stateful,
unknown destinations nest, a control-word delimiter is not output, and text is
not one fixed encoding.

## The encapsulation marker

An HTML-encapsulated document starts as ordinary RTF but carries `\fromhtml1`
after `\rtf1` and before `\fonttbl`. Only the exact parameter `1` counts;
`\fromhtml` and `\fromhtml0` do not. `\fromtext` similarly marks encapsulated
plain text.

The reader should inspect at most the first ten RTF tokens for either marker.
These rules are MS-OXRTFEX §§2.1.3.1.1, 2.1.3.1.2, and 2.2.3.1.

## The two interleaved channels

HTML uses two mechanisms inside the same RTF stream.

### `HTMLTAG`: source content preserved instead of regenerated

An `HTMLTAG` destination has this shape:

```rtf
{\*\htmltagN original HTML fragment}
```

`N` is an `HTMLTagParameter`, a legacy numeric description of the fragment.
De-encapsulation must ignore the parameter and copy the group content. Producers
use these destinations for HTML tags, comments, character references, and other
material that cannot be represented faithfully as visible RTF.

MS-OXRTFEX §2.1.3.1.4 defines the group and §2.2.3.2 requires the parameter to be
ignored. A leading `\*` is part of the specified destination form.

The special empty destination `{\*\htmltag64}` is not a `<p>` tag waiting to be
generated. Producers place one before shared visible text to disable deprecated
reader behavior; Appendix A `<10>` explains the compatibility purpose. Its empty
content naturally emits nothing.

Inside an `HTMLTAG`, the escape and character controls enumerated by
MS-OXRTFEX §2.1.3.1.4.2 have output meaning. The implementation also preserves
RTF's unambiguous optional-hyphen control, `\-`, as a documented extension.
Examples include:

| RTF input            | HTML text emitted                                |
| -------------------- | ------------------------------------------------ |
| `\par`               | CRLF                                             |
| `\tab`               | horizontal tab                                   |
| `\{`, `\}`, `\\`     | `{`, `}`, `\`                                    |
| `\lquote`, `\rquote` | U+2018, U+2019                                   |
| `\bullet`            | U+2022                                           |
| `\~`                 | U+00A0 nonbreaking space                         |
| `\_`, `\-`           | U+00AD soft hyphen                               |
| `\'HH`               | byte `0xHH`, decoded with the document code page |
| `\uN`                | the Unicode character it names                   |

Source: MS-OXRTFEX §2.1.3.1.4.2, except `\-`, which is the RTF 1.9.1 optional
hyphen extension documented in [Conformance](conformance.md). Other controls in
an `HTMLTAG` are ignored.

### Shared text and `HTMLRTF`: content selected by state

Text outside an `HTMLTAG` is normally shared: an RTF reader displays it and a
de-encapsulator copies it. RTF-only material is bracketed by the toggle:

```rtf
\htmlrtf1 this belongs only to the RTF approximation\htmlrtf0
```

`\htmlrtf` without a parameter and `\htmlrtf1` both enable suppression;
`\htmlrtf0` disables it. Like other RTF formatting state, the value is inherited
by nested groups and restored at the matching closing brace. A de-encapsulator
still tracks font changes while output is suppressed. These are the rules in
MS-OXRTFEX §§2.1.3.1.3 and 2.2.3.2.

## A complete small example

This hand-authored example shows the roles rather than mimicking every control
word emitted by Outlook:

```rtf
{\rtf1\ansi\ansicpg1252\fromhtml1\deff0
{\fonttbl{\f0\fnil\fcharset0 Arial;}}
{\*\htmltag1 <html><body>}
{\*\htmltag64}
{\*\htmltag64 <p>}Hello
\htmlrtf1\f0\fs24\b0\htmlrtf0
{\*\htmltag64 </p>}
{\*\htmltag1 </body></html>}}
```

A normal RTF reader ignores the unknown ignorable `HTMLTAG` groups and displays
`Hello`. A de-encapsulator does the reverse selection:

1. `\fromhtml1` selects HTML mode.
2. The font table and `\ansicpg1252` establish decoding state.
3. HTMLTAG parameters `1` and `64` are discarded; their content is copied.
4. The shared `Hello` text is copied.
5. The RTF formatting controls bracketed by `\htmlrtf1` and `\htmlrtf0` emit
   nothing.

The result is:

```html
<html>
  <body>
    <p>Hello</p>
  </body>
</html>
```

## `MHTMLTAG`

Some legacy producers can also emit `MHTMLTAG`. It holds a rewritten copy of
content whose original form exists in an `HTMLTAG`, so it must be ignored. Copying
both would duplicate or alter the original. See MS-OXRTFEX §2.1.3.1.5 and
Appendix A `<8>`.
