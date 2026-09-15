"""Control words and control symbols that stand for a character.

Provenance
==========

There are two tables, one per destination, because the two specifications
disagree about one row.

- ``HTMLTAG_CHARMAP`` is the table in MS-OXRTFEX 2.1.3.1.4.2, which enumerates
  every RTF escape and control word that a CONTENT HTML fragment may contain.
  Anything absent from that table is ignored inside an HTMLTAG destination.
- ``BODY_CHARMAP`` is the Special Characters table of RTF 1.9.1 (Character
  Formatting), restricted to the entries that stand for a character. MS-OXRTFEX
  2.2.3.2 additionally requires ``\\par`` and ``\\line`` to become CRLF and
  ``\\tab`` to become a horizontal tab outside HTMLTAG destinations.

The disagreement is ``\\_``. MS-OXRTFEX 2.1.3.1.4.2 gives it as ``&shy;``
(U+00AD, soft hyphen); RTF 1.9.1 calls it the non-breaking hyphen (U+2011) and
gives U+00AD to ``\\-``, the optional hyphen. Each table follows its own
specification, so ``\\_`` produces a different character depending on where it
appears. The alternative -- picking one reading and applying it everywhere --
would silently corrupt one of the two contexts.

Every value is written as an escape rather than as a literal character. Half of
this table is invisible in a text editor, and a reviewer cannot check a table of
non-breaking spaces, soft hyphens and joiners that all render as nothing.

Deliberate omissions
====================

Entries of the RTF 1.9.1 table that name no character are absent, so the driver
ignores them: ``\\:`` (index subentry), ``\\|`` (formula character), the break
control words other than ``\\par`` and ``\\line``, and the table-cell words.
``\\zwbo`` and ``\\zwnbo`` are absent too: the specification describes them as
line-break opportunities without giving a Unicode equivalent, and inventing one
would put a character in the output that no specification asked for.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

__all__ = ["BODY_CHARMAP", "HTMLTAG_CHARMAP", "CharMap"]

_SHARED_WORDS: dict[str, str] = {
    # Rows where MS-OXRTFEX 2.1.3.1.4.2 and the RTF 1.9.1 Special Characters
    # table agree. The Windows code values RTF 1.9.1 lists for the quotation
    # marks, the bullet and the dashes (145-151) are their Windows-1252 bytes,
    # which decode to exactly these code points.
    "par": "\r\n",  # MS-OXRTFEX: %x0D.0A; RTF 1.9.1: end of paragraph
    "tab": "\t",  # %x09, horizontal tab
    "lquote": "\u2018",  # left single quotation mark
    "rquote": "\u2019",  # right single quotation mark
    "ldblquote": "\u201c",  # left double quotation mark
    "rdblquote": "\u201d",  # right double quotation mark
    "bullet": "\u2022",  # bullet
    "endash": "\u2013",  # en dash
    "emdash": "\u2014",  # em dash
}

_SHARED_SYMBOLS: dict[str, str] = {
    # Control symbols both specifications define identically.
    "{": "{",  # %x7B
    "}": "}",  # %x7D
    "\\": "\\",  # %x5C, reverse solidus
    "~": "\u00a0",  # non-breaking space
    # \- is not in the MS-OXRTFEX 2.1.3.1.4.2 table, which would make it an
    # ignored control symbol inside HTMLTAG content. It is kept in both tables
    # because RTF 1.9.1 defines it unambiguously and dropping it would delete a
    # character the producer wrote.
    "-": "\u00ad",  # optional hyphen, i.e. soft hyphen
}

_HTMLTAG_WORDS: dict[str, str] = dict(_SHARED_WORDS)
"""MS-OXRTFEX 2.1.3.1.4.2 lists no control word beyond the shared set."""

_HTMLTAG_SYMBOLS: dict[str, str] = {
    **_SHARED_SYMBOLS,
    "_": "\u00ad",  # MS-OXRTFEX 2.1.3.1.4.2: "&shy;", soft hyphen
}

_BODY_WORDS: dict[str, str] = {
    **_SHARED_WORDS,
    # MS-OXRTFEX 2.2.3.2: \line becomes CRLF alongside \par. RTF 1.9.1 calls it
    # a required line break with no paragraph break; that distinction does not
    # survive into HTML or plain text.
    "line": "\r\n",
    # The remaining RTF 1.9.1 Special Characters that stand for a character.
    "emspace": "\u2003",  # non-breaking space one "m" wide -- em space
    "enspace": "\u2002",  # non-breaking space one "n" wide -- en space
    "qmspace": "\u2005",  # one-quarter em space -- four-per-em space
    "ltrmark": "\u200e",  # left-to-right mark
    "rtlmark": "\u200f",  # right-to-left mark
    "zwj": "\u200d",  # zero-width joiner
    "zwnj": "\u200c",  # zero-width non-joiner
}

_BODY_SYMBOLS: dict[str, str] = {
    **_SHARED_SYMBOLS,
    "_": "\u2011",  # RTF 1.9.1: non-breaking hyphen
}


@dataclass(frozen=True, slots=True)
class CharMap:
    """The character tables that apply in one destination.

    Both mappings are keyed without the leading backslash: ``words`` by a
    control word name as the tokenizer reports it (``"par"``), ``symbols`` by the
    single character of a control symbol (``"~"``). An absent key means the token
    produces no character and is ignored.
    """

    words: Mapping[str, str]
    """Control word name to the text it produces."""

    symbols: Mapping[str, str]
    """Control symbol character to the text it produces."""


HTMLTAG_CHARMAP = CharMap(
    words=MappingProxyType(_HTMLTAG_WORDS),
    symbols=MappingProxyType(_HTMLTAG_SYMBOLS),
)
"""What a CONTENT HTML fragment inside an HTMLTAG destination may contain.

Per MS-OXRTFEX 2.1.3.1.4.2. Note ``\\_`` -- U+00AD here, U+2011 in :data:`BODY_CHARMAP`.
"""

BODY_CHARMAP = CharMap(
    words=MappingProxyType(_BODY_WORDS),
    symbols=MappingProxyType(_BODY_SYMBOLS),
)
"""What document body text may contain, outside any HTMLTAG destination.

Per the RTF 1.9.1 Special Characters table, plus the CRLF and horizontal tab conversions
that MS-OXRTFEX 2.2.3.2 requires.
"""
