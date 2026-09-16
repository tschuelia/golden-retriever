"""Exceptions raised by :mod:`ottertf`.

Every exception this package raises deliberately derives from
:class:`OtteRTFError` and from nothing else in the standard library
hierarchy. A single ``except OtteRTFError`` is therefore both necessary
and sufficient to keep a malformed message from taking down a caller that is
processing a mailbox, and it cannot accidentally swallow a genuine ``TypeError``
or ``ValueError`` from the surrounding code.
"""

__all__ = [
    "OtteRTFError",
    "MalformedRtfError",
    "MissingFontTableError",
    "NotEncapsulatedRtfError",
    "UnsupportedCodePageError",
]


class OtteRTFError(Exception):
    """Base class for every error raised by this package."""


class NotEncapsulatedRtfError(OtteRTFError):
    """The input is RTF, but it does not encapsulate HTML or plain text.

    Raised when neither ``\\fromhtml1`` nor ``\\fromtext`` appears in the document
    header (MS-OXRTFEX 2.2.3.1). Call :func:`ottertf.detect_content_type` first
    to branch on this without exception handling.
    """


class MalformedRtfError(OtteRTFError):
    """The input is structurally broken beyond what leniency covers.

    Only raised when ``strict=True``. Structural damage covered by this error is
    a missing ``{\\rtf1`` header, an HTMLTAG group without the required ``\\*``,
    unbalanced groups, and a ``\\bin`` payload that runs past the end of the data.
    In the default lenient mode each of those is recorded as a
    :class:`ottertf.Diagnostic` instead.
    """


class UnsupportedCodePageError(OtteRTFError):
    """A code page named by the document has no decoder in this Python build.

    Only raised when ``strict=True``; the lenient default falls back to the document
    code page (or ``fallback_codepage``) and records a diagnostic.
    """


class MissingFontTableError(OtteRTFError):
    """The document declares no ``\\fonttbl``.

    Only raised when ``strict=True``. Encapsulated HTML produced by Outlook always
    carries a font table, but truncated or hand-built documents may not; the lenient
    default decodes everything in the document code page and records a diagnostic.
    """
