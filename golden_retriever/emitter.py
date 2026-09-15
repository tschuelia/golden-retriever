"""Deferred decoding of the content a driver emits.

Design
======

Nothing is decoded while the document is being scanned. Which code page a text
byte belongs to depends on the font in effect -- MS-OXRTFEX 2.2.3.2 requires a
reader to "use the code page information, as specified for each font in a font
table" and to "track changes to the current font" -- and ``\\deffN``, or in
malformed input the text itself, can precede ``{\\fonttbl...}``. Decoding eagerly
would mean guessing. A driver instead appends two kinds of thing:

- **Decoded text**, for everything whose character is already known: a ``\\uN``
  escape, and every control word or symbol one of the character tables defines.
- **Undecoded bytes**, tagged with the font in effect, for document text and
  ``\\'hh`` escapes.

Consecutive bytes carrying the same font accumulate into one run, and
:meth:`Emitter.resolve` decodes every run at the end, when the font table is
complete.

Why runs, rather than one byte at a time
========================================

RTF 1.9.1 (East Asian RTF, Escaped Expressions): "when an RTF reader encounters
raw characters in the leading-byte range of the double-byte character, it regards
the next character as the trailing byte of the double-byte character and combines
the two characters into one double-byte character". The validity table there
allows a lead byte and its trailing byte to be any mix of raw and escaped, so
``\\'82\\'a0``, an escaped lead byte followed by a raw one, and two raw bytes all
have to arrive at the decoder as one contiguous pair.

That is also why one incremental decoder is carried across adjacent runs that
resolve to the same encoding: in ``\\f0\\'82\\f5\\'a0`` the pair is split across
two runs, and it is still one character whenever both fonts name the same code
page.

Appending decoded text closes the open run, because a character that is already
known belongs between the bytes on either side of it. It is also what stops a
dangling lead byte from pairing with a byte on the far side of a ``\\par``.

Nothing is ever removed
=======================

Suppressed content -- an HTMLRTF region, a non-visible destination, the ANSI
representation that follows a ``\\uN`` escape -- is never appended in the first
place. This class has no delete operation, and a segment records nothing about
where in the document it came from, so deleting content by source position is not
a mistake that can be made here.

Failure modes
=============

Nothing in this module raises, whatever the content, and nothing it records
escalates under ``strict``: an unknown font, bytes their code page does not
define and an unpaired surrogate are all damage inside the document rather than
structural damage to it. Each becomes U+FFFD, or a fallback encoding, plus a
diagnostic.

The result is always encodable as UTF-8. Two things could otherwise leave a lone
surrogate in it -- a ``\\uN`` surrogate whose partner never arrived, and a code
page whose decoder can produce one, which the UTF-7 of ``\\ansicpg65000`` can --
so the resolved text is swept for surrogates once at the end.

One diagnostic is approximate. Undecodable bytes are counted by counting the
U+FFFD characters the decoders produced, so a document that itself encodes U+FFFD
is reported as having undecodable bytes. That reports a problem where there is
none, in a diagnostic that never escalates, and the text is identical either way;
the alternative is a second decoding pass over every byte of every document.
"""

import codecs
import re
from collections.abc import Mapping
from typing import NamedTuple

from golden_retriever.result import Diagnostic, DiagnosticCode

__all__ = ["REPLACEMENT_CHARACTER", "Emitted", "Emitter"]

REPLACEMENT_CHARACTER = "\ufffd"
"""What every unrepresentable character becomes.

Written as an escape, like the character tables: a literal U+FFFD in the source is
indistinguishable from the mojibake it is here to describe.
"""

# RTF 1.9.1: "Most RTF control words accept signed 16-bit numbers as arguments.
# For these control words, Unicode values greater than 32767 are expressed as
# negative numbers. For example, the character code U+F020 is given by \u-4064."
_SIXTEEN_BIT_WRAP = 0x10000

_HIGH_SURROGATE_FIRST = 0xD800
_HIGH_SURROGATE_LAST = 0xDBFF
_LOW_SURROGATE_FIRST = 0xDC00
_LOW_SURROGATE_LAST = 0xDFFF
_SUPPLEMENTARY_BASE = 0x10000
_LOW_SURROGATE_BITS = 10
_MAX_CODE_POINT = 0x10FFFF

_LONE_SURROGATE = re.compile("[\ud800-\udfff]")


class Emitted(NamedTuple):
    """What :meth:`Emitter.resolve` produced."""

    text: str
    """The decoded content, in document order."""

    diagnostics: tuple[Diagnostic, ...]
    """Problems found while appending and while decoding, in that order."""


class _ByteRun:
    """A run of undecoded bytes that all carry the same font.

    Mutable and private: a driver appends to the open run through
    :meth:`Emitter.add_bytes` and never sees one of these.
    """

    __slots__ = ("chunks", "font_id")

    def __init__(self, font_id: int | None) -> None:
        self.font_id = font_id
        """The ``N`` of the ``\\fN`` in effect, or ``None`` for the document default."""

        self.chunks: list[bytes] = []
        """The bytes, joined once at resolve time."""


class Emitter:
    """Collects what a driver emits, and decodes it once the font table is known.

    Append with :meth:`add_bytes`, :meth:`add_text` and :meth:`add_unicode`, in
    document order, then call :meth:`resolve` exactly once.
    """

    __slots__ = ("_diagnostics", "_open_run", "_pending_high_surrogate", "_segments")

    def __init__(self) -> None:
        self._segments: list[str | _ByteRun] = []
        self._open_run: _ByteRun | None = None
        self._pending_high_surrogate: int | None = None
        self._diagnostics: list[Diagnostic] = []

    def add_bytes(self, data: bytes, font_id: int | None) -> None:
        """Append undecoded document bytes.

        :param data: Raw bytes, from document text or a ``\\'hh`` escape.
        :param font_id: The ``N`` of the ``\\fN`` in effect, or ``None`` to decode
            these bytes in the document's code page.
        """
        self._resolve_pending_surrogate()
        run = self._open_run
        if run is None or run.font_id != font_id:
            run = _ByteRun(font_id)
            self._segments.append(run)
            self._open_run = run
        run.chunks.append(data)

    def add_text(self, text: str) -> None:
        """Append text whose characters are already known.

        :param text: What a control word, control symbol or escape stands for.
        """
        self._resolve_pending_surrogate()
        self._append_text(text)

    def add_unicode(self, value: int) -> None:
        """Append the character a ``\\uN`` control word names.

        Surrogates are paired with the following ``\\uN``, since RTF has no other way
        to write a character outside the basic multilingual plane. A surrogate that
        finds no partner becomes :data:`REPLACEMENT_CHARACTER`.

        :param value: The control word's parameter, as the scanner reports it:
            "the Unicode character value expressed as a decimal number" (RTF 1.9.1),
            negative if the writer expressed it as a signed 16-bit integer.
        """
        code_unit = value + _SIXTEEN_BIT_WRAP if value < 0 else value

        pending = self._pending_high_surrogate
        if pending is not None:
            self._pending_high_surrogate = None
            if _LOW_SURROGATE_FIRST <= code_unit <= _LOW_SURROGATE_LAST:
                self._append_text(chr(_combine_surrogates(pending, code_unit)))
                return
            self._replace_unpaired_surrogate(pending)

        if _HIGH_SURROGATE_FIRST <= code_unit <= _HIGH_SURROGATE_LAST:
            self._pending_high_surrogate = code_unit
        elif _LOW_SURROGATE_FIRST <= code_unit <= _LOW_SURROGATE_LAST:
            self._replace_unpaired_surrogate(code_unit)
        elif 0 <= code_unit <= _MAX_CODE_POINT:
            self._append_text(chr(code_unit))
        else:
            # A parameter naming no character at all. There is nothing to
            # diagnose about the document's data, only about its syntax.
            self._append_text(REPLACEMENT_CHARACTER)

    def resolve(
        self, *, font_encodings: Mapping[int, str], document_encoding: str
    ) -> Emitted:
        """Decode everything appended so far.

        Call once, after the whole document has been scanned. Codec names are taken
        as given: they come from
        :func:`~golden_retriever.codepages.encoding_for_codepage`, which only ever
        returns a name :mod:`codecs` resolves.

        :param font_encodings: Codec name per ``\\fN`` identifier, from the completed
            font table. A font absent from this mapping is reported as unknown and
            decoded with ``document_encoding``.
        :param document_encoding: Codec for bytes carrying no font, i.e. the code page
            of ``\\ansicpgN`` or the caller's fallback.
        """
        self._resolve_pending_surrogate()

        diagnostics = list(self._diagnostics)
        parts: list[str] = []
        decoder: codecs.IncrementalDecoder | None = None
        encoding: str | None = None
        replaced = 0
        unknown_fonts: set[int] = set()

        def flush() -> None:
            """Finish the open decoder, so an incomplete sequence becomes U+FFFD here
            rather than merging with whatever comes next."""
            nonlocal decoder, encoding, replaced
            if decoder is None:
                return
            tail = decoder.decode(b"", final=True)
            replaced += tail.count(REPLACEMENT_CHARACTER)
            parts.append(tail)
            decoder = None
            encoding = None

        for segment in self._segments:
            if isinstance(segment, str):
                flush()
                parts.append(segment)
                continue

            font_id = segment.font_id
            run_encoding = document_encoding
            if font_id is not None:
                named = font_encodings.get(font_id)
                if named is None:
                    if font_id not in unknown_fonts:
                        unknown_fonts.add(font_id)
                        diagnostics.append(
                            Diagnostic(
                                DiagnosticCode.UNKNOWN_FONT,
                                f"font {font_id} is not in the font table; its text "
                                f"was decoded as {document_encoding}",
                            )
                        )
                else:
                    run_encoding = named

            if decoder is None or run_encoding != encoding:
                flush()
                decoder = codecs.getincrementaldecoder(run_encoding)(errors="replace")
                encoding = run_encoding
            decoded = decoder.decode(b"".join(segment.chunks))
            replaced += decoded.count(REPLACEMENT_CHARACTER)
            parts.append(decoded)

        flush()

        text, scrubbed = _LONE_SURROGATE.subn(REPLACEMENT_CHARACTER, "".join(parts))
        if replaced:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.UNDECODABLE_BYTES,
                    f"{replaced} byte sequence(s) were not valid in their code page "
                    f"and became U+FFFD",
                )
            )
        if scrubbed:
            diagnostics.append(
                Diagnostic(
                    DiagnosticCode.UNPAIRED_SURROGATE,
                    f"{scrubbed} decoded surrogate(s) had no partner and became U+FFFD",
                )
            )
        return Emitted(text, tuple(diagnostics))

    def _append_text(self, text: str) -> None:
        """Append decoded text, closing the open byte run."""
        self._segments.append(text)
        self._open_run = None

    def _resolve_pending_surrogate(self) -> None:
        """Give up on a high surrogate whose partner did not follow immediately."""
        pending = self._pending_high_surrogate
        if pending is not None:
            self._pending_high_surrogate = None
            self._replace_unpaired_surrogate(pending)

    def _replace_unpaired_surrogate(self, code_unit: int) -> None:
        self._append_text(REPLACEMENT_CHARACTER)
        self._diagnostics.append(
            Diagnostic(
                DiagnosticCode.UNPAIRED_SURROGATE,
                f"\\u escape for surrogate U+{code_unit:04X} had no partner and "
                f"became U+FFFD",
            )
        )


def _combine_surrogates(high: int, low: int) -> int:
    """The code point a surrogate pair stands for."""
    return (
        _SUPPLEMENTARY_BASE
        + ((high - _HIGH_SURROGATE_FIRST) << _LOW_SURROGATE_BITS)
        + (low - _LOW_SURROGATE_FIRST)
    )
