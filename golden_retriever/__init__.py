"""Extract HTML embedded in RTF.

An implementation of MS-OXRTFEX de-encapsulation: given the uncompressed RTF
bytes of an email body, recover the HTML or plain text that Exchange or Outlook
encapsulated in it.

    import golden_retriever as gr

    result = gr.deencapsulate(raw_rtf)
    print(result.body)

Pure standard library, no runtime dependencies. See the README for the
conformance table and the documented deviations from the specification.
"""

import importlib.metadata

from golden_retriever.deencapsulator import deencapsulate
from golden_retriever.detect import detect_content_type, is_encapsulated_html
from golden_retriever.exceptions import (
    GoldenRetrieverError,
    MalformedRtfError,
    MissingFontTableError,
    NotEncapsulatedRtfError,
    UnsupportedCodePageError,
)
from golden_retriever.html_meta import declared_charset, normalize_charset_declaration
from golden_retriever.result import (
    ContentType,
    DeEncapsulationResult,
    Diagnostic,
    DiagnosticCode,
    FontInfo,
)

try:
    __version__ = importlib.metadata.version("golden-retriever")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - normally installed
    __version__ = "0.0.0"

__all__ = [
    "ContentType",
    "DeEncapsulationResult",
    "Diagnostic",
    "DiagnosticCode",
    "FontInfo",
    "GoldenRetrieverError",
    "MalformedRtfError",
    "MissingFontTableError",
    "NotEncapsulatedRtfError",
    "UnsupportedCodePageError",
    "__version__",
    "declared_charset",
    "deencapsulate",
    "detect_content_type",
    "is_encapsulated_html",
    "normalize_charset_declaration",
]
