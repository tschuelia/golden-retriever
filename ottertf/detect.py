"""Recognizing encapsulated content (MS-OXRTFEX 2.2.3.1).

The rule
========

A de-encapsulating reader "SHOULD inspect no more than the first 10 RTF tokens
(that is, begin group marks and control words) in the input RTF document, in
sequence, starting from the beginning of the RTF document". The FROMHTML control
word means the document contains encapsulated HTML, FROMTEXT means it was
produced from plain text, and inspection stops at whichever appears first. The
document is a normal (pure) RTF document if "there are any RTF tokens besides the
begin group mark "{" or a control word within the first 10 tokens", or if "there
is no FROMHTML or FROMTEXT control word within the first 10 tokens".

Both markers are exact byte sequences rather than families of control words:

- ``FROMTEXT = %x5C.66.72.6F.6D.74.65.78.74`` -- ``\\fromtext``, with no
  parameter (MS-OXRTFEX 2.1.3.1.1).
- ``FROMHTML = %x5C.66.72.6F.6D.68.74.6D.6C "1"``, and "this control word MUST be
  \\fromhtml1. Any other form, such as \\fromhtml or \\fromhtml0, will not be
  considered encapsulated" (MS-OXRTFEX 2.1.3.1.2).

RTF control words are case-sensitive, so ``\\FROMHTML1`` is a different control
word and not a marker.

Cost
====

Inspection is bounded: it stops at the token limit, and any token that is not a
begin group mark or a control word stops it immediately. Recognition therefore
reads a document's header, never its body, and is cheap enough to call as a
guard.

Leniency
========

- **A missing ``{\\rtf1`` heading does not change the classification.**
  MS-OXRTFEX 2.2.3.1 asks a reader to check the heading first, but its product
  behavior note A<13> records that implementations "ignore the absence of the
  \\rtf1 keyword at the beginning of the RTF encoded text and try to
  de-encapsulate the text anyway". This module does the same:
  :func:`has_rtf_heading` reports the heading separately, so a caller can record a
  :attr:`~ottertf.DiagnosticCode.MISSING_RTF_MAGIC` diagnostic without
  discarding content that is plainly encapsulated.
- **A whitespace-only text token does not end the inspection,** though it does
  spend one token of the window. Bare CR and LF are insignificant already (RTF
  1.9.1: "CRLFs should be ignored by RTF readers"), so a header written across
  several lines arrives here with its indentation as a run of spaces, and
  refusing that document would discard a marker the producer did emit.
- **``\\fonttbl`` is not a cutoff.** Both markers "MUST appear before the
  \\fonttbl control word and after the \\rtf1 control word", but that is a
  requirement on writers. Stopping at ``\\fonttbl`` would refuse a document whose
  marker is still in plain sight, so the token limit is the only bound. A font
  table usually ends the inspection by itself, because the first font name in it
  is a text token.

Everything else follows the rule strictly: a stray ``}``, a control symbol such
as ``\\*``, a ``\\'hh`` escape and a ``\\binN`` payload each mean native RTF,
because none of them is a begin group mark or a control word.
"""

from ottertf.result import ContentType
from ottertf.tokenizer import Token, TokenKind, tokenize

__all__ = [
    "DEFAULT_HEADER_TOKEN_LIMIT",
    "RTF_HEADING",
    "detect_content_type",
    "has_rtf_heading",
    "is_encapsulated_html",
]

DEFAULT_HEADER_TOKEN_LIMIT = 10
"""How far into the document to look for ``\\fromhtml1`` / ``\\fromtext``.

MS-OXRTFEX 2.2.3.1: a reader "SHOULD inspect no more than the first 10 RTF tokens ...
starting from the beginning of the RTF document". Raising this is what a caller does to
be more lenient than the specification; note A<14> records that implementations
"do not produce the \\fromhtml1 or \\fromtext keywords outside of the first 10 tokens".
"""

RTF_HEADING = b"{\\rtf1"
"""The heading MS-OXRTFEX 2.2.3.1 expects: a valid document "starts with the character
sequence "{\\rtf1""."""

_FROMHTML = "fromhtml"
_FROMHTML_PARAM = 1
_FROMTEXT = "fromtext"

# The token kinds MS-OXRTFEX 2.2.3.1 names as inspectable: "begin group marks and
# control words".
_HEADER_TOKEN_KINDS = frozenset({TokenKind.GROUP_START, TokenKind.WORD})


def has_rtf_heading(raw_rtf: bytes) -> bool:
    """Whether ``raw_rtf`` begins with the ``{\\rtf1`` document heading.

    Reported rather than enforced; see this module's leniency notes.

    :param raw_rtf: Uncompressed RTF bytes.
    :returns: ``True`` only when the exact RTF heading is present at byte zero.
    """
    return raw_rtf.startswith(RTF_HEADING)


def _ends_inspection(token: Token) -> bool:
    """Whether ``token`` is one of the "RTF tokens besides the begin group mark "{" or a
    control word" that make a document native RTF."""
    if token.kind in _HEADER_TOKEN_KINDS:
        return False
    return not (token.kind is TokenKind.TEXT and token.data.isspace())


def detect_content_type(
    raw_rtf: bytes, *, header_token_limit: int = DEFAULT_HEADER_TOKEN_LIMIT
) -> ContentType:
    """Classify what ``raw_rtf`` encapsulates, without de-encapsulating it.

    This only lexes the document header, so it is cheap enough to call as a guard. It
    never raises for malformed input: anything unrecognizable is
    :attr:`~ottertf.ContentType.NATIVE_RTF`.

    :param raw_rtf: Uncompressed RTF bytes.
    :param header_token_limit: How many header tokens may precede the marker.
    :returns: HTML, plain text, or native RTF classification.
    """
    inspected = 0
    for token in tokenize(raw_rtf):
        if inspected >= header_token_limit:
            # "There is no FROMHTML or FROMTEXT control word within the first 10
            # tokens."
            return ContentType.NATIVE_RTF
        inspected += 1
        if _ends_inspection(token):
            return ContentType.NATIVE_RTF
        if token.kind is TokenKind.WORD:
            if token.name == _FROMHTML and token.param == _FROMHTML_PARAM:
                return ContentType.HTML
            if token.name == _FROMTEXT and token.param is None:
                return ContentType.TEXT
    return ContentType.NATIVE_RTF


def is_encapsulated_html(raw_rtf: bytes) -> bool:
    """Whether ``raw_rtf`` encapsulates HTML.

    Shorthand for comparing :func:`detect_content_type` against
    :attr:`~ottertf.ContentType.HTML`.

    :param raw_rtf: Uncompressed RTF bytes.
    :returns: ``True`` only for a recognized ``\\fromhtml1`` document.
    """
    return detect_content_type(raw_rtf) is ContentType.HTML
