# API reference

The supported import surface is available directly from `ottertf`.

## Extraction

::: ottertf.deencapsulator.deencapsulate

## Detection

::: ottertf.detect.detect_content_type

::: ottertf.detect.is_encapsulated_html

## HTML charset helpers

::: ottertf.html_meta.declared_charset

::: ottertf.html_meta.normalize_charset_declaration

## Result types

::: ottertf.result.ContentType

::: ottertf.result.DeEncapsulationResult

::: ottertf.result.Diagnostic

::: ottertf.result.DiagnosticCode

::: ottertf.result.FontInfo

## Exceptions

::: ottertf.exceptions.OtteRTFError

::: ottertf.exceptions.NotEncapsulatedRtfError

::: ottertf.exceptions.MalformedRtfError

::: ottertf.exceptions.MissingFontTableError

::: ottertf.exceptions.UnsupportedCodePageError

## Version

`ottertf.__version__` contains the installed distribution version, or
`"0.0.0"` when the source tree is imported without installed package metadata.
