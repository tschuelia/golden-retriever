"""Tests for recognizing encapsulated content (MS-OXRTFEX 2.2.3.1).

Recognition decides whether a document is de-encapsulated at all, so both kinds of
mistake are expensive: classifying encapsulated HTML as native RTF turns into a
refusal, and the other direction turns RTF markup into "HTML". Every case here is
an inline byte literal, so the header being classified is visible in the test.
"""

from collections.abc import Iterator

import pytest

from golden_retriever.detect import (
    DEFAULT_HEADER_TOKEN_LIMIT,
    RTF_HEADING,
    detect_content_type,
    has_rtf_heading,
    is_encapsulated_html,
)
from golden_retriever.result import ContentType
from golden_retriever.tokenizer import Token, tokenize

ENCAPSULATED_HTML = (
    b"{\\rtf1\\ansi\\ansicpg1252\\fromhtml1\\deff0"
    b"{\\fonttbl{\\f0\\fswiss\\fcharset0 Arial;}}"
    b"{\\*\\htmltag84 <p>}text\\par}"
)
"""A header in the shape MS-OXRTFEX 2.1.3.2 describes: the marker after ``\\rtf1`` and
before ``\\fonttbl``."""

ENCAPSULATED_TEXT = (
    b"{\\rtf1\\ansi\\ansicpg1252\\fromtext\\deff0"
    b"{\\fonttbl{\\f0\\fmodern\\fcharset0 Courier New;}}"
    b"plain text\\par}"
)

NATIVE_RTF = (
    b"{\\rtf1\\ANSI\\ansicpg1252\\deff0\\deflang1033"
    b"{\\fonttbl{\\f0\\fswiss\\fcharset0 Arial;}}\r\n"
    b"{\\*\\generator Riched20 5.50.99.2050;}"
    b"\\viewkind4\\uc1\\pard\\f0\\fs20 This is a test email.\\par\r\n}"
)
"""The document MS-OXRTFEX 3.2 walks through, which it concludes is not encapsulated
"because the FROMHTML and FROMTEXT control words are not found in the RTF header"."""

NINE_HEADER_TOKENS = (
    b"{\\rtf1\\ansi\\ansicpg1252\\deff0\\deflang1033\\viewkind4\\uc1\\pard"
)
"""A begin group mark and eight control words, so the next token is the tenth."""


def test_the_marker_is_recognized_in_a_realistic_header() -> None:
    assert detect_content_type(ENCAPSULATED_HTML) is ContentType.HTML
    assert detect_content_type(ENCAPSULATED_TEXT) is ContentType.TEXT


def test_a_document_without_a_marker_is_native_rtf() -> None:
    assert detect_content_type(NATIVE_RTF) is ContentType.NATIVE_RTF


@pytest.mark.parametrize(
    ("marker", "expected"),
    [
        (b"\\fromhtml1", ContentType.HTML),
        (b"\\fromhtml", ContentType.NATIVE_RTF),
        (b"\\fromhtml0", ContentType.NATIVE_RTF),
        (b"\\fromhtml2", ContentType.NATIVE_RTF),
        (b"\\fromtext", ContentType.TEXT),
        (b"\\fromtext0", ContentType.NATIVE_RTF),
        (b"\\fromtext1", ContentType.NATIVE_RTF),
    ],
)
def test_only_the_exact_marker_forms_count(
    marker: bytes, expected: ContentType
) -> None:
    """Only ``\\fromhtml1`` is FROMHTML: "any other form, such as \\fromhtml or
    \\fromhtml0, will not be considered encapsulated" (MS-OXRTFEX 2.1.3.1.2).

    FROMTEXT is the mirror image: its ABNF in 2.1.3.1.1 is ``\\fromtext`` with no
    parameter at all, and RTF 1.9.1 gives a zero parameter the meaning "off".
    """
    assert detect_content_type(b"{\\rtf1\\ansi" + marker + b" x}") is expected


@pytest.mark.parametrize("marker", [b"\\FROMHTML1", b"\\FromHtml1", b"\\Fromtext"])
def test_a_marker_is_case_sensitive(marker: bytes) -> None:
    """The ABNF fixes the bytes: ``%x5C.66.72.6F.6D.68.74.6D.6C`` is lowercase, and RTF
    1.9.1 control words differing in case are different control words."""
    assert detect_content_type(b"{\\rtf1" + marker + b" x}") is ContentType.NATIVE_RTF


def test_inspection_stops_at_the_first_marker() -> None:
    """MS-OXRTFEX 2.2.3.1 concludes and stops "further inspection", so whichever marker
    comes first decides -- a document carrying both is not reclassified."""
    assert detect_content_type(b"{\\rtf1\\fromtext\\fromhtml1 x}") is ContentType.TEXT
    assert detect_content_type(b"{\\rtf1\\fromhtml1\\fromtext x}") is ContentType.HTML


def test_the_marker_may_be_the_last_token_of_the_window() -> None:
    document = NINE_HEADER_TOKENS + b"\\fromhtml1"
    assert len(list(tokenize(document))) == DEFAULT_HEADER_TOKEN_LIMIT
    assert detect_content_type(document) is ContentType.HTML


def test_a_marker_past_the_window_is_not_seen_unless_the_window_is_widened() -> None:
    """The limit is MS-OXRTFEX 2.2.3.1's "no more than the first 10 RTF tokens"; a
    caller who knows better may look further."""
    document = NINE_HEADER_TOKENS + b"\\f0\\fromhtml1"
    assert len(list(tokenize(document))) == DEFAULT_HEADER_TOKEN_LIMIT + 1
    assert detect_content_type(document) is ContentType.NATIVE_RTF
    assert detect_content_type(document, header_token_limit=20) is ContentType.HTML


def test_begin_group_marks_spend_the_window() -> None:
    """2.2.3.1 counts "begin group marks and control words", so braces are tokens too."""
    assert (
        detect_content_type(b"{\\rtf1" + b"{" * 7 + b"\\fromhtml1") is ContentType.HTML
    )
    assert (
        detect_content_type(b"{\\rtf1" + b"{" * 8 + b"\\fromhtml1")
        is ContentType.NATIVE_RTF
    )


def test_a_zero_token_window_inspects_nothing() -> None:
    assert (
        detect_content_type(ENCAPSULATED_HTML, header_token_limit=0)
        is ContentType.NATIVE_RTF
    )


@pytest.mark.parametrize(
    "document",
    [
        b"{\\rtf1}\\fromhtml1",
        b"{\\rtf1 x\\fromhtml1",
        b"{\\rtf1\\*\\fromhtml1",
        b"{\\rtf1\\'e4\\fromhtml1",
        b"{\\rtf1\\bin2 ab\\fromhtml1",
    ],
    ids=["group-end", "text", "control-symbol", "hex-escape", "binary-payload"],
)
def test_a_token_that_is_neither_a_group_start_nor_a_control_word_ends_inspection(
    document: bytes,
) -> None:
    """MS-OXRTFEX 2.2.3.1: pure RTF if "there are any RTF tokens besides the begin group
    mark "{" or a control word within the first 10 tokens"."""
    assert detect_content_type(document) is ContentType.NATIVE_RTF


def test_indentation_in_a_wrapped_header_does_not_end_inspection() -> None:
    """The one exception to the rule above, because CR and LF are already insignificant.

    A header written across several lines leaves its indentation behind as a text token,
    and that is formatting rather than content.
    """
    document = b"{\\rtf1\\ansi\\ansicpg1252\r\n  \\fromhtml1\r\n{\\fonttbl}}"
    assert detect_content_type(document) is ContentType.HTML


def test_the_font_table_control_word_is_not_a_cutoff() -> None:
    """A marker after ``\\fonttbl`` violates the placement rule in MS-OXRTFEX 2.1.3.1.2,
    but that rule binds writers; a reader that can still see the marker honors it.

    Contrived on purpose: a real font table ends inspection by itself, at its first font
    name or its closing brace.
    """
    assert detect_content_type(b"{\\rtf1{\\fonttbl\\fromhtml1") is ContentType.HTML


def test_the_heading_is_not_required_to_recognize_encapsulation() -> None:
    """MS-OXRTFEX A<13>: implementations "ignore the absence of the \\rtf1 keyword at
    the beginning of the RTF encoded text and try to de-encapsulate the text anyway".

    The heading is reported separately so a caller can record a diagnostic for it.
    """
    headless = b"{\\ansi\\ansicpg1252\\fromhtml1 x}"
    assert not has_rtf_heading(headless)
    assert detect_content_type(headless) is ContentType.HTML


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (b"{\\rtf1\\ansi}", True),
        (b"{\\rtf1", True),
        (b"{\\rtf2", False),
        (b"{\\rtf", False),
        (b"{\\RTF1", False),
        (b" {\\rtf1", False),
        (b"", False),
    ],
)
def test_has_rtf_heading(raw: bytes, expected: bool) -> None:
    """MS-OXRTFEX 2.2.3.1: a valid heading means the document "starts with the character
    sequence "{\\rtf1""."""
    assert has_rtf_heading(raw) is expected
    assert RTF_HEADING == b"{\\rtf1"


def test_is_encapsulated_html_is_true_only_for_html() -> None:
    assert is_encapsulated_html(ENCAPSULATED_HTML)
    assert not is_encapsulated_html(ENCAPSULATED_TEXT)
    assert not is_encapsulated_html(NATIVE_RTF)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"{",
        b"}",
        b"\\",
        b"\\'",
        b"{\\rtf1",
        b"{\\rtf1\\fromhtml1",
        b"{\\rtf1\\bin99 short",
        b"\xff\xfe\x00",
        b"\\" + b"z" * 300,
        b"{\\rtf1\\ansi\r\n\r\n\r\n",
    ],
)
def test_malformed_input_is_classified_and_never_raises(raw: bytes) -> None:
    """Truncated and nonsensical documents get an answer, not an exception."""
    assert isinstance(detect_content_type(raw), ContentType)


def test_a_str_argument_is_a_type_error() -> None:
    """The scanner works on bytes; passing text is a caller bug, not malformed RTF."""
    with pytest.raises(TypeError):
        detect_content_type("{\\rtf1\\fromhtml1")  # type: ignore[arg-type]


def test_inspection_reads_the_header_and_not_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recognition is a guard, so its cost must not scale with document size."""
    pulled = 0

    def counting_tokenize(data: bytes) -> Iterator[Token]:
        nonlocal pulled
        for token in tokenize(data):
            pulled += 1
            yield token

    monkeypatch.setattr("golden_retriever.detect.tokenize", counting_tokenize)
    document = NINE_HEADER_TOKENS + b"\\f0\\fs20 " + b"body " * 20_000 + b"}"
    assert detect_content_type(document) is ContentType.NATIVE_RTF
    assert pulled <= DEFAULT_HEADER_TOKEN_LIMIT + 1
