# API reference

The supported import surface is available directly from `golden_retriever`.

## Extraction

::: golden_retriever.deencapsulator.deencapsulate

## Detection

::: golden_retriever.detect.detect_content_type

::: golden_retriever.detect.is_encapsulated_html

## HTML charset helpers

::: golden_retriever.html_meta.declared_charset

::: golden_retriever.html_meta.normalize_charset_declaration

## Result types

::: golden_retriever.result.ContentType

::: golden_retriever.result.DeEncapsulationResult

::: golden_retriever.result.Diagnostic

::: golden_retriever.result.DiagnosticCode

::: golden_retriever.result.FontInfo

## Exceptions

::: golden_retriever.exceptions.GoldenRetrieverError

::: golden_retriever.exceptions.NotEncapsulatedRtfError

::: golden_retriever.exceptions.MalformedRtfError

::: golden_retriever.exceptions.MissingFontTableError

::: golden_retriever.exceptions.UnsupportedCodePageError

## Version

`golden_retriever.__version__` contains the installed distribution version, or
`"0.0.0"` when the source tree is imported without installed package metadata.
