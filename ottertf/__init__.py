"""Extract HTML embedded in RTF.

An implementation of MS-OXRTFEX de-encapsulation: given the uncompressed RTF
bytes of an email body, recover the HTML or plain text that Exchange or Outlook
encapsulated in it.

    import ottertf

    result = ottertf.deencapsulate(raw_rtf)
    print(result.body)

Pure standard library, no runtime dependencies. See the README for the
conformance table and the documented deviations from the specification.
"""

import importlib.metadata

from ottertf.deencapsulator import deencapsulate
from ottertf.detect import detect_content_type, is_encapsulated_html
from ottertf.exceptions import (
    MalformedRtfError,
    MissingFontTableError,
    NotEncapsulatedRtfError,
    OtteRTFError,
    UnsupportedCodePageError,
)
from ottertf.html_meta import declared_charset, normalize_charset_declaration
from ottertf.result import (
    ContentType,
    DeEncapsulationResult,
    Diagnostic,
    DiagnosticCode,
    FontInfo,
)

try:
    __version__ = importlib.metadata.version("ottertf")
except importlib.metadata.PackageNotFoundError:  # pragma: no cover - normally installed
    __version__ = "0.0.0"

__all__ = [
    "ContentType",
    "DeEncapsulationResult",
    "Diagnostic",
    "DiagnosticCode",
    "FontInfo",
    "MalformedRtfError",
    "MissingFontTableError",
    "NotEncapsulatedRtfError",
    "OtteRTFError",
    "UnsupportedCodePageError",
    "__version__",
    "declared_charset",
    "deencapsulate",
    "detect_content_type",
    "is_encapsulated_html",
    "normalize_charset_declaration",
]
