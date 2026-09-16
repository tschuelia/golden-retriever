"""Tests for the font table.

The font table decides which code page every text byte in the document is decoded with,
so a mistake here does not raise -- it mojibakes one language's mail and nothing else.
Each case is therefore an inline font table with the resolved codec asserted by name.
"""

from collections.abc import Mapping

import pytest

from ottertf.fonts import (
    FontEntry,
    FontTable,
    parse_font_table,
    resolve_fonts,
)
from ottertf.groups import FONTTBL_WORD
from ottertf.result import Diagnostic, DiagnosticCode, FontInfo
from ottertf.tokenizer import Token, TokenKind, tokenize

SPEC_EXAMPLE = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl "
    b"{\\f0\\fmodern Courier New;}{\\f1\\fswiss Arial;}"
    b"{\\f2\\fswiss\\fcharset0 Arial;}}}"
)
"""The font table MS-OXRTFEX 2.2.3.2 uses as its illustration, verbatim."""

FLAT_EXAMPLE = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0{\\fonttbl"
    b"\\f0\\fmodern Courier New;\\f1\\fswiss Arial;\\f2\\fswiss\\fcharset0 Arial;}}"
)
"""The same table in the other shape the RTF 1.9.1 grammar allows.

``'{' \\fonttbl (<fontinfo> | ('{' <fontinfo> '}'))+ '}'`` -- entries either each in a
group of their own or flat inside the table's own group, separated by ``;``.
"""


def parse(document: bytes) -> FontTable:
    """Parse ``document``'s font table the way the driver will.

    Reads up to the ``\\fonttbl`` control word and hands the same token iterator over,
    which is the contract :func:`parse_font_table` documents.
    """
    tokens = tokenize(document)
    for token in tokens:
        if token.kind is TokenKind.WORD and token.name == FONTTBL_WORD:
            return parse_font_table(tokens)
    raise AssertionError("the test document has no font table")


def resolve(
    document: bytes, *, document_encoding: str = "cp1252"
) -> tuple[Mapping[int, FontInfo], tuple[Diagnostic, ...]]:
    return resolve_fonts(parse(document).entries, document_encoding=document_encoding)


def table(*entries: bytes, prefix: bytes = b"") -> bytes:
    """A minimal document whose font table holds ``entries``, each in its own group."""
    body = b"".join(b"{" + entry + b"}" for entry in entries)
    return b"{\\rtf1\\ansi" + prefix + b"{\\fonttbl" + body + b"}}"


def codes(diagnostics: tuple[Diagnostic, ...]) -> list[str]:
    return [diagnostic.code for diagnostic in diagnostics]


@pytest.mark.parametrize(
    "document", [SPEC_EXAMPLE, FLAT_EXAMPLE], ids=["grouped", "flat"]
)
def test_both_table_shapes_produce_the_same_entries(document: bytes) -> None:
    parsed = parse(document)
    assert parsed.closed
    assert parsed.entries == (
        FontEntry(font_id=0, name=b"Courier New", charset=None, codepage=None),
        FontEntry(font_id=1, name=b"Arial", charset=None, codepage=None),
        FontEntry(font_id=2, name=b"Arial", charset=0, codepage=None),
    )


@pytest.mark.parametrize(
    "document", [SPEC_EXAMPLE, FLAT_EXAMPLE], ids=["grouped", "flat"]
)
def test_both_table_shapes_resolve_the_same_way(document: bytes) -> None:
    fonts, diagnostics = resolve(document)
    assert diagnostics == ()
    assert fonts == {
        0: FontInfo(0, "Courier New", None, None, "cp1252"),
        1: FontInfo(1, "Arial", None, None, "cp1252"),
        2: FontInfo(2, "Arial", 0, None, "cp1252"),
    }


def test_the_table_ends_where_its_group_ends() -> None:
    """The driver hands over its own iterator and carries on with it afterwards, so the
    table's braces must not reach the driver's group stack."""
    tokens = tokenize(b"{\\fonttbl{\\f0\\fnil Arial;}}\\pard after")
    assert next(tokens).kind is TokenKind.GROUP_START
    assert next(tokens).name == FONTTBL_WORD

    parsed = parse_font_table(tokens)
    assert parsed.closed
    assert parsed.entries == (
        FontEntry(font_id=0, name=b"Arial", charset=None, codepage=None),
    )
    assert list(tokens) == [
        Token(TokenKind.WORD, name="pard"),
        Token(TokenKind.TEXT, b"after"),
    ]


def test_a_charset_names_a_code_page() -> None:
    """RTF 1.9.1: ``\\fcharsetN`` "implies that bytes in runs tagged with the associated
    ``\\fN`` are character codes in the codepage corresponding to the charset N"."""
    fonts, diagnostics = resolve(table(b"\\f0\\fnil\\fcharset128 MS Mincho;"))
    assert diagnostics == ()
    assert fonts[0] == FontInfo(0, "MS Mincho", 128, 932, "cp932")


def test_a_code_page_supersedes_a_charset() -> None:
    """RTF 1.9.1, twice: "if the ``\\cpgN`` does appear, it supersedes the code page
    corresponding to the ``\\fcharsetN``", and ``\\fcharsetN`` points at "the ``\\cpgN``
    control word, which, if it appears, supersedes the codepage given by
    ``\\fcharsetN``".

    The charset is still reported as declared, so the conflict stays visible.
    """
    fonts, diagnostics = resolve(table(b"\\f0\\fnil\\fcharset238\\cpg1251 Arial;"))
    assert diagnostics == ()
    assert fonts[0] == FontInfo(0, "Arial", 238, 1251, "cp1251")


def test_a_code_page_supersedes_a_charset_written_after_it() -> None:
    """The grammar puts ``\\cpgN`` last, but precedence is not about order."""
    fonts, _ = resolve(table(b"\\f0\\fnil\\cpg1251\\fcharset238 Arial;"))
    assert fonts[0].encoding == "cp1251"
    assert fonts[0].codepage == 1251


def test_a_code_page_alone_is_enough() -> None:
    fonts, diagnostics = resolve(table(b"\\f0\\fnil\\cpg932 MS Mincho;"))
    assert diagnostics == ()
    assert fonts[0] == FontInfo(0, "MS Mincho", None, 932, "cp932")


@pytest.mark.parametrize("declaration", [b"", b"\\fcharset0", b"\\fcharset1"])
def test_an_entry_naming_no_code_page_of_its_own_uses_the_documents(
    declaration: bytes,
) -> None:
    """``\\fcharset0`` is "the system ANSI code page" and ``\\fcharset1`` the rendering
    system's default; neither names a code page, so the document's declaration stands.

    ``codepage`` is ``None`` for all three, which is what that field means -- the
    document default applied.
    """
    fonts, diagnostics = resolve(
        table(b"\\f0\\fnil" + declaration + b" Arial;"), document_encoding="cp1250"
    )
    assert diagnostics == ()
    assert fonts[0].codepage is None
    assert fonts[0].encoding == "cp1250"


def test_a_symbol_font_is_reported_rather_than_guessed_at() -> None:
    """``\\fcharset2`` names a font that maps bytes to glyphs instead of characters, so
    no code page decodes it correctly."""
    fonts, diagnostics = resolve(table(b"\\f0\\ftech\\fcharset2 Symbol;"))
    assert fonts[0] == FontInfo(0, "Symbol", 2, None, "cp1252")
    assert codes(diagnostics) == [DiagnosticCode.SYMBOL_FONT_CHARSET]
    assert "0" in diagnostics[0].message


def test_a_charset_the_specification_does_not_define_is_reported() -> None:
    """RTF 1.9.1 lists a fixed set.

    Guessing a code page for anything else would mojibake a language silently instead of
    saying so.
    """
    fonts, diagnostics = resolve(table(b"\\f0\\fnil\\fcharset200 Odd;"))
    assert fonts[0].encoding == "cp1252"
    assert fonts[0].codepage is None
    assert fonts[0].charset == 200
    assert codes(diagnostics) == [DiagnosticCode.UNSUPPORTED_CODEPAGE]
    assert "200" in diagnostics[0].message


@pytest.mark.parametrize("codepage", [99999, 1200])
def test_a_code_page_with_no_decoder_falls_back_and_is_reported(codepage: int) -> None:
    """1200 is UTF-16LE, which is excluded deliberately: it is not byte-oriented, so
    decoding a run of ``\\'HH`` escapes with it would produce plausible garbage."""
    document = table(b"\\f0\\fnil\\cpg" + str(codepage).encode("ascii") + b" Odd;")
    fonts, diagnostics = resolve(document)
    assert fonts[0].encoding == "cp1252"
    assert fonts[0].codepage is None
    assert codes(diagnostics) == [DiagnosticCode.UNSUPPORTED_CODEPAGE]
    assert str(codepage) in diagnostics[0].message


def test_a_font_name_is_decoded_in_its_own_code_page() -> None:
    """A Japanese font's name is written in the font's own encoding, not the
    document's."""
    fonts, diagnostics = resolve(
        table(b"\\f0\\fnil\\fcharset128 \\'82\\'a0;"), document_encoding="cp1252"
    )
    assert diagnostics == ()
    assert fonts[0].name == "あ"


def test_an_alternate_name_group_does_not_become_the_font_name() -> None:
    """``<fontaltname>`` is ``'{\\*' \\falt #PCDATA '}'``, and the ``\\*`` rule skips
    it."""
    parsed = parse(table(b"\\f0\\fswiss\\fcharset0{\\*\\falt Courier New}Arial;"))
    assert parsed.entries == (
        FontEntry(font_id=0, name=b"Arial", charset=0, codepage=None),
    )


def test_a_semicolon_inside_an_ignorable_group_does_not_end_the_entry() -> None:
    """``<nontaggedname>`` is ``'{\\*' \\fname #PCDATA ';}'``.

    Its ``;`` would commit the
    entry early, losing the real name, if the group were not skipped whole.
    """
    parsed = parse(table(b"\\f0\\fnil{\\*\\fname Arial;}Arial Unicode MS;"))
    assert parsed.entries == (
        FontEntry(font_id=0, name=b"Arial Unicode MS", charset=None, codepage=None),
    )


def test_an_embedded_font_payload_does_not_become_the_font_name() -> None:
    """``<fontemb>`` is ``'{\\*' \\fontemb ...}`` and may nest further groups; the skip
    covers all of them."""
    parsed = parse(
        table(
            b"\\f0\\fnil{\\*\\fontemb\\fttruetype"
            b"{\\*\\fontfile\\cpg1252 arial.ttf}}Arial;"
        )
    )
    assert parsed.entries == (
        FontEntry(font_id=0, name=b"Arial", charset=None, codepage=None),
    )


def test_a_panose_group_does_not_become_the_font_name() -> None:
    parsed = parse(table(b"\\f0\\fnil{\\*\\panose 020b0604020202020204}Arial;"))
    assert parsed.entries[0].name == b"Arial"


@pytest.mark.parametrize(
    "entry",
    [
        b"\\f0\\fnil Ar\\~ial;",
        b"\\f0\\fnil\\fprq2 Arial;",
        b"\\f0\\fnil\\bin2 XXArial;",
    ],
    ids=["control-symbol", "parameterized-word", "binary-payload"],
)
def test_a_token_carrying_no_font_information_is_ignored(entry: bytes) -> None:
    """Only ``\\fN``, ``\\fcharsetN`` and ``\\cpgN`` are read, and only text and
    ``\\'hh`` escapes are name bytes.

    Everything else in the ``<fontinfo>`` production passes through: ``\\fprq`` is part of
    it, a control symbol in a font name is not but costs nothing to tolerate, and a
    ``\\binN`` payload here is malformed input that must not end up in a name.
    """
    parsed = parse(table(entry))
    assert parsed.entries == (
        FontEntry(font_id=0, name=b"Arial", charset=None, codepage=None),
    )


def test_an_entry_group_closing_without_a_semicolon_still_counts() -> None:
    """The grammar requires the ``;``; a document missing one is still readable."""
    parsed = parse(table(b"\\f0\\fnil Arial"))
    assert parsed.closed
    assert parsed.entries == (
        FontEntry(font_id=0, name=b"Arial", charset=None, codepage=None),
    )


def test_a_new_font_word_ends_the_previous_entry() -> None:
    """A flat table with no separators at all: the ``\\fN`` is the only boundary
    left."""
    parsed = parse(b"{\\rtf1{\\fonttbl\\f0\\fnil Arial\\f1\\fnil Courier}}")
    assert parsed.entries == (
        FontEntry(font_id=0, name=b"Arial", charset=None, codepage=None),
        FontEntry(font_id=1, name=b"Courier", charset=None, codepage=None),
    )


def test_a_truncated_table_keeps_what_it_had() -> None:
    parsed = parse(b"{\\rtf1{\\fonttbl{\\f0\\fnil Arial;}{\\f1\\fnil Courier")
    assert not parsed.closed
    assert [entry.font_id for entry in parsed.entries] == [0, 1]
    assert parsed.entries[1].name == b"Courier"


def test_an_empty_table_is_not_an_error() -> None:
    parsed = parse(b"{\\rtf1{\\fonttbl}}")
    assert parsed == FontTable(entries=(), closed=True)
    assert resolve_fonts((), document_encoding="cp1252") == ({}, ())


def test_a_repeated_font_identifier_keeps_the_last_entry() -> None:
    parsed = parse(table(b"\\f0\\fnil Arial;", b"\\f0\\fnil\\fcharset238 Courier;"))
    assert parsed.entries == (
        FontEntry(font_id=0, name=b"Courier", charset=238, codepage=None),
    )


def test_text_belonging_to_no_entry_is_dropped() -> None:
    """After an entry's ``;`` and before the next ``\\fN`` there is no entry to append
    to."""
    parsed = parse(b"{\\rtf1{\\fonttbl\\f0\\fnil Arial; stray \\f1\\fnil Courier;}}")
    assert parsed.entries == (
        FontEntry(font_id=0, name=b"Arial", charset=None, codepage=None),
        FontEntry(font_id=1, name=b"Courier", charset=None, codepage=None),
    )


def test_a_font_word_without_an_identifier_opens_nothing() -> None:
    parsed = parse(b"{\\rtf1{\\fonttbl\\f\\fnil Arial;}}")
    assert parsed.entries == ()


def test_surrounding_whitespace_is_not_part_of_a_name() -> None:
    fonts, _ = resolve(table(b"\\f0\\fnil   Arial   ;"))
    assert fonts[0].name == "Arial"


def test_an_entry_with_no_name_reports_none() -> None:
    """``None`` rather than ``""``, so a caller can tell "declared nothing" from
    "declared an empty name"."""
    fonts, diagnostics = resolve(table(b"\\f0\\fnil\\fcharset238;"))
    assert diagnostics == ()
    assert fonts[0] == FontInfo(0, None, 238, 1250, "cp1250")


def test_diagnostics_follow_the_order_the_entries_were_declared() -> None:
    fonts, diagnostics = resolve(
        table(
            b"\\f0\\fnil\\fcharset2 Symbol;",
            b"\\f1\\fnil\\fcharset0 Arial;",
            b"\\f2\\fnil\\cpg99999 Odd;",
        )
    )
    assert set(fonts) == {0, 1, 2}
    assert codes(diagnostics) == [
        DiagnosticCode.SYMBOL_FONT_CHARSET,
        DiagnosticCode.UNSUPPORTED_CODEPAGE,
    ]


@pytest.mark.parametrize(
    "document",
    [
        b"{\\rtf1{\\fonttbl",
        b"{\\rtf1{\\fonttbl{",
        b"{\\rtf1{\\fonttbl{\\f0",
        b"{\\rtf1{\\fonttbl{\\f0\\fcharset",
        b"{\\rtf1{\\fonttbl;;;}}",
        b"{\\rtf1{\\fonttbl}}}}}}",
        b"{\\rtf1{\\fonttbl{\\*}}}",
        b"{\\rtf1{\\fonttbl\\bin4 ab}}",
        b"{\\rtf1{\\fonttbl\\f-1\\fnil A;}}",
        b"{\\rtf1{\\fonttbl\\f0\\cpg-5 A;}}",
    ],
)
def test_malformed_tables_are_parsed_and_resolved_without_raising(
    document: bytes,
) -> None:
    """Truncated, empty and nonsensical tables get an answer.

    A negative ``\\fN`` or ``\\cpgN`` is kept as declared rather than rejected: the
    identifier only has to match what the body's own ``\\fN`` says, and a code page
    that resolves to no codec already has a fallback path.
    """
    fonts, _ = resolve(document)
    assert all(isinstance(info, FontInfo) for info in fonts.values())
