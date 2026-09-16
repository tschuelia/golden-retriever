"""Reading the font table, and resolving each entry to a codec.

Why the font table is read at all
=================================

MS-OXRTFEX 2.2.3.2 makes it the one non-visible destination a de-encapsulating
reader may not skip: "Ignore and skip any standard RTF destination groups that do
not produce visible text ... except for the \\fonttbl group. The de-encapsulating
RTF reader SHOULD process a font table group and at least remember the code page
that corresponds to each font." Its own rule for text says to interpret bytes "in
a code page that corresponds to the current font", so the table is what makes a
document with more than one script readable at all.

Syntax, per RTF 1.9.1 (Font and Color Tables)
=============================================

::

    <fonttbl>  '{' \\fonttbl (<fontinfo> | ('{' <fontinfo> '}'))+ '}'
    <fontinfo> <themefont>? \\fN <fontfamily> \\fcharsetN? \\fprq? <panose>?
               <nontaggedname>? <fontemb>? \\cpgN? <fontname> <fontaltname>? ';'

Two shapes, then: each entry in a group of its own, or all of them flat inside the
table's group separated by ``;``. Both occur in real documents and both are parsed
here. Of the whole production only three control words carry information this
package needs -- ``\\fN`` opens an entry, ``\\fcharsetN`` and ``\\cpgN`` name its
code page -- and the font name is the text up to the ``;``.

Everything the grammar wraps in ``{\\*`` -- ``<panose>``, ``<nontaggedname>``,
``<fontemb>``, ``<fontaltname>`` -- is skipped by the ``\\*`` rule rather than by
name. That is not just economy: ``<nontaggedname>`` is ``'{\\*' \\fname #PCDATA
';}'``, so it contains a ``;`` of its own, and a reader that did not skip the group
would commit the entry early and lose the real font name.

Which code page wins
====================

``\\cpgN``, when both are present. RTF 1.9.1 says so twice: "if the charset doesn't
exist, the codepage may be given by the \\cpgN control word ... If the \\cpgN does
appear, it supersedes the code page corresponding to the \\fcharsetN", and, under
``\\fcharsetN``, "see also the \\cpgN control word, which, if it appears, supersedes
the codepage given by \\fcharsetN".

An entry naming neither, or naming ``\\fcharset0`` or ``\\fcharset1``, decodes in the
document's code page -- see :data:`~ottertf.codepages.ANSI_CHARSET`.

Leniency
========

Nothing here raises, and nothing is discarded that could still be read:

- A missing ``;`` is not fatal. An entry is committed by its ``;``, by the ``}`` of
  its own group, by the next ``\\fN``, or by the end of the table, whichever comes
  first.
- A truncated table -- one whose ``}`` never arrives -- still yields every entry it
  did contain, and reports :attr:`FontTable.closed` as ``False`` so the caller can
  record the structural damage.
- A repeated ``\\fN`` keeps the last entry, since that is what a writer emitting a
  correction would mean.
- Text between an entry's ``;`` and the next ``\\fN`` belongs to no entry and is
  dropped. In a well-formed table there is none.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import NamedTuple

from ottertf.codepages import (
    FCHARSET_TO_CODEPAGE,
    SYMBOL_CHARSET,
    encoding_for_codepage,
)
from ottertf.groups import IGNORABLE_SYMBOL
from ottertf.result import Diagnostic, DiagnosticCode, FontInfo
from ottertf.tokenizer import Token, TokenKind

__all__ = [
    "CHARSET_WORD",
    "CODEPAGE_WORD",
    "FONT_WORD",
    "FontEntry",
    "FontTable",
    "parse_font_table",
    "resolve_fonts",
]

FONT_WORD = "f"
"""``\\fN``: opens a font entry inside the table, and selects a font outside it."""

CHARSET_WORD = "fcharset"
"""``\\fcharsetN``: "specifies the character set of a font in the font table"."""

CODEPAGE_WORD = "cpg"
"""``\\cpgN``: a code page named directly, which supersedes ``\\fcharsetN``."""

_SEMICOLON = b";"


class FontEntry(NamedTuple):
    """One ``<fontinfo>`` production, as written.

    Nothing is resolved yet, and the name is still bytes: which codec applies to it
    depends on the entry's own code page, which depends on the document's, which is
    not known until the header has been read. :func:`resolve_fonts` does that part.
    """

    font_id: int
    """The ``N`` in ``\\fN``."""

    name: bytes
    """The undecoded font name, empty if the entry declared none."""

    charset: int | None
    """The ``N`` in ``\\fcharsetN``, or ``None``."""

    codepage: int | None
    """The ``N`` in ``\\cpgN``, or ``None``."""


@dataclass(frozen=True, slots=True)
class FontTable:
    """What one ``{\\fonttbl ...}`` group contained."""

    entries: tuple[FontEntry, ...]
    """The entries, in the order the table declared them."""

    closed: bool
    """Whether the table's own ``}`` was found.

    ``False`` means the document ended inside the font table. The entries are still
    usable; the caller decides whether to report the truncation.
    """


class _OpenEntry:
    """An entry being accumulated, before its terminator arrives."""

    __slots__ = ("charset", "codepage", "depth", "font_id", "name")

    def __init__(self, font_id: int, depth: int) -> None:
        self.font_id = font_id
        self.name = bytearray()
        self.charset: int | None = None
        self.codepage: int | None = None

        self.depth = depth
        """The group depth the ``\\fN`` was found at.

        The entry ends when *that* group closes. Without this, the ``}`` of a nested
        ``{\\*...}`` group -- which every font entry with an alternate name, a PANOSE
        block or an embedded font file contains -- would end the entry before its name
        had been read.
        """

    def freeze(self) -> FontEntry:
        return FontEntry(
            font_id=self.font_id,
            name=bytes(self.name),
            charset=self.charset,
            codepage=self.codepage,
        )


def parse_font_table(tokens: Iterator[Token]) -> FontTable:
    """Read one font table, consuming tokens up to and including its closing ``}``.

    Call this with the driver's own token iterator, positioned just after the
    ``{`` and the ``\\fonttbl`` that opened the table. On return the iterator is
    positioned on whatever followed the table, so the caller resumes as if the group
    had never been there -- the table's braces never reach the caller's group stack.

    :param tokens: The document's remaining tokens.
    """
    entries: dict[int, FontEntry] = {}
    open_entry: _OpenEntry | None = None
    # The font table's own group is already open, so the closing brace that ends it
    # is the one that takes this back to zero.
    depth = 1
    closed = False
    at_group_start = False
    # The depth at which a "\*" group began, or None. Everything at or below it is
    # ignored -- see this module's docstring on <nontaggedname>.
    skip_from_depth: int | None = None

    for token in tokens:
        kind = token.kind

        if kind is TokenKind.GROUP_START:
            depth += 1
            at_group_start = True
            continue

        if kind is TokenKind.GROUP_END:
            depth -= 1
            at_group_start = False
            if skip_from_depth is not None and depth < skip_from_depth:
                skip_from_depth = None
            if depth <= 0:
                closed = True
                break
            if open_entry is not None and depth < open_entry.depth:
                # The group holding the entry has closed, with or without a ";".
                _commit(entries, open_entry)
                open_entry = None
            continue

        opens_group, at_group_start = at_group_start, False
        if skip_from_depth is not None:
            continue

        if kind is TokenKind.SYMBOL:
            if opens_group and token.name == IGNORABLE_SYMBOL:
                skip_from_depth = depth
            continue

        if kind is TokenKind.WORD:
            if token.name == FONT_WORD and token.param is not None:
                if open_entry is not None:
                    _commit(entries, open_entry)
                open_entry = _OpenEntry(token.param, depth)
            elif open_entry is not None and token.param is not None:
                if token.name == CHARSET_WORD:
                    open_entry.charset = token.param
                elif token.name == CODEPAGE_WORD:
                    open_entry.codepage = token.param
            continue

        if open_entry is None:
            continue
        if kind is TokenKind.HEX:
            # A font name may be written with escapes, so these are name bytes.
            open_entry.name += token.data
        elif kind is TokenKind.TEXT:
            head, terminator, _rest = token.data.partition(_SEMICOLON)
            open_entry.name += head
            if terminator:
                _commit(entries, open_entry)
                open_entry = None

    if open_entry is not None:
        _commit(entries, open_entry)

    return FontTable(entries=tuple(entries.values()), closed=closed)


def _commit(entries: dict[int, FontEntry], open_entry: _OpenEntry) -> None:
    """Store a finished entry, replacing any earlier one with the same identifier."""
    entries[open_entry.font_id] = open_entry.freeze()


def resolve_fonts(
    entries: Iterable[FontEntry], *, document_encoding: str
) -> tuple[Mapping[int, FontInfo], tuple[Diagnostic, ...]]:
    """Resolve each entry to the codec its text will actually be decoded with.

    A font that names no usable code page falls back to ``document_encoding`` and is
    reported, rather than raising: the alternative is discarding a message because one
    font entry in its table named a code page this Python build has no codec for.

    :param entries: The entries of one :class:`FontTable`.
    :param document_encoding: The codec for the document's own code page, used
        wherever an entry names none of its own.
    :returns: The resolved table keyed by ``\\fN`` identifier, and any diagnostics, in
        the order the entries were declared.
    """
    resolved: dict[int, FontInfo] = {}
    diagnostics: list[Diagnostic] = []

    for entry in entries:
        codepage, diagnostic = _codepage_for(entry)
        if diagnostic is not None:
            diagnostics.append(diagnostic)

        encoding = document_encoding
        if codepage is not None:
            named = encoding_for_codepage(codepage)
            if named is None:
                diagnostics.append(
                    Diagnostic(
                        DiagnosticCode.UNSUPPORTED_CODEPAGE,
                        f"font {entry.font_id} names code page {codepage}, which has "
                        f"no decoder; its text was decoded as {document_encoding}",
                    )
                )
                # The field means "the code page in force", and the document's is
                # what ended up in force.
                codepage = None
            else:
                encoding = named

        name = entry.name.decode(encoding, errors="replace").strip()
        resolved[entry.font_id] = FontInfo(
            font_id=entry.font_id,
            name=name or None,
            charset=entry.charset,
            codepage=codepage,
            encoding=encoding,
        )

    return resolved, tuple(diagnostics)


def _codepage_for(entry: FontEntry) -> tuple[int | None, Diagnostic | None]:
    """The code page an entry declares, or ``None`` to mean the document's.

    RTF 1.9.1: ``\\cpgN``, "if it appears, supersedes the codepage given by
    ``\\fcharsetN``".
    """
    if entry.codepage is not None:
        return entry.codepage, None

    charset = entry.charset
    if charset is None:
        return None, None

    if charset == SYMBOL_CHARSET:
        # A symbol font maps bytes to glyphs rather than to characters, so no code
        # page can decode it correctly. Reported so mojibake here is explicable.
        return None, Diagnostic(
            DiagnosticCode.SYMBOL_FONT_CHARSET,
            f"font {entry.font_id} declares \\fcharset2 (Symbol), which names no "
            f"code page; its text was decoded in the document's",
        )

    if charset not in FCHARSET_TO_CODEPAGE:
        # RTF 1.9.1 defines a fixed set of charsets. Guessing a code page for one it
        # does not define would silently mojibake a language rather than say so.
        return None, Diagnostic(
            DiagnosticCode.UNSUPPORTED_CODEPAGE,
            f"font {entry.font_id} declares \\fcharset{charset}, which the "
            f"specification does not define; its text was decoded in the document's "
            f"code page",
        )

    return FCHARSET_TO_CODEPAGE[charset], None
