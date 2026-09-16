"""Tests for code page resolution.

The point of most of these is that a transcription typo in a hand-written code page
table fails loudly here rather than silently mojibaking one language's mail in
production.
"""

import codecs

import pytest

from ottertf.codepages import (
    ANSI_CHARSET,
    CODEPAGE_TO_CODEC,
    DEFAULT_CHARSET,
    FCHARSET_TO_CODEPAGE,
    INVALID_CHARSET,
    SYMBOL_CHARSET,
    encoding_for_codepage,
)


@pytest.mark.parametrize("codec_name", sorted(set(CODEPAGE_TO_CODEC.values())))
def test_every_alias_names_a_real_codec(codec_name: str) -> None:
    assert codecs.lookup(codec_name)


@pytest.mark.parametrize(
    "codepage", sorted(cp for cp in FCHARSET_TO_CODEPAGE.values() if cp is not None)
)
def test_every_charset_codepage_resolves(codepage: int) -> None:
    """Catches a digit transposition such as 1461 for 1361."""
    encoding = encoding_for_codepage(codepage)
    assert encoding is not None, codepage
    assert codecs.lookup(encoding)


@pytest.mark.parametrize("codepage", sorted(CODEPAGE_TO_CODEC))
def test_every_alias_is_reachable_through_the_resolver(codepage: int) -> None:
    assert encoding_for_codepage(codepage) == CODEPAGE_TO_CODEC[codepage]


@pytest.mark.parametrize(
    ("codepage", "expected"),
    [
        (1252, "cp1252"),
        (1250, "cp1250"),
        (932, "cp932"),
        (936, "cp936"),
        (950, "cp950"),
        (949, "cp949"),
        (1361, "cp1361"),
        (874, "cp874"),
        (437, "cp437"),
        (850, "cp850"),
        (65001, "cp65001"),
        (20127, "ascii"),
        (28591, "iso8859_1"),
        (54936, "gb18030"),
    ],
)
def test_common_codepages_resolve_to_the_expected_codec(
    codepage: int, expected: str
) -> None:
    assert encoding_for_codepage(codepage) == expected


def test_zero_padded_fallback() -> None:
    """CPython names EBCDIC code pages with a fixed width: cp037, not cp37."""
    with pytest.raises(LookupError):
        codecs.lookup("cp37")
    assert encoding_for_codepage(37) == "cp037"


@pytest.mark.parametrize("codepage", [1200, 1201, 12000, 12001])
def test_utf16_and_utf32_are_refused(codepage: int) -> None:
    """These are not byte-oriented code pages; decoding RTF bytes with them is wrong."""
    assert encoding_for_codepage(codepage) is None


@pytest.mark.parametrize("codepage", [0, 9999, 123456, -1, -1252])
def test_unknown_codepages_return_none(codepage: int) -> None:
    assert encoding_for_codepage(codepage) is None


def test_utf8_resolves_and_round_trips() -> None:
    encoding = encoding_for_codepage(65001)
    assert encoding is not None
    assert "wörd".encode(encoding).decode(encoding) == "wörd"


class TestFcharsetTable:
    """Pins the ``\\fcharsetN`` table against RTF 1.9.1."""

    def test_default_like_charsets_defer_to_the_document(self) -> None:
        for charset in (ANSI_CHARSET, DEFAULT_CHARSET, SYMBOL_CHARSET, INVALID_CHARSET):
            assert charset in FCHARSET_TO_CODEPAGE
            assert FCHARSET_TO_CODEPAGE[charset] is None

    @pytest.mark.parametrize(
        ("charset", "codepage"),
        [
            (77, 10000),  # Mac Roman
            (128, 932),  # Shift JIS
            (129, 949),  # Hangul
            (130, 1361),  # Johab
            (134, 936),  # GB2312
            (136, 950),  # Big5
            (161, 1253),  # Greek
            (162, 1254),  # Turkish
            (163, 1258),  # Vietnamese
            (177, 1255),  # Hebrew
            (178, 1256),  # Arabic
            (179, 1256),  # Arabic Traditional
            (180, 1256),  # Arabic user
            (181, 1255),  # Hebrew user
            (186, 1257),  # Baltic
            (204, 1251),  # Russian
            (222, 874),  # Thai
            (238, 1250),  # Eastern European
            (254, 437),  # OEM United States
            (255, 850),  # OEM multilingual Latin 1
        ],
    )
    def test_snapshot(self, charset: int, codepage: int) -> None:
        """An accidental edit to the table has to show up in review."""
        assert FCHARSET_TO_CODEPAGE[charset] == codepage

    def test_table_has_no_undocumented_entries(self) -> None:
        expected = {
            0, 1, 2, 3, 77, 128, 129, 130, 134, 136, 161, 162, 163, 177, 178,
            179, 180, 181, 186, 204, 222, 238, 254, 255,
        }  # fmt: skip
        assert set(FCHARSET_TO_CODEPAGE) == expected

    @pytest.mark.parametrize("charset", [4, 182, 200, 256, -1])
    def test_charsets_the_spec_does_not_define_are_absent(self, charset: int) -> None:
        """Absence is how the driver tells "use the default" from "unknown"."""
        assert charset not in FCHARSET_TO_CODEPAGE


def test_tables_are_read_only() -> None:
    """A caller mutating these would corrupt every later call in the process."""
    with pytest.raises(TypeError):
        FCHARSET_TO_CODEPAGE[999] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        CODEPAGE_TO_CODEC[999] = "x"  # type: ignore[index]


@pytest.mark.parametrize(
    ("codepage", "raw", "expected"),
    [
        (1252, b"\xe4", "ä"),
        (1251, b"\xe0", "а"),
        (1250, b"\xe8", "č"),
        (28595, b"\xd0", "а"),
        (20866, b"\xc1", "а"),
        (932, b"\x82\xa0", "あ"),
        (936, b"\xc4\xe3", "你"),
    ],
)
def test_resolved_codecs_decode_as_expected(
    codepage: int, raw: bytes, expected: str
) -> None:
    """Spot check that the resolved codec is the right one, not merely a valid one."""
    encoding = encoding_for_codepage(codepage)
    assert encoding is not None
    assert raw.decode(encoding) == expected
