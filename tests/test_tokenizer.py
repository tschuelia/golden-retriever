"""Tests for the RTF scanner.

Every test names an exact token sequence for a byte literal, so the RTF is the
documentation of the assertion. The scanner is the one component every other
component reads through: a wrong token here does not fail, it quietly changes what
the document says.
"""

import pytest

from golden_retriever.charmap import BODY_CHARMAP
from golden_retriever.tokenizer import (
    MAX_CONTROL_WORD_LETTERS,
    MAX_PARAMETER_DIGITS,
    Token,
    TokenKind,
    tokenize,
)

GROUP_START = Token(TokenKind.GROUP_START)
GROUP_END = Token(TokenKind.GROUP_END)


def scan(data: bytes) -> list[Token]:
    """The whole token sequence, for comparing against a literal list."""
    return list(tokenize(data))


def text(data: bytes) -> Token:
    return Token(TokenKind.TEXT, data)


def word(name: str, param: int | None = None) -> Token:
    return Token(TokenKind.WORD, name=name, param=param)


def symbol(char: str) -> Token:
    return Token(TokenKind.SYMBOL, name=char)


def octet(value: int) -> Token:
    return Token(TokenKind.HEX, bytes((value,)), param=value)


def test_empty_input_yields_nothing() -> None:
    assert scan(b"") == []


def test_a_document_without_control_information_is_one_text_token() -> None:
    assert scan(b"plain text") == [text(b"plain text")]


def test_groups_and_text_interleave() -> None:
    assert scan(b"{a{b}c}") == [
        GROUP_START,
        text(b"a"),
        GROUP_START,
        text(b"b"),
        GROUP_END,
        text(b"c"),
        GROUP_END,
    ]


def test_tokenize_is_lazy() -> None:
    """A quarter-megabyte document must not become a list of tokens first."""
    stream = tokenize(b"{\\rtf1 x}")
    assert next(stream) == GROUP_START


def test_the_delimiter_space_is_consumed() -> None:
    """RTF 1.9.1: a space "serves only to delimit a control word and is ignored"."""
    assert scan(b"\\ansicpg1252 text") == [word("ansicpg", 1252), text(b"text")]


def test_only_one_delimiter_space_is_consumed() -> None:
    """RTF 1.9.1: "any characters following the single space delimiter, including any
    subsequent spaces, will appear as text"."""
    assert scan(b"\\par  x") == [word("par"), text(b" x")]


def test_a_delimiter_that_is_not_a_space_stays_in_the_stream() -> None:
    """RTF 1.9.1: such a character "terminates the control word and is not part of the
    control word"."""
    assert scan(b"\\pard{\\b x}") == [
        word("pard"),
        GROUP_START,
        word("b"),
        text(b"x"),
        GROUP_END,
    ]


def test_a_negative_parameter_keeps_its_sign() -> None:
    """``\\u-3891`` is how a producer writes U+F0CD, so the sign is content."""
    assert scan(b"\\u-3891") == [word("u", -3891)]


@pytest.mark.parametrize(
    ("raw", "param"),
    [(b"\\fromhtml", None), (b"\\fromhtml0", 0), (b"\\fromhtml1", 1)],
)
def test_an_absent_parameter_is_not_a_zero_parameter(
    raw: bytes, param: int | None
) -> None:
    """MS-OXRTFEX 2.2.3.1 recognizes ``\\fromhtml1`` and nothing else, so these three
    have to stay distinguishable."""
    assert scan(raw) == [word("fromhtml", param)]


def test_a_name_may_contain_uppercase_letters() -> None:
    """RTF 1.9.1: the letter sequence is "a through z and A through Z"."""
    assert scan(b"\\Uppercase\\lower") == [word("Uppercase"), word("lower")]


@pytest.mark.parametrize("char", ["{", "}", "\\", "~", "-", "_", "*", ":", "|", "5"])
def test_control_symbols(char: str) -> None:
    """RTF 1.9.1: "a backslash followed by a single, non-alphabetical character"."""
    assert scan(("\\" + char).encode("ascii")) == [symbol(char)]


def test_a_control_symbol_does_not_consume_a_following_space() -> None:
    """RTF 1.9.1: "control symbols do not have delimiters, i.e., a space following a
    control symbol is treated as text, not a delimiter"."""
    assert scan(b"\\~ x") == [symbol("~"), text(b" x")]


def test_a_name_longer_than_the_specification_allows_overflows_into_text() -> None:
    """RTF 1.9.1: "a control word's name cannot be longer than 32 letters"."""
    raw = b"\\" + b"a" * (MAX_CONTROL_WORD_LETTERS + 1)
    assert scan(raw) == [word("a" * MAX_CONTROL_WORD_LETTERS), text(b"a")]


def test_a_parameter_longer_than_the_specification_allows_overflows_into_text() -> None:
    """RTF 1.9.1: "up to 10 digits optionally preceded by a minus sign"."""
    raw = b"\\f" + b"1" * (MAX_PARAMETER_DIGITS + 1)
    assert scan(raw) == [word("f", int("1" * MAX_PARAMETER_DIGITS)), text(b"1")]


@pytest.mark.parametrize("raw", [b"\\'e4", b"\\'E4"])
def test_a_hex_escape_accepts_either_case(raw: bytes) -> None:
    assert scan(raw) == [octet(0xE4)]


@pytest.mark.parametrize("value", [0x00, 0x09, 0x20, 0x5C, 0x7F, 0x80, 0xFF])
def test_a_hex_escape_carries_both_its_byte_and_its_value(value: int) -> None:
    """The byte is what the emitter appends; the value is what a driver compares."""
    assert scan(b"\\'" + f"{value:02x}".encode("ascii")) == [octet(value)]


def test_consecutive_hex_escapes_stay_separate_and_in_order() -> None:
    """A double-byte character arrives as two escapes and has to decode as a pair.

    RTF 1.9.1 (East Asian RTF) allows a lead byte and its trailing byte to be escaped
    independently, so nothing may reorder or merge them here.
    """
    assert scan(b"\\'82\\'a0") == [octet(0x82), octet(0xA0)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\\'zz", [symbol("'"), text(b"zz")]),
        (b"\\'e", [symbol("'"), text(b"e")]),
        (b"\\'", [symbol("'")]),
    ],
)
def test_an_incomplete_hex_escape_becomes_an_ignored_control_symbol(
    raw: bytes, expected: list[Token]
) -> None:
    """``\\'`` without two digits produces no character, rather than an apostrophe the
    producer never wrote."""
    assert scan(raw) == expected


def test_bare_line_breaks_produce_no_token() -> None:
    """RTF 1.9.1: "CRLFs should be ignored by RTF readers"."""
    assert scan(b"a\r\nb") == [text(b"a"), text(b"b")]


def test_a_line_break_can_delimit_a_control_word() -> None:
    """RTF 1.9.1: CRLFs "can act as control word delimiters"."""
    assert scan(b"\\par\r\nx") == [word("par"), text(b"x")]


@pytest.mark.parametrize("raw", [b"\\\r", b"\\\n", b"\\\r\n"])
def test_a_backslash_before_a_line_break_is_a_paragraph_mark(raw: bytes) -> None:
    """RTF 1.9.1: CR or LF "is treated as a ``\\par`` control if the character is
    preceded by a backslash"."""
    assert scan(raw) == [word("par")]


def test_a_binary_payload_is_taken_verbatim() -> None:
    """RTF 1.9.1: N "is the number of bytes that follow", and they may be anything.

    Braces and backslashes inside the payload are data, which is the reason this is a
    scanner and not a grammar.
    """
    assert scan(b"\\bin5 {}\\ab") == [Token(TokenKind.BINARY, b"{}\\ab", param=5)]


def test_the_delimiter_space_is_not_part_of_a_binary_payload() -> None:
    """RTF 1.9.1 warns that spaces after the delimiter attach to the picture data."""
    assert scan(b"\\bin3    ") == [Token(TokenKind.BINARY, b"   ", param=3)]


def test_a_truncated_binary_payload_still_reports_its_declared_length() -> None:
    """The gap between ``param`` and ``len(data)`` is what the driver diagnoses."""
    assert scan(b"\\bin9 abc") == [Token(TokenKind.BINARY, b"abc", param=9)]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"\\bin", word("bin")),
        (b"\\bin0", word("bin", 0)),
        (b"\\bin-4", word("bin", -4)),
    ],
)
def test_bin_without_a_positive_length_is_an_ordinary_control_word(
    raw: bytes, expected: Token
) -> None:
    """Nothing follows it, so nothing may be swallowed."""
    assert scan(raw) == [expected]


def test_a_trailing_backslash_is_dropped() -> None:
    """There is no character left for it to escape."""
    assert scan(b"x\\") == [text(b"x")]


def test_an_unclosed_group_tokenizes_up_to_its_last_byte() -> None:
    assert scan(b"{\\rtf1 x") == [GROUP_START, word("rtf", 1), text(b"x")]


def test_a_stray_group_end_is_reported_rather_than_swallowed() -> None:
    """The driver decides what an unbalanced brace means; the scanner only reports
    it."""
    assert scan(b"a}b") == [text(b"a"), GROUP_END, text(b"b")]


@pytest.mark.parametrize(
    "raw",
    [
        b"{\\rtf1 x",
        b"}",
        b"{{{",
        b"\\",
        b"\\'",
        b"{\\bin99 short",
        b"\\bin-1{",
        b"\xff\xfe\x00",
        b"\\" + b"z" * 300,
        b"\\f" + b"9" * 40,
    ],
)
def test_malformed_input_terminates_and_yields_no_empty_text(raw: bytes) -> None:
    """Reaching the assertion at all is half the test: nothing here may raise.

    An empty ``TEXT`` token would be the signature of an off-by-one in the run
    slicing, and would give a driver a token that means nothing.
    """
    tokens = scan(raw)
    assert all(token.data for token in tokens if token.kind is TokenKind.TEXT)


def test_names_are_reported_the_way_the_character_tables_are_keyed() -> None:
    """A name carrying its backslash would silently never match a table entry."""
    tokens = scan(b"\\par\\tab\\emdash\\~\\_")
    assert [token.name for token in tokens] == ["par", "tab", "emdash", "~", "_"]
    assert all(
        token.name in BODY_CHARMAP.words or token.name in BODY_CHARMAP.symbols
        for token in tokens
    )


def rejoin(token: Token) -> bytes:
    """The RTF a token was scanned from, in canonical form.

    Canonical means every control word is followed by its delimiting space, since that
    space is consumed and cannot be recovered from the token itself.
    """
    if token.kind is TokenKind.TEXT:
        return token.data
    if token.kind is TokenKind.GROUP_START:
        return b"{"
    if token.kind is TokenKind.GROUP_END:
        return b"}"
    if token.kind is TokenKind.SYMBOL:
        return b"\\" + token.name.encode("latin-1")
    if token.kind is TokenKind.HEX:
        assert token.param is not None
        return b"\\'" + f"{token.param:02x}".encode("ascii")
    param = b"" if token.param is None else str(token.param).encode("ascii")
    if token.kind is TokenKind.BINARY:
        return b"\\bin" + param + b" " + token.data
    return b"\\" + token.name.encode("ascii") + param + b" "


def test_every_byte_of_a_document_is_accounted_for() -> None:
    """Rejoining the tokens reproduces the document exactly.

    The document is written in the canonical form :func:`rejoin` produces -- a space
    after every control word, no bare line breaks -- because those are precisely
    the bytes the scanner is allowed to discard. Anything else it dropped or
    duplicated shows up here as a mismatch.
    """
    document = (
        b"{\\rtf1 \\ansi \\ansicpg1252 \\fromhtml1 "
        b"{\\fonttbl {\\f0 \\fcharset0 Calibri;}}"
        b"{\\*\\htmltag84 <p>}r\\'e9sum\\'e9 \\{x\\}\\emdash \\bin4 \x00\x01{}"
        b"\\par }"
    )
    assert b"".join(rejoin(token) for token in tokenize(document)) == document
