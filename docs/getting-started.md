# Getting started

## Installation

Install the package from conda-forge:

```console
conda install -c conda-forge golden-retriever
```

With Pixi, add it to a workspace instead:

```console
pixi add golden-retriever
```

The package named `golden-retriever` on PyPI is unrelated to this repository;
do not install that package as a substitute.

Python 3.12 or newer is required.

## Detect before extracting

The detector reads only a bounded header prefix, following MS-OXRTFEX §2.2.3.1:

```python
import golden_retriever as gr

raw_rtf = b"{\\rtf1\\ansi\\fromhtml1 ...}"

match gr.detect_content_type(raw_rtf):
    case gr.ContentType.HTML:
        print("encapsulated HTML")
    case gr.ContentType.TEXT:
        print("encapsulated plain text")
    case gr.ContentType.NATIVE_RTF:
        print("ordinary or unrecognized RTF")
```

`is_encapsulated_html(raw_rtf)` is a Boolean shorthand. The default recognition
window is ten RTF tokens. Increase `header_token_limit` only when recovering
nonconforming input.

## Extract content

```python
result = gr.deencapsulate(raw_rtf)

result.content_type  # ContentType.HTML or ContentType.TEXT
result.body  # whichever decoded str was extracted
result.html  # str for HTML, otherwise None
result.text  # str for text, otherwise None
```

The result also records how bytes were interpreted:

```python
result.document_codepage  # for example, 1252
result.document_encoding  # Python codec name, for example, "cp1252"
result.fonts  # mapping from RTF font number to FontInfo
result.declared_html_charset
```

`declared_html_charset` is metadata found in the resulting HTML. It is not the
decoder used for the RTF byte stream. See [Encodings and Unicode](encodings.md).

## Choose recovery or strict mode

Lenient mode is the default. It substitutes where possible and returns a tuple
of diagnostics:

```python
result = gr.deencapsulate(raw_rtf)
for diagnostic in result.diagnostics:
    print(diagnostic.code, diagnostic.message)
```

Strict mode raises structural problems such as a missing RTF heading, unbalanced
groups, a truncated binary payload, a missing font table, or an unsupported code
page:

```python
try:
    result = gr.deencapsulate(raw_rtf, strict=True)
except gr.NotEncapsulatedRtfError:
    ...  # neither encapsulation marker was recognized
except gr.GoldenRetrieverError as error:
    ...  # strict structural failure
```

Strict mode changes whether parsing stops, not the decoding rules.

## Serialize extracted HTML safely

Extraction returns `str`. It deliberately leaves a `<meta charset>` declaration
unchanged, so a caller that writes a different character encoding must update the
declaration:

```python
html = gr.normalize_charset_declaration(result.body, "utf-8")
payload = html.encode("utf-8")
```

`declared_charset(html)` reads the first declaration in the document head.
`normalize_charset_declaration` rewrites it or inserts one. Neither helper
sanitizes HTML.

!!! warning

    Extracted HTML is untrusted message content. Sanitize it before inserting it
    into a browser document, and apply context-appropriate escaping before using
    it anywhere else.
