# otteRTF 🦦

[![CI](https://github.com/tschuelia/ottertf/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/tschuelia/ottertf/actions/workflows/ci.yml)
[![Documentation](https://github.com/tschuelia/ottertf/actions/workflows/docs.yml/badge.svg?branch=main)](https://tschuelia.github.io/ottertf/)

Recover the original HTML from RTF-encapsulated HTML: the `\fromhtml1` form
that Microsoft Outlook and Exchange can store in a message's
`PidTagRtfCompressed` property.

otteRTF 🦦 implements de-encapsulation from
[MS-OXRTFEX](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfex/906fbb0f-2467-490e-8c3e-bdc31c5e9d35),
using the
[RTF 1.9.1 specification](<https://learn.microsoft.com/en-us/previous-versions/office/developer/office-2007/dd351035(v=office.12)>)
and Microsoft's
[code-page registry](https://learn.microsoft.com/en-us/windows/win32/intl/code-page-identifiers).
It has no runtime dependencies.

## Install

Install the package from conda-forge:

```console
conda install -c conda-forge ottertf
```

With Pixi, add it to a workspace instead:

```console
pixi add ottertf
```

Alternatively, install it from PyPI:

```console
python -m pip install ottertf
```

Or add the PyPI package with Pixi:

```console
pixi add --pypi ottertf
```

## Use

Pass **uncompressed RTF bytes**, not an `.msg` file and not the compressed
`PidTagRtfCompressed` payload:

```python
import ottertf

raw_rtf: bytes = ...

content_type = ottertf.detect_content_type(raw_rtf)
if content_type is ottertf.ContentType.NATIVE_RTF:
    raise ValueError("the message contains ordinary RTF")

result = ottertf.deencapsulate(raw_rtf)
print(result.content_type)  # ContentType.HTML or ContentType.TEXT
print(result.body)  # decoded str
print(result.diagnostics)
```

Extraction preserves the producer's HTML charset declaration even though the
result is already a Python `str`. If you serialize as UTF-8, make the declaration
agree first:

```python
html = ottertf.normalize_charset_declaration(result.body, "utf-8")
with open("mail.html", "w", encoding="utf-8") as output:
    output.write(html)
```

The default parser recovers usable content and reports damage in
`result.diagnostics`. `strict=True` raises structural problems instead. Native
RTF always raises `NotEncapsulatedRtfError` when passed to `deencapsulate`.

## Scope

The package performs one deliberately narrow step:

```text
.msg container -> RTF-compressed bytes -> uncompressed RTF -> HTML
       caller             caller          otteRTF 🦦
```

It does not parse `.msg` compound files, decompress the RTF compression wrapper,
render native RTF, resolve `cid:` attachments, fetch resources, or sanitize HTML.
The returned markup is untrusted input and must be sanitized before browser use.

Read the [documentation](https://tschuelia.github.io/ottertf/) for the
format history, annotated examples, extraction algorithm, encoding rules,
diagnostic policy, conformance notes, and API reference.

## Development

The repository uses [Pixi](https://pixi.sh/):

```console
pixi install
pixi run postinstall
pixi run test
pixi run -e lint lint
pixi run -e docs docs-build
pixi run -e docs docs-serve
```

Slow performance checks are available with `pixi run test-slow`. See the
[development guide](https://tschuelia.github.io/ottertf/development/)
for the supported Python matrix and fixture rules.

## License

[MIT](LICENSE)
