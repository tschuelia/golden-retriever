"""Tests for the plain-text de-encapsulation path (MS-OXRTFEX 2.2.3.3).

Every case here is a whole document, because that is the only way to test a driver: the
RTF in each test *is* the documentation of what is being asserted. The mechanisms
exercised -- the group stack, HTMLRTF suppression, destination skipping, the character
tables and the ``\\uN``/``\\ucN`` skip count -- are shared with the HTML path, so this
file carries the bulk of them and the HTML tests cover only what HTMLTAG adds.
"""

import logging

import pytest

from golden_retriever.deencapsulator import deencapsulate
from golden_retriever.emitter import REPLACEMENT_CHARACTER
from golden_retriever.exceptions import (
    MalformedRtfError,
    MissingFontTableError,
    NotEncapsulatedRtfError,
    UnsupportedCodePageError,
)
from golden_retriever.result import ContentType, DeEncapsulationResult, DiagnosticCode

FFFD = REPLACEMENT_CHARACTER

FONT_TABLE = (
    b"{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}{\\f1\\fnil\\fcharset128 MS Mincho;}}"
)
"""Font 0 in the document's code page, font 1 in cp932, per RTF 1.9.1's charsets."""

HEADER = b"{\\rtf1\\ansi\\ansicpg1252\\fromtext\\deff0" + FONT_TABLE
"""A header a producer could have written, minus nothing that matters."""


def document(body: bytes) -> bytes:
    """``body`` inside a minimal well-formed FROMTEXT document."""
    return HEADER + body + b"}"


def run(body: bytes, *, strict: bool = False) -> DeEncapsulationResult:
    """De-encapsulate ``body``, asserting the result is routed as plain text."""
    result = deencapsulate(document(body), strict=strict)
    assert result.content_type is ContentType.TEXT
    assert result.html is None
    assert result.text is not None
    return result


def text(body: bytes) -> str:
    """The plain text ``body`` de-encapsulates to."""
    result = run(body)
    assert result.text is not None
    return result.text


def codes(result: DeEncapsulationResult) -> list[str]:
    return [diagnostic.code for diagnostic in result.diagnostics]


def test_a_clean_document_produces_text_and_nothing_else() -> None:
    result = run(b"\\pard\\f0 Hello.\\par")
    assert result.text == "Hello.\r\n"
    assert result.diagnostics == ()
    assert result.document_codepage == 1252
    assert result.document_encoding == "cp1252"
    assert result.declared_html_charset is None
    assert set(result.fonts) == {0, 1}
    assert result.body == result.text


def test_native_rtf_is_refused_rather_than_guessed_at() -> None:
    """MS-OXRTFEX 2.2.3.1 recognizes encapsulated content by its header marker; without
    one there is nothing encapsulated to extract."""
    with pytest.raises(NotEncapsulatedRtfError):
        deencapsulate(b"{\\rtf1\\ansi\\deff0 ordinary RTF}")


def test_text_input_is_a_programming_error_rather_than_a_document_problem() -> None:
    with pytest.raises(TypeError, match="bytes"):
        deencapsulate("{\\rtf1\\fromtext x}")  # type: ignore[arg-type]


def test_a_fallback_code_page_with_no_decoder_is_rejected_up_front() -> None:
    """A wrong argument value, not a problem with the document: raised whatever the
    document says, so the failure does not depend on the input."""
    with pytest.raises(ValueError, match="99999"):
        deencapsulate(document(b"x"), fallback_codepage=99999)


# --- The character tables (MS-OXRTFEX 2.2.3.3, RTF 1.9.1 Special Characters) ---


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"a\\par b", "a\r\nb"),
        (b"a\\line b", "a\r\nb"),
        (b"a\\tab b", "a\tb"),
        (b"a\\emdash b", "a—b"),
        (b"a\\bullet b", "a•b"),
        (b"a\\lquote b\\rquote ", "a‘b’"),
        (b"a\\ldblquote b\\rdblquote ", "a“b”"),
        (b"a\\enspace b", "a\u2002b"),
        (b"a\\zwnj b", "a\u200cb"),
    ],
    ids=lambda value: value.decode() if isinstance(value, bytes) else "",
)
def test_a_control_word_becomes_the_character_it_stands_for(
    body: bytes, expected: str
) -> None:
    """MS-OXRTFEX 2.2.3.3: "translate it to its textual equivalent"."""
    assert text(body) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (b"\\{x\\}", "{x}"),
        (b"a\\\\b", "a\\b"),
        (b"a\\~b", "a\u00a0b"),
        (b"a\\-b", "a\u00adb"),
        (b"a\\_b", "a\u2011b"),
    ],
    ids=["braces", "backslash", "nbsp", "optional-hyphen", "nonbreaking-hyphen"],
)
def test_a_control_symbol_becomes_the_character_it_stands_for(
    body: bytes, expected: str
) -> None:
    """``\\_`` is U+2011 here, per RTF 1.9.1; inside an HTMLTAG destination MS-OXRTFEX
    2.1.3.1.4.2 makes it U+00AD instead."""
    assert text(body) == expected


@pytest.mark.parametrize(
    "body",
    [
        b"a\\b\\i0 b",
        b"a\\fs20 b",
        b"a\\pard\\plain b",
        b"a\\page b",
        b"a\\zwbo b",
        b"a\\:b",
        b"a\\|b",
    ],
)
def test_a_control_token_standing_for_no_character_is_ignored(body: bytes) -> None:
    """MS-OXRTFEX 2.2.3.3: "Ignore any RTF formatting control words that do not have a
    textual representation"."""
    assert text(body) == "ab"


def test_a_hex_escape_is_decoded_in_the_documents_code_page() -> None:
    assert text(b"r\\'e9sum\\'e9") == "résumé"


def test_a_hex_escape_is_decoded_in_the_fonts_code_page() -> None:
    """RTF 1.9.1 (East Asian RTF): a lead byte and its trailing byte become one
    character, so the pair has to reach one decoder together."""
    assert text(b"{\\f1\\'82\\'a0\\'82\\'a2}") == "あい"


def test_a_raw_byte_and_an_escaped_byte_pair_up() -> None:
    """The same rule, with the lead byte escaped and the trailing byte raw."""
    assert text(b"{\\f1\\'82\xa0}") == "あ"


# --- \uN and \ucN (RTF 1.9.1, Unicode RTF) ---


def test_the_ansi_representation_after_a_unicode_escape_is_skipped() -> None:
    """The plan's shape, verbatim: ``\\uc2`` and a two-character fallback."""
    assert text(b"\\uc2{\\u482??}") == "Ǣ"


def test_a_zero_skip_count_keeps_the_following_text() -> None:
    """``\\uc0`` means the producer wrote no ANSI representation at all."""
    assert text(b"\\uc0\\u482 ab") == "Ǣab"


def test_the_keyword_terminating_space_is_not_counted() -> None:
    """RTF 1.9.1: "a keyword-terminating space may be present (before the ANSI
    characters) that is not counted in the characters to skip"."""
    assert text(b"\\uc1\\u482 ?tail") == "Ǣtail"


def test_the_skip_count_is_inherited_and_restored_with_the_group() -> None:
    """RTF 1.9.1: the values "are scoped like character properties", and "when leaving
    an RTF group that specified a ``\\ucN`` value, the reader must revert to the
    previous value"."""
    assert text(b"\\uc1{\\uc3\\u482 xxxA}\\u482 yB") == "ǢAǢB"


def test_a_group_boundary_ends_skippable_data() -> None:
    """RTF 1.9.1: "If an RTF scope delimiter character (that is, an opening or closing
    brace) is encountered while scanning skippable data, the skippable data is
    considered to end before the delimiter"."""
    assert text(b"\\uc3{\\u482 x}kept") == "Ǣkept"
    assert text(b"\\uc3\\u482 x{kept}") == "Ǣkept"


@pytest.mark.parametrize(
    "body",
    [
        b"\\uc2\\u482 \\'e6\\'e7tail",
        b"\\uc2\\u482 \\bullet\\endash tail",
        b"\\uc2\\u482 \\{\\}tail",
        b"\\uc2\\u482 \\bin2 xx?tail",
        b"\\uc2\\u482 x\\bullet tail",
    ],
    ids=["hex", "words", "symbols", "binary", "mixed"],
)
def test_any_token_of_ansi_representation_counts_as_one_character(body: bytes) -> None:
    """RTF 1.9.1: "Any RTF control word or symbol is considered a single character for
    the purposes of counting skippable characters", and "a ``\\binN`` keyword, its
    argument, and the binary data that follows are considered one character"."""
    assert text(body) == "Ǣtail"


def test_a_unicode_escape_is_not_consumed_by_the_skip_before_it() -> None:
    """A deviation, and the reason for it: skippable data is an *ANSI* representation,
    which a ``\\uN`` never is.

    Counting it would delete a character that has no other spelling in the document.
    """
    assert text(b"\\uc1\\u482\\u483") == "Ǣǣ"


def test_a_negative_parameter_is_the_signed_form_of_the_same_character() -> None:
    """RTF 1.9.1: "Unicode values greater than 32767 are expressed as negative numbers.

    For example, the character code U+F020 is given by \\u-4064."
    """
    assert text(b"\\uc0\\u-3891") == "\uf0cd"
    assert text(b"\\uc0\\u61645") == "\uf0cd"


def test_a_surrogate_pair_becomes_one_character() -> None:
    """RTF has no other way to write a character outside the basic multilingual
    plane."""
    assert text(b"\\uc0\\u-10179\\u-8704") == "\U0001f600"


def test_a_surrogate_pair_written_with_ansi_representations_becomes_one_character() -> (
    None
):
    """The shape a producer actually writes: each half carries its own fallback."""
    assert text(b"\\uc1\\u-10179?\\u-8704?") == "\U0001f600"


def test_a_surrogate_with_no_partner_is_replaced_and_stays_encodable() -> None:
    """The output is always encodable as UTF-8, which a lone surrogate would break."""
    result = run(b"\\uc0\\u-10179 tail")
    assert result.text == FFFD + "tail"
    assert result.text.encode("utf-8")
    assert codes(result) == [DiagnosticCode.UNPAIRED_SURROGATE]


@pytest.mark.parametrize("body", [b"\\uc-1\\u482 x", b"\\uc\\u482 x"])
def test_a_skip_count_naming_no_number_leaves_the_previous_one(body: bytes) -> None:
    """Neither is legal RTF; keeping the last good value is the reading that does not
    lose text."""
    assert text(body) == "Ǣ"


def test_a_unicode_escape_with_no_parameter_produces_nothing() -> None:
    assert text(b"a\\u b") == "ab"


# --- HTMLRTF suppression (MS-OXRTFEX 2.1.3.1.3) ---


@pytest.mark.parametrize(
    "body",
    [
        b"\\htmlrtf1 hidden\\htmlrtf0 shown",
        b"\\htmlrtf hidden\\htmlrtf0 shown",
    ],
    ids=["with-parameter", "without-parameter"],
)
def test_suppressed_text_is_not_copied(body: bytes) -> None:
    """MS-OXRTFEX 2.1.3.1.3: while the state is enabled a reader "MUST NOT copy any
    subsequent text and control words in the RTF content until the state is disabled",
    and ``\\htmlrtf`` and ``\\htmlrtf1`` "both represent enabling"."""
    assert text(body) == "shown"


def test_suppression_covers_every_kind_of_content() -> None:
    assert text(b"\\htmlrtf1 t\\'e9\\bullet\\u482 ?\\{\\par\\htmlrtf0 shown") == "shown"


def test_suppression_transfers_into_a_group_and_is_restored_on_exit() -> None:
    """MS-OXRTFEX 2.1.3.1.3: the state "MUST transfer when entering groups and be
    restored when exiting groups"."""
    assert text(b"{\\htmlrtf1 a{b}}c") == "c"
    assert text(b"{\\htmlrtf1 a{\\htmlrtf0 b}c}d") == "bd"


def test_the_current_font_is_tracked_while_suppressed() -> None:
    """MS-OXRTFEX 2.2.3.2 states the exception: a reader "SHOULD track the current font
    even when the corresponding \\fN control word is inside of a fragment that is
    disabled with an HTMLRTF control word"."""
    assert text(b"\\htmlrtf1\\f1 hidden\\htmlrtf0\\'82\\'a0") == "あ"


def test_the_skip_count_is_tracked_while_suppressed() -> None:
    """The same treatment, for the same reason: ``\\ucN`` copies nothing, and losing it
    eats the text after the next ``\\uN``."""
    assert text(b"\\htmlrtf1\\uc0 hidden\\htmlrtf0\\u482 tail") == "Ǣtail"


def test_the_font_table_is_read_while_suppressed() -> None:
    """A suppressed font table would leave every text run decoded in the document's code
    page instead."""
    body = b"{\\f1\\'82\\'a0}"
    suppressed = b"{\\rtf1\\ansi\\fromtext\\htmlrtf1" + FONT_TABLE + b"\\htmlrtf0"
    result = deencapsulate(suppressed + body + b"}")
    assert result.text == "あ"
    assert result.diagnostics == ()


# --- Destinations (MS-OXRTFEX 2.2.3.2) ---


@pytest.mark.parametrize(
    "body",
    [
        b"{\\colortbl;\\red0\\green0\\blue0;}",
        b"{\\stylesheet{\\s0 Normal;}}",
        b"{\\info{\\title Secret}{\\author Nobody}}",
        b"{\\pict\\pngblip 89504e470d0a1a0a}",
        b"{\\listtable{\\list\\listtemplateid1}}",
        b"{\\*\\generator Something 1.0;}",
        b"{\\*\\themedata 04a0}",
        b"{\\*\\latentstyles\\lsdstimax267}",
    ],
    ids=[
        "colortbl",
        "stylesheet",
        "info",
        "pict",
        "listtable",
        "generator",
        "themedata",
        "latentstyles",
    ],
)
def test_a_group_producing_no_visible_text_emits_nothing(body: bytes) -> None:
    """MS-OXRTFEX 2.2.3.2: "Ignore and skip any standard RTF destination groups that do
    not produce visible text (such as \\colortbl groups)", and "Ignore any ignorable
    destination groups (that is, groups that start with "\\*")"."""
    assert text(b"a" + body + b"b") == "ab"


def test_a_skipped_destination_takes_its_nested_groups_with_it() -> None:
    assert text(b"a{\\info{\\title T{\\*\\x y}}}b") == "ab"


def test_a_skipped_destination_does_not_lose_the_state_around_it() -> None:
    """The group's own frame is what the skip lives in, so the document continues in the
    font and suppression state it had."""
    assert text(b"{\\f1{\\info{\\title T}}\\'82\\'a0}") == "あ"


def test_an_ignorable_group_is_skipped_whatever_follows_the_star() -> None:
    """The ``\\*`` rule is about the group, not about the destination it names, so it
    applies even where no destination control word follows."""
    assert text(b"a{\\* plain text}b") == "ab"
    assert text(b"a{\\*\\'e9}b") == "ab"
    assert text(b"a{\\*\\{}b") == "ab"
    assert text(b"a{\\*}b") == "ab"


def test_a_group_starting_with_content_declares_no_destination() -> None:
    """Only a control word can name a destination, so a group whose first token is text,
    an escape or a control symbol is ordinary content."""
    assert text(b"a{b}c") == "abc"
    assert text(b"a{\\'e9}b") == "aéb"
    assert text(b"a{\\{}b") == "a{b"


def test_a_tag_destination_in_a_plain_text_document_is_content() -> None:
    """MS-OXRTFEX 2.2.3.3 describes no HTMLTAG handling, so there is nothing to switch
    on: a ``\\fromtext`` document that carries one gets the same reader the HTML path
    does, and 2.1.3.1.4.2's CONTENT is a text fragment either way.

    Its ``HTMLTagParameter``, ``84`` here, is part of the control word and never reaches
    the output.
    """
    assert text(b"a{\\*\\htmltag84 <br>}b") == "a<br>b"


def test_a_field_keeps_its_visible_result() -> None:
    """``\\fldrslt`` is ordinary body content.

    Its instruction half is ``{\\*\\fldinst ...}``, which the ``\\*`` rule skips -- so
    nothing has to name ``\\field`` to get this right.
    """
    body = b'{\\field{\\*\\fldinst{HYPERLINK "http://example.com"}}{\\fldrslt link}}'
    assert text(body) == "link"


def test_a_skipped_destination_is_logged_rather_than_diagnosed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Skipping ``{\\colortbl...}`` is what a correct document expects, so it is not a
    problem to report.

    It is also the one action that drops content silently, so every skip is traceable at
    debug level.
    """
    with caplog.at_level(logging.DEBUG, logger="golden_retriever.deencapsulator"):
        result = run(b"{\\colortbl;}{\\*\\generator X;}")
    assert result.diagnostics == ()
    assert [record.getMessage() for record in caplog.records] == [
        "skipping the colortbl destination group",
        "skipping the generator destination group",
    ]


def test_a_destination_word_after_the_first_token_declares_nothing() -> None:
    """RTF 1.9.1 requires a destination control word to be the first item in its group,
    so a later ``\\colortbl`` is an ordinary ignored control word."""
    assert text(b"a\\colortbl b") == "ab"


# --- Fonts and the document code page ---


def test_text_claimed_by_no_font_uses_the_default_font() -> None:
    """``\\deffN`` is "the default font", which is what applies before any ``\\fN``."""
    document_bytes = (
        b"{\\rtf1\\ansi\\ansicpg1252\\fromtext\\deff1" + FONT_TABLE + b"\\'82\\'a0}"
    )
    result = deencapsulate(document_bytes)
    assert result.text == "あ"
    assert result.diagnostics == ()


def test_text_claimed_by_no_font_and_no_default_uses_the_document_code_page() -> None:
    document_bytes = b"{\\rtf1\\ansi\\ansicpg1250\\fromtext" + FONT_TABLE + b"\\'9c}"
    result = deencapsulate(document_bytes)
    assert result.text == "ś"
    assert result.document_encoding == "cp1250"


def test_a_font_word_with_no_number_changes_nothing() -> None:
    """``\\f`` without a parameter is not legal RTF; reverting to the default font on
    one would mojibake the run it appears in."""
    assert text(b"{\\f1\\f\\'82\\'a0}") == "あ"


def test_the_first_default_font_declaration_wins() -> None:
    """``\\deffN`` is a header property like ``\\ansicpgN``, and a bare ``\\deff`` names
    no font at all."""
    header = b"{\\rtf1\\ansi\\ansicpg1252\\fromtext\\deff1\\deff0\\deff"
    result = deencapsulate(header + FONT_TABLE + b"\\'82\\'a0}")
    assert result.text == "あ"


def test_a_font_the_table_does_not_define_is_reported() -> None:
    result = run(b"{\\f9\\'e9}")
    assert result.text == "é"
    assert codes(result) == [DiagnosticCode.UNKNOWN_FONT]
    assert "9" in result.diagnostics[0].message


def test_the_font_reverts_with_the_group_that_changed_it() -> None:
    assert text(b"{\\f1\\'82\\'a0}\\'e9") == "あé"


def test_a_font_change_outside_a_group_lasts_to_the_end_of_it() -> None:
    assert text(b"\\'e9\\f1\\'82\\'a0") == "éあ"


def test_the_documents_own_code_page_wins_over_the_fallback() -> None:
    document_bytes = b"{\\rtf1\\ansi\\ansicpg1251\\fromtext" + FONT_TABLE + b"\\'e0}"
    result = deencapsulate(document_bytes, fallback_codepage=1252)
    assert result.text == "а"
    assert result.document_codepage == 1251


def test_the_fallback_applies_when_the_document_declares_no_code_page() -> None:
    document_bytes = b"{\\rtf1\\ansi\\fromtext" + FONT_TABLE + b"\\'e0}"
    result = deencapsulate(document_bytes, fallback_codepage=1251)
    assert result.text == "а"
    assert result.document_codepage is None
    assert result.document_encoding == "cp1251"
    assert result.diagnostics == ()


def test_the_first_code_page_declaration_wins() -> None:
    """MS-OXRTFEX 2.2.3.2 calls it "the default code page, as specified in the RTF
    header", so a later one is not a change of encoding for text already read."""
    document_bytes = (
        b"{\\rtf1\\ansi\\ansicpg1252\\ansicpg1251\\fromtext" + FONT_TABLE + b"\\'e9}"
    )
    result = deencapsulate(document_bytes)
    assert result.document_codepage == 1252
    assert result.text == "é"


def test_a_code_page_with_no_decoder_falls_back_and_is_reported() -> None:
    """1200 is UTF-16LE, which :func:`~golden_retriever.codepages.encoding_for_codepage`
    excludes deliberately: it is not byte-oriented, so decoding a document of ``\\'HH``
    escapes with it would produce plausible garbage instead of an answer a caller can
    distrust."""
    document_bytes = b"{\\rtf1\\ansi\\ansicpg1200\\fromtext" + FONT_TABLE + b"\\'e9}"
    result = deencapsulate(document_bytes, fallback_codepage=1252)
    assert result.document_codepage == 1200
    assert result.document_encoding == "cp1252"
    assert codes(result) == [DiagnosticCode.UNSUPPORTED_CODEPAGE]
    with pytest.raises(UnsupportedCodePageError):
        deencapsulate(document_bytes, strict=True)


def test_bytes_their_code_page_does_not_define_become_replacements() -> None:
    result = run(b"{\\f1\\'82\\'82\\'82}")
    assert result.text is not None
    assert result.text.count(FFFD) >= 1
    assert codes(result) == [DiagnosticCode.UNDECODABLE_BYTES]


def test_content_damage_never_escalates_under_strict() -> None:
    """An unknown font, an undecodable byte and a lone surrogate are all damage inside
    the document; refusing to answer would not help a caller."""
    result = run(b"{\\f9\\'e9}{\\f1\\'82}\\uc0\\u-10179 ", strict=True)
    assert set(codes(result)) == {
        DiagnosticCode.UNKNOWN_FONT,
        DiagnosticCode.UNDECODABLE_BYTES,
        DiagnosticCode.UNPAIRED_SURROGATE,
    }


# --- Structural damage ---


def test_a_document_with_no_font_table_is_reported() -> None:
    document_bytes = b"{\\rtf1\\ansi\\ansicpg1252\\fromtext\\'e9}"
    result = deencapsulate(document_bytes)
    assert result.text == "é"
    assert codes(result) == [DiagnosticCode.MISSING_FONT_TABLE]
    with pytest.raises(MissingFontTableError):
        deencapsulate(document_bytes, strict=True)


def test_a_missing_rtf_heading_is_reported_and_read_anyway() -> None:
    """MS-OXRTFEX note A<13>: implementations "ignore the absence of the \\rtf1 keyword
    at the beginning of the RTF encoded text and try to de-encapsulate the text
    anyway"."""
    document_bytes = b"{\\fromtext" + FONT_TABLE + b"kept}"
    result = deencapsulate(document_bytes)
    assert result.text == "kept"
    assert codes(result) == [DiagnosticCode.MISSING_RTF_MAGIC]
    with pytest.raises(MalformedRtfError):
        deencapsulate(document_bytes, strict=True)


@pytest.mark.parametrize(
    ("document_bytes", "expected"),
    [
        (b"{\\rtf1\\ansi\\fromtext" + FONT_TABLE + b"{kept", "kept"),
        (b"{\\rtf1\\ansi\\fromtext" + FONT_TABLE + b"kept}}}", "kept"),
    ],
    ids=["unclosed", "stray-close"],
)
def test_groups_that_do_not_balance_are_reported_and_read_anyway(
    document_bytes: bytes, expected: str
) -> None:
    result = deencapsulate(document_bytes)
    assert result.text == expected
    assert DiagnosticCode.UNBALANCED_GROUPS in codes(result)
    with pytest.raises(MalformedRtfError):
        deencapsulate(document_bytes, strict=True)


def test_a_truncated_font_table_leaves_the_document_unbalanced() -> None:
    """The table consumes the driver's own tokens, so a table that never closes is the
    same failure as any other unclosed group."""
    result = deencapsulate(b"{\\rtf1\\ansi\\fromtext{\\fonttbl{\\f0\\fnil Arial;}")
    assert result.text == ""
    assert codes(result) == [DiagnosticCode.UNBALANCED_GROUPS]
    assert set(result.fonts) == {0}


def test_a_binary_payload_running_past_the_end_is_reported() -> None:
    """``\\binN`` is length-prefixed, so a truncated document is only detectable here --
    and it occurs inside ``{\\pict...}``, a destination whose content is skipped, so the
    check has to happen before the skip."""
    result = deencapsulate(
        b"{\\rtf1\\ansi\\fromtext" + FONT_TABLE + b"{\\pict\\bin32 short"
    )
    assert codes(result) == [
        DiagnosticCode.TRUNCATED_BIN,
        DiagnosticCode.UNBALANCED_GROUPS,
    ]
    with pytest.raises(MalformedRtfError):
        deencapsulate(
            b"{\\rtf1\\ansi\\fromtext" + FONT_TABLE + b"{\\pict\\bin32 short",
            strict=True,
        )


def test_a_binary_payload_is_never_content() -> None:
    assert text(b"a{\\pict\\bin4 \\{x}}b") == "ab"
    assert text(b"a\\bin4 textb") == "ab"


def test_an_empty_document_produces_an_empty_string() -> None:
    result = deencapsulate(b"{\\rtf1\\fromtext}")
    assert result.text == ""
    assert codes(result) == [DiagnosticCode.MISSING_FONT_TABLE]


def test_bare_line_endings_in_the_source_are_not_content() -> None:
    """RTF 1.9.1 treats a carriage return and a line feed in the source as
    insignificant; only ``\\par`` and ``\\line`` end a line."""
    assert text(b"a\r\nb\rc\nd") == "abcd"
