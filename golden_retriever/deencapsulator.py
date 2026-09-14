"""De-encapsulating HTML and plain text (MS-OXRTFEX 2.2.3.2 and 2.2.3.3)."""

from golden_retriever.detect import DEFAULT_HEADER_TOKEN_LIMIT
from golden_retriever.result import DeEncapsulationResult

__all__ = ["DEFAULT_FALLBACK_CODEPAGE", "deencapsulate"]

DEFAULT_FALLBACK_CODEPAGE = 1252
"""Code page assumed when the document declares no usable ``\\ansicpgN``.

Windows-1252 is what Outlook writes for western-European locales and is the least
damaging guess: its printable range agrees with Latin-1 and ASCII.
"""


def deencapsulate(
    raw_rtf: bytes,
    *,
    strict: bool = False,
    fallback_codepage: int = DEFAULT_FALLBACK_CODEPAGE,
    header_token_limit: int = DEFAULT_HEADER_TOKEN_LIMIT,
) -> DeEncapsulationResult:
    """Extract the HTML or plain text encapsulated in ``raw_rtf``.

    :param raw_rtf: Uncompressed RTF bytes. If the content is stored as
        ``PidTagRtfCompressed``, decompress it first.
    :param strict: Raise on structural damage instead of recording a
        :class:`~golden_retriever.Diagnostic` and carrying on. This never changes which
        characters are produced -- only whether a problem is raised or reported.
    :param fallback_codepage: Code page to assume when the document declares no usable
        ``\\ansicpgN``.
    :param header_token_limit: How many header tokens may precede the ``\\fromhtml1`` /
        ``\\fromtext`` marker.
    :raises golden_retriever.NotEncapsulatedRtfError: The document is native RTF. Call
        :func:`~golden_retriever.detect_content_type` first to avoid this.
    :raises golden_retriever.GoldenRetrieverError: Any other failure. No other exception
        type escapes this function for ``bytes`` input.
    """
    raise NotImplementedError("deencapsulate is not implemented yet")
