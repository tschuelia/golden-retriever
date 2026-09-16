"""Resolving RTF code page declarations to Python codecs.

Provenance
==========

The tables here were transcribed from two published Microsoft documents.

- ``FCHARSET_TO_CODEPAGE`` follows the ``\\fcharsetN`` table in the `Rich Text
  Format (RTF) Specification, version 1.9.1
  <https://go.microsoft.com/fwlink/?LinkId=120924>`_, which enumerates the
  Windows ``*_CHARSET`` constants a font entry may declare.
- ``CODEPAGE_TO_CODEC`` follows `Code Page Identifiers
  <https://learn.microsoft.com/en-us/windows/win32/intl/code-page-identifiers>`_.

Design
======

Most of the work is done by :mod:`codecs`, not by a table. Every code page an
RTF document realistically declares -- 437, 850, 852, 874, 932, 936, 949, 950,
1250-1258, 1361, 65001 and the rest of the OEM and Windows ranges -- already
resolves under the name ``cp<N>``. ``CODEPAGE_TO_CODEC`` therefore holds only
the identifiers that are *not* spelled that way: the ISO 8859, KOI8, Mac and
ISO-2022 families.

This keeps the hand-maintained data small, which matters because a
transcription typo in a code page table does not fail loudly -- it silently
mojibakes one language's mail.
"""

import codecs
from collections.abc import Mapping
from types import MappingProxyType

__all__ = [
    "ANSI_CHARSET",
    "CODEPAGE_TO_CODEC",
    "DEFAULT_CHARSET",
    "FCHARSET_TO_CODEPAGE",
    "INVALID_CHARSET",
    "SYMBOL_CHARSET",
    "encoding_for_codepage",
]

ANSI_CHARSET = 0
"""``\\fcharset0``: "the system ANSI code page", i.e. the document's ``\\ansicpg``."""

DEFAULT_CHARSET = 1
"""``\\fcharset1``: whatever the rendering system's default is."""

SYMBOL_CHARSET = 2
"""``\\fcharset2``: a symbol font.

Symbol fonts map bytes to glyphs, not to characters, so no code page can decode
them correctly. Callers get a
:attr:`~ottertf.DiagnosticCode.SYMBOL_FONT_CHARSET` diagnostic and the
document default is used.
"""

INVALID_CHARSET = 3
"""``\\fcharset3``: explicitly declared invalid by the specification."""

_FCHARSET_TO_CODEPAGE: dict[int, int | None] = {
    # A value of None means "this charset names no distinct code page; use the
    # document's \ansicpg". Membership in this mapping is what separates a
    # charset the specification defines from one it does not.
    ANSI_CHARSET: None,
    DEFAULT_CHARSET: None,
    SYMBOL_CHARSET: None,
    INVALID_CHARSET: None,
    77: 10000,  # Mac Roman
    128: 932,  # Shift JIS, Japanese
    129: 949,  # Hangul, Korean
    130: 1361,  # Johab, Korean
    134: 936,  # GB2312, simplified Chinese
    136: 950,  # Big5, traditional Chinese
    161: 1253,  # Greek
    162: 1254,  # Turkish
    163: 1258,  # Vietnamese
    177: 1255,  # Hebrew
    178: 1256,  # Arabic
    # 179 (Arabic Traditional) and 180 (Arabic user) have no code page of their
    # own; 1256 is the closest the specification offers. Likewise 181 (Hebrew
    # user) and 1255. RTF 1.9.1 defines nothing above 181 except the three
    # below, so any other value is treated as unknown rather than guessed at.
    179: 1256,
    180: 1256,
    181: 1255,
    186: 1257,  # Baltic
    204: 1251,  # Russian
    222: 874,  # Thai
    238: 1250,  # Eastern European
    254: 437,  # OEM United States
    255: 850,  # OEM multilingual Latin 1
}

FCHARSET_TO_CODEPAGE: Mapping[int, int | None] = MappingProxyType(_FCHARSET_TO_CODEPAGE)
"""``\\fcharsetN`` to Windows code page.

``None`` means the charset names no code page of its own and the document default
applies. A charset *absent* from this mapping is one the specification does not define;
the caller should fall back and record a diagnostic rather than guess.
"""

_CODEPAGE_TO_CODEC: dict[int, str] = {
    # Only identifiers that do not resolve as "cp<N>" need an entry here.
    708: "iso8859_6",  # Arabic ASMO 708
    # Mac code pages. 10005 (Hebrew), 10008 (simplified Chinese), 10017
    # (Ukrainian) and 10021 (Thai) are deliberately absent: CPython ships no
    # codec for them, so they fall through to the fallback and a diagnostic.
    10000: "mac_roman",
    10001: "shift_jis",
    10002: "big5",
    10003: "euc_kr",
    10004: "mac_arabic",
    10006: "mac_greek",
    10007: "mac_cyrillic",
    10010: "mac_romanian",
    10029: "mac_latin2",
    10079: "mac_iceland",
    10081: "mac_turkish",
    10082: "mac_croatian",
    20127: "ascii",  # US-ASCII
    20866: "koi8_r",  # Cyrillic KOI8-R
    21866: "koi8_u",  # Cyrillic KOI8-U
    # ISO 8859 family.
    28591: "iso8859_1",
    28592: "iso8859_2",
    28593: "iso8859_3",
    28594: "iso8859_4",
    28595: "iso8859_5",
    28596: "iso8859_6",
    28597: "iso8859_7",
    28598: "iso8859_8",
    28599: "iso8859_9",
    28603: "iso8859_13",
    28605: "iso8859_15",
    38598: "iso8859_8",  # ISO 8859-8 Hebrew, logical ordering
    # ISO 2022 and the East Asian multi-byte families.
    50220: "iso2022_jp",
    50221: "iso2022_jp_2",
    50222: "iso2022_jp",
    51932: "euc_jp",
    51949: "euc_kr",
    54936: "gb18030",
    65000: "utf_7",
}

CODEPAGE_TO_CODEC: Mapping[int, str] = MappingProxyType(_CODEPAGE_TO_CODEC)
"""Windows code page to Python codec, for identifiers not spelled ``cp<N>``."""

_EXCLUDED_CODEPAGES = frozenset(
    {
        # UTF-16 and UTF-32. These are not byte-oriented code pages: an RTF
        # document declaring one is nonsense, and decoding a run of \'HH escapes
        # as UTF-16 would produce garbage rather than fail. Excluding them
        # explicitly means a future CPython gaining a "cp1200" alias cannot
        # silently change our behavior.
        1200,  # UTF-16LE
        1201,  # UTF-16BE
        12000,  # UTF-32LE
        12001,  # UTF-32BE
    }
)


def encoding_for_codepage(codepage: int) -> str | None:
    """Return a Python codec name for ``codepage``, or ``None`` if there is none.

    Resolution order: the explicit alias table, then ``cp<N>``, then the
    zero-padded ``cp<NNN>``. The last step exists because CPython names the EBCDIC
    code pages with a fixed three-digit width -- code page 37 is ``cp037``, and
    ``cp37`` does not resolve.

    ``None`` means "no decoder available"; the caller should fall back to the
    document default and record an
    :attr:`~ottertf.DiagnosticCode.UNSUPPORTED_CODEPAGE` diagnostic
    rather than raise, unless running in strict mode.
    """
    if codepage in _EXCLUDED_CODEPAGES:
        return None

    alias = _CODEPAGE_TO_CODEC.get(codepage)
    if alias is not None:
        return alias

    if codepage < 0:
        return None

    for candidate in (f"cp{codepage}", f"cp{codepage:03d}"):
        try:
            codecs.lookup(candidate)
        except LookupError:
            continue
        return candidate
    return None
