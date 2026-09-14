"""Recognizing encapsulated content (MS-OXRTFEX 2.2.3.1)."""

from golden_retriever.result import ContentType

__all__ = ["DEFAULT_HEADER_TOKEN_LIMIT", "detect_content_type", "is_encapsulated_html"]

DEFAULT_HEADER_TOKEN_LIMIT = 10
"""How far into the document to look for ``\\fromhtml1`` / ``\\fromtext``.

MS-OXRTFEX 2.2.3.1 requires the marker to appear "before any other keyword" in the first
10 tokens of the document.
"""


def detect_content_type(
    raw_rtf: bytes, *, header_token_limit: int = DEFAULT_HEADER_TOKEN_LIMIT
) -> ContentType:
    """Classify what ``raw_rtf`` encapsulates, without de-encapsulating it.

    This only lexes the document header, so it is cheap enough to call as a guard. It
    never raises for malformed input: anything unrecognizable is
    :attr:`~golden_retriever.ContentType.NATIVE_RTF`.

    :param raw_rtf: Uncompressed RTF bytes.
    :param header_token_limit: How many header tokens may precede the marker.
    """
    raise NotImplementedError("detect_content_type is not implemented yet")


def is_encapsulated_html(raw_rtf: bytes) -> bool:
    """Whether ``raw_rtf`` encapsulates HTML.

    Shorthand for comparing :func:`detect_content_type` against
    :attr:`~golden_retriever.ContentType.HTML`.
    """
    raise NotImplementedError("is_encapsulated_html is not implemented yet")
