"""Tests for the HTML de-encapsulation path (MS-OXRTFEX 2.2.3.2).

The group stack, HTMLRTF suppression, destination skipping, the ``\\uN``/``\\ucN`` skip
count and the code-page resolution are shared with the plain-text path and are covered
in full by ``test_deencapsulate_text.py``. This file covers what HTMLTAG adds -- its
CONTENT, its character table, its code page and its interaction with suppression -- plus
the two regressions that would each lose content silently.
"""

import pytest

from golden_retriever.deencapsulator import deencapsulate
from golden_retriever.emitter import REPLACEMENT_CHARACTER
from golden_retriever.exceptions import MalformedRtfError
from golden_retriever.result import ContentType, DeEncapsulationResult, DiagnosticCode

FFFD = REPLACEMENT_CHARACTER

SHY = "\u00ad"
"""U+00AD, the soft hyphen MS-OXRTFEX 2.1.3.1.4.2 gives for ``\\_`` as ``&shy;``.

Written as an escape, like the character tables: it renders as nothing at all.
"""

FONT_TABLE = (
    b"{\\fonttbl{\\f0\\fnil\\fcharset0 Arial;}{\\f1\\fnil\\fcharset128 MS Mincho;}}"
)
"""Font 0 in the document's code page, font 1 in cp932, per RTF 1.9.1's charsets."""

HEADER = b"{\\rtf1\\ansi\\ansicpg1252\\fromhtml1\\deff0" + FONT_TABLE
"""A header a producer could have written, minus nothing that matters."""


def document(body: bytes) -> bytes:
    """``body`` inside a minimal well-formed FROMHTML document."""
    return HEADER + body + b"}"


def tag(content: bytes) -> bytes:
    """``content`` as the CONTENT of an HTMLTAG destination group.

    The shape is MS-OXRTFEX 2.1.3.1.4's ``"{" HTMLTAG [HTMLTagParameter] DELIMITER
    CONTENT "}"``, with the parameter omitted.
    """
    return b"{\\*\\htmltag " + content + b"}"


def run(body: bytes, *, strict: bool = False) -> DeEncapsulationResult:
    """De-encapsulate ``body``, asserting the result is routed as HTML."""
    result = deencapsulate(document(body), strict=strict)
    assert result.content_type is ContentType.HTML
    assert result.text is None
    assert result.html is not None
    return result


def html(body: bytes) -> str:
    """The HTML ``body`` de-encapsulates to."""
    result = run(body)
    assert result.html is not None
    return result.html


def codes(result: DeEncapsulationResult) -> list[str]:
    return [diagnostic.code for diagnostic in result.diagnostics]


def test_a_clean_document_produces_html_and_nothing_else() -> None:
    result = run(tag(b"<html><body>") + b"Hello." + tag(b"</body></html>"))
    assert result.html == "<html><body>Hello.</body></html>"
    assert result.diagnostics == ()
    assert result.document_codepage == 1252
    assert result.document_encoding == "cp1252"
    assert set(result.fonts) == {0, 1}
    assert result.body == result.html
    assert result.declared_html_charset is None


def test_the_charset_the_extracted_markup_declares_is_reported() -> None:
    """The declaration is part of the extracted HTML like any other tag, and reporting
    it is what lets a caller fix it before writing the result out as something else.

    It describes the bytes the producer encapsulated, so it is reported rather than acted
    on: those bytes are already decoded by the time a caller sees this.
    """
    meta = b'<meta http-equiv="Content-Type" content="text/html; charset=us-ascii">'
    result = run(tag(b"<html><head>") + tag(meta) + tag(b"</head>"))
    assert result.declared_html_charset == "us-ascii"
    assert result.document_encoding == "cp1252"


# --- The HTMLTAG destination group (MS-OXRTFEX 2.1.3.1.4) ---


def test_a_tag_group_yields_its_fragment_verbatim() -> None:
    """MS-OXRTFEX 2.1.3.1.4.2: the CONTENT is "a fragment of the original HTML
    content"."""
    assert html(tag(b'<FONT face="symbol">')) == '<FONT face="symbol">'


@pytest.mark.parametrize(
    "opening",
    [b"\\htmltag", b"\\htmltag0", b"\\htmltag84", b"\\htmltag148"],
    ids=lambda value: value.decode(),
)
def test_the_tag_parameter_never_reaches_the_output(opening: bytes) -> None:
    """The ``HTMLTagParameter`` is a property of the control word rather than part of
    the fragment, and MS-OXRTFEX 2.2.3.2 asks only for the CONTENT."""
    assert html(b"{\\*" + opening + b" <br>}") == "<br>"


def test_the_delimiter_space_is_consumed_and_a_second_one_is_content() -> None:
    """MS-OXRTFEX 2.1.3.1.4 puts one DELIMITER between the control word and the CONTENT,
    and RTF 1.9.1 makes that the single optional space a keyword may end with.

    A second space is a space the producer wrote inside the fragment.
    """
    assert html(b"{\\*\\htmltag84 <br>}") == "<br>"
    assert html(b"{\\*\\htmltag84  <br>}") == " <br>"


@pytest.mark.parametrize(
    "body",
    [b"{\\*\\htmltag }", b"{\\*\\htmltag84}"],
    ids=["delimiter-only", "parameter-only"],
)
def test_an_empty_fragment_produces_nothing(body: bytes) -> None:
    assert html(body) == ""


def test_escaped_delimiters_inside_a_fragment_are_the_characters_themselves() -> None:
    """MS-OXRTFEX 2.1.3.1.4.2 gives ``\\{``, ``\\}`` and ``\\\\`` their literal
    characters, which is how a fragment can contain RTF's own syntax."""
    assert html(tag(b"\\{x\\}")) == "{x}"
    assert html(tag(b"a\\\\b")) == "a\\b"


def test_par_and_tab_inside_a_fragment_become_their_characters() -> None:
    """MS-OXRTFEX 2.1.3.1.4.2 maps ``\\par`` to %x0D.0A and ``\\tab`` to %x09, the same
    as outside a tag."""
    assert html(tag(b"a\\par b\\tab c")) == "a\r\nb\tc"


def test_the_content_table_of_a_fragment_is_not_the_body_table() -> None:
    """``\\_`` is the row the two specifications disagree about: MS-OXRTFEX 2.1.3.1.4.2
    gives ``&shy;``, and RTF 1.9.1 gives the non-breaking hyphen U+2011.

    Each context follows its own specification, which is a documented deviation.
    """
    assert html(tag(b"a\\_b")) == "a" + SHY + "b"
    assert html(b"a\\_b") == "a\u2011b"


@pytest.mark.parametrize(
    "word",
    [b"\\line", b"\\enspace", b"\\emspace", b"\\zwnj", b"\\ltrmark"],
    ids=lambda value: value.decode(),
)
def test_a_control_word_absent_from_the_content_table_stands_for_nothing(
    word: bytes,
) -> None:
    """MS-OXRTFEX 2.1.3.1.4.2 enumerates what a fragment may contain, so a control word
    it omits is ignored inside a tag even where the RTF 1.9.1 table defines it."""
    assert html(tag(b"a" + word + b" b")) == "ab"
    assert html(b"a" + word + b" b") != "ab"


def test_a_unicode_escape_inside_a_fragment_is_still_a_character() -> None:
    """``\\uN`` is not in the CONTENT table because it is not an escape for a fixed
    character; it names one directly, and a fragment that carries one carries that
    character."""
    assert html(tag(b"\\uc0\\u8212")) == "—"


# --- Which code page a fragment is written in ---


def test_a_fragment_decodes_in_the_document_code_page_whatever_font_applies() -> None:
    """A tag is markup the producer wrote in "the default code page, as specified in the
    RTF header" (MS-OXRTFEX 2.2.3.2).

    Font 1 is cp932 here, where 0xE9 is a lead byte rather than a character, so the
    document's own cp1252 is the only reading that produces this.
    """
    assert html(b"{\\f1" + tag(b"\\'e9") + b"}") == "é"
    assert html(tag(b"\\f1\\'e9")) == "é"


def test_body_text_still_decodes_in_the_font_that_claims_it() -> None:
    """The contrast to the case above: outside a tag, MS-OXRTFEX 2.2.3.2 requires the
    reader to "use the code page information, as specified for each font in a font
    table"."""
    assert html(b"{\\f1\\'82\\'a0}") == "あ"


def test_a_group_inside_a_fragment_stays_in_the_tag_destination() -> None:
    """The destination is inherited like every other frame field, so a producer that
    wraps part of a fragment in a group gets the same code page and the same table
    inside it."""
    assert html(b"{\\*\\htmltag {\\f1\\'e9}}") == "é"
    assert html(b"{\\*\\htmltag {a\\_b}}") == "a" + SHY + "b"


def test_a_font_charset_resolves_through_the_documents_code_page() -> None:
    """``\\fcharset0`` is ANSI_CHARSET, i.e. "the system ANSI code page", which
    ``\\ansicpgN`` is the document's declaration of."""
    document_bytes = (
        b"{\\rtf1\\ansi\\ansicpg1250\\fromhtml1\\deff0" + FONT_TABLE + b"{\\f0\\'9c}}"
    )
    result = deencapsulate(document_bytes)
    assert result.html == "ś"
    assert result.fonts[0].encoding == "cp1250"


def test_a_font_the_table_does_not_define_falls_back_and_is_reported() -> None:
    result = run(b"{\\f9\\'e9}")
    assert result.html == "é"
    assert codes(result) == [DiagnosticCode.UNKNOWN_FONT]


def test_bytes_their_code_page_does_not_define_become_replacements() -> None:
    """0x81, 0x8D, 0x8F, 0x90 and 0x9D are the five bytes Windows-1252 leaves
    undefined."""
    result = run(b"{\\f0\\'81\\'8d\\'8f\\'90\\'9d}")
    assert result.html == FFFD * 5
    assert codes(result) == [DiagnosticCode.UNDECODABLE_BYTES]
    assert "5" in result.diagnostics[0].message


def test_a_delimiter_space_after_each_header_word_is_tolerated() -> None:
    """RTF 1.9.1 allows every control word to end with one, and a producer that writes
    them must not change how the header reads."""
    document_bytes = (
        b"{\\rtf1 \\ansi \\ansicpg1252 \\fromhtml1 \\deff0 " + FONT_TABLE + b"x}"
    )
    result = deencapsulate(document_bytes)
    assert result.html == "x"
    assert result.document_codepage == 1252
    assert result.diagnostics == ()


# --- A tag group written without its \* (MS-OXRTFEX A<14>) ---


def test_a_tag_group_without_the_star_is_read_as_a_tag_and_reported() -> None:
    """Treating it as body content would emit RTF markup into the output, so the group
    is de-encapsulated anyway and only the deviation from 2.1.3.1.4's grammar is
    recorded."""
    result = run(b"{\\htmltag84 <br>}")
    assert result.html == "<br>"
    assert codes(result) == [DiagnosticCode.UNPREFIXED_HTMLTAG]
    with pytest.raises(MalformedRtfError):
        run(b"{\\htmltag84 <br>}", strict=True)


def test_the_missing_star_is_reported_once_however_many_tags_omit_it() -> None:
    """A producer that omits it omits it on every tag, and one diagnostic per tag would
    bury everything else in the list."""
    result = run(b"{\\htmltag64 <p>}text{\\htmltag72 </p>}")
    assert result.html == "<p>text</p>"
    assert codes(result) == [DiagnosticCode.UNPREFIXED_HTMLTAG]


def test_a_tag_group_with_the_star_is_not_reported() -> None:
    result = run(tag(b"<br>"))
    assert result.diagnostics == ()


# --- HTMLRTF suppression (MS-OXRTFEX 2.1.3.1.3) ---


def test_the_rtf_only_rendering_is_dropped_and_the_markup_kept() -> None:
    """The shape a producer actually writes: the RTF that renders the message sits inside
    HTMLRTF regions, and the HTML it stands for sits in HTMLTAG groups.

    The suppression here is turned on outside a group and off inside it, which is what
    2.1.3.1.3's transfer-and-restore rule has to get right.
    """
    body = (
        b"{\\*\\htmltag64 <p>}\\htmlrtf {\\htmlrtf0 Hello"
        b"{\\*\\htmltag84 <br>}\\htmlrtf\\line \\htmlrtf0 world"
        b"\\htmlrtf }\\htmlrtf0 {\\*\\htmltag72 </p>}"
    )
    assert html(body) == "<p>Hello<br>world</p>"


def test_a_fragment_is_copied_even_where_suppression_was_left_on() -> None:
    """A documented deviation.

    HTMLRTF exists to hide RTF-only markup, and a fragment *is* the HTML output, so
    entering a tag clears suppression for that group rather than deleting a tag the
    producer did write.
    """
    assert html(b"\\htmlrtf1" + tag(b"<br>") + b"hidden\\htmlrtf0 shown") == "<br>shown"


def test_the_current_font_is_tracked_while_suppressed() -> None:
    """MS-OXRTFEX 2.2.3.2 states this exception outright: a reader "SHOULD track the
    current font even when the corresponding \\fN control word is inside of a fragment
    that is disabled with an HTMLRTF control word"."""
    assert html(b"\\htmlrtf1\\f1 hidden\\htmlrtf0\\'82\\'a0") == "あ"


# --- Destinations that must not leak into the markup ---


@pytest.mark.parametrize(
    "body",
    [
        b"{\\colortbl;\\red0\\green0\\blue0;}",
        b"{\\stylesheet{\\s0 Normal;}}",
        b"{\\info{\\title Secret}{\\author Nobody}}",
        b"{\\pict\\pngblip 89504e470d0a1a0a}",
        b"{\\pict\\pngblip\\bin8 \x89PNG\r\n\x1a\n}",
        b"{\\*\\generator Something 1.0;}",
        b'{\\*\\mhtmltag133 <IMG src="http://example.com/i.gif">}',
        b"{\\*\\htmlbase http://example.com/}",
    ],
    ids=[
        "colortbl",
        "stylesheet",
        "info",
        "pict-hex",
        "pict-bin",
        "generator",
        "mhtmltag",
        "htmlbase",
    ],
)
def test_a_group_producing_no_visible_text_leaks_nothing_into_the_markup(
    body: bytes,
) -> None:
    """MS-OXRTFEX 2.2.3.2: "Ignore and skip any standard RTF destination groups that do
    not produce visible text", and "Ignore any ignorable destination groups (that is,
    groups that start with "\\*")".

    Asserted with markup on both sides, because a skip that ran one group too far would
    take the tag after it as well.
    """
    result = run(tag(b"<p>") + body + tag(b"</p>"))
    assert result.html == "<p></p>"
    assert result.diagnostics == ()


def test_an_mhtmltag_group_is_dropped_in_favor_of_its_htmltag_twin() -> None:
    """MS-OXRTFEX 2.1.3.1.5 note <8>: an MHTMLTAG group's content "is also encapsulated
    in another HTMLTAG destination group; thus, an MHTMLTAG destination group can be
    safely ignored"."""
    body = (
        b'{\\*\\mhtmltag133 <IMG src="http://example.com/i.gif">}'
        b'{\\*\\htmltag133 <IMG src="cid:1">}'
    )
    assert html(body) == '<IMG src="cid:1">'


def test_a_base_url_is_never_resolved_or_emitted() -> None:
    """No network access is ever performed, and a base URL is not part of the extracted
    markup: as a control word it stands for no character, and as a group ``\\*`` skips
    it."""
    assert html(b"a\\htmlbase b") == "ab"
    assert html(b"a{\\*\\htmlbase http://example.com/}b") == "ab"


def test_a_hidden_hex_escape_does_not_delete_an_identical_visible_one() -> None:
    """Content is emitted, never deleted, so a byte inside a skipped field instruction
    cannot reach the identical bytes in the visible text around it.

    ``\\fldrslt`` is the field's visible result and stays, which is why nothing names
    ``\\field`` as a non-visible destination.
    """
    body = (
        b"\\'e4{\\field{\\*\\fldinst{HYPERLINK \"x\\'e4y\"}}{\\fldrslt visible}}\\'e4"
    )
    result = run(body)
    assert result.html == "ävisibleä"
    assert result.html.count("ä") == 2
    assert "x" not in result.html
    assert "y" not in result.html
