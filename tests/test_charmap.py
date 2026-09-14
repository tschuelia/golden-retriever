"""Tests pinning the two character tables against their specifications.

The tables are hand-transcribed data, and a wrong row does not fail loudly -- it puts
one wrong character into otherwise perfect output. So every row of MS-OXRTFEX
2.1.3.1.4.2 is asserted individually, and both key sets are pinned so an added or
removed row has to be justified in review.
"""

import pytest

from golden_retriever.charmap import BODY_CHARMAP, HTMLTAG_CHARMAP, CharMap

CHARMAPS = [BODY_CHARMAP, HTMLTAG_CHARMAP]

# MS-OXRTFEX 2.1.3.1.4.2, the CONTENT HTML fragment table, one entry per row that
# stands for a character. The rows for \'HH, \u[-]NNNNN and \uc are the
# tokenizer's and the driver's job, not a table lookup.
CONTENT_WORDS = [
    ("par", "\r\n"),
    ("tab", "\t"),
    ("lquote", "\u2018"),
    ("rquote", "\u2019"),
    ("ldblquote", "\u201c"),
    ("rdblquote", "\u201d"),
    ("bullet", "\u2022"),
    ("endash", "\u2013"),
    ("emdash", "\u2014"),
]

CONTENT_SYMBOLS = [
    ("{", "{"),
    ("}", "}"),
    ("\\", "\\"),
    ("~", "\u00a0"),
    ("_", "\u00ad"),
]


def test_the_content_table_is_transcribed_in_full() -> None:
    """All 14 character-producing rows of MS-OXRTFEX 2.1.3.1.4.2 are present."""
    assert len(CONTENT_WORDS) + len(CONTENT_SYMBOLS) == 14


@pytest.mark.parametrize(("name", "expected"), CONTENT_WORDS)
def test_htmltag_control_words(name: str, expected: str) -> None:
    assert HTMLTAG_CHARMAP.words[name] == expected


@pytest.mark.parametrize(("char", "expected"), CONTENT_SYMBOLS)
def test_htmltag_control_symbols(char: str, expected: str) -> None:
    assert HTMLTAG_CHARMAP.symbols[char] == expected


def test_underscore_differs_between_the_two_tables() -> None:
    """The one documented conflict, and the reason there are two tables.

    MS-OXRTFEX 2.1.3.1.4.2 gives ``\\_`` as ``&shy;``. RTF 1.9.1 assigns U+00AD to
    ``\\-`` instead, and gives ``\\_`` the non-breaking hyphen.
    """
    assert HTMLTAG_CHARMAP.symbols["_"] == "\u00ad"
    assert BODY_CHARMAP.symbols["_"] == "\u2011"


@pytest.mark.parametrize("charmap", CHARMAPS)
def test_optional_hyphen_is_the_soft_hyphen_everywhere(charmap: CharMap) -> None:
    """RTF 1.9.1: ``\\-`` is the optional hyphen, in both destinations."""
    assert charmap.symbols["-"] == "\u00ad"


@pytest.mark.parametrize(("name", "expected"), CONTENT_WORDS)
def test_the_body_table_agrees_on_every_shared_control_word(
    name: str, expected: str
) -> None:
    assert BODY_CHARMAP.words[name] == expected


def test_line_becomes_crlf_in_body_text_only() -> None:
    """MS-OXRTFEX 2.2.3.2 lists ``\\line``; 2.1.3.1.4.2 does not."""
    assert BODY_CHARMAP.words["line"] == "\r\n"
    assert "line" not in HTMLTAG_CHARMAP.words


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("emspace", "\u2003"),
        ("enspace", "\u2002"),
        ("qmspace", "\u2005"),
        ("ltrmark", "\u200e"),
        ("rtlmark", "\u200f"),
        ("zwj", "\u200d"),
        ("zwnj", "\u200c"),
    ],
)
def test_body_only_special_characters(name: str, expected: str) -> None:
    """RTF 1.9.1 Special Characters that MS-OXRTFEX 2.1.3.1.4.2 omits."""
    assert BODY_CHARMAP.words[name] == expected
    assert name not in HTMLTAG_CHARMAP.words


@pytest.mark.parametrize("charmap", CHARMAPS)
@pytest.mark.parametrize(
    "name",
    [
        # RTF 1.9.1 special characters that name no character. Producing one
        # would insert text the specification never asked for.
        "zwbo",
        "zwnbo",
        # Breaks other than \par and \line. MS-OXRTFEX 2.2.3.2 converts only
        # those two, and ignores every other control word.
        "sect",
        "page",
        "column",
        "softline",
        "softpage",
        "softcol",
        "cell",
        "row",
        "nestcell",
        "nestrow",
        # Header and field words that must never reach the output.
        "fonttbl",
        "colortbl",
        "htmlrtf",
        "htmltag",
        "fldinst",
    ],
)
def test_ignored_control_words_are_absent(charmap: CharMap, name: str) -> None:
    assert name not in charmap.words


@pytest.mark.parametrize("charmap", CHARMAPS)
@pytest.mark.parametrize("char", [":", "|", "*", "'", "u"])
def test_ignored_control_symbols_are_absent(charmap: CharMap, char: str) -> None:
    """``\\:`` and ``\\|`` name no character; ``\\*``, ``\\'`` and ``\\u`` are the
    driver's and the tokenizer's."""
    assert char not in charmap.symbols


def test_htmltag_key_sets_are_pinned() -> None:
    """A row added to or removed from the HTMLTAG table must show up here."""
    assert sorted(HTMLTAG_CHARMAP.words) == sorted(name for name, _ in CONTENT_WORDS)
    assert sorted(HTMLTAG_CHARMAP.symbols) == sorted(
        # The CONTENT table plus \-, the one documented addition.
        [char for char, _ in CONTENT_SYMBOLS] + ["-"]
    )


def test_body_key_sets_are_pinned() -> None:
    """A row added to or removed from the body table must show up here."""
    assert sorted(BODY_CHARMAP.words) == [
        "bullet",
        "emdash",
        "emspace",
        "endash",
        "enspace",
        "ldblquote",
        "line",
        "lquote",
        "ltrmark",
        "par",
        "qmspace",
        "rdblquote",
        "rquote",
        "rtlmark",
        "tab",
        "zwj",
        "zwnj",
    ]
    assert sorted(BODY_CHARMAP.symbols) == ["-", "\\", "_", "{", "}", "~"]


@pytest.mark.parametrize("charmap", CHARMAPS)
def test_keys_carry_no_leading_backslash(charmap: CharMap) -> None:
    """The tokenizer reports names and symbol characters without the backslash.

    A key spelled ``"\\par"`` would silently never match.
    """
    assert not any(name.startswith("\\") for name in charmap.words)
    assert all(len(char) == 1 for char in charmap.symbols)


@pytest.mark.parametrize("charmap", CHARMAPS)
def test_every_value_is_a_non_empty_string(charmap: CharMap) -> None:
    """An empty value would be indistinguishable from an ignored control word, but would
    take a different code path in the driver."""
    for mapping in (charmap.words, charmap.symbols):
        assert all(isinstance(value, str) and value for value in mapping.values())


@pytest.mark.parametrize("charmap", CHARMAPS)
def test_the_tables_are_read_only(charmap: CharMap) -> None:
    """A caller cannot reach in and change what a control word decodes to."""
    with pytest.raises(TypeError):
        charmap.words["par"] = "x"  # type: ignore[index]
    with pytest.raises(TypeError):
        charmap.symbols["~"] = "x"  # type: ignore[index]


def test_charmap_is_frozen() -> None:
    with pytest.raises(AttributeError):
        BODY_CHARMAP.words = HTMLTAG_CHARMAP.words  # type: ignore[misc]
