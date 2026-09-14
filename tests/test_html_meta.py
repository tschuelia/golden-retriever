"""Tests for reading and rewriting an HTML charset declaration.

The two spellings, the two places an inserted declaration can go, and idempotence --
which is the property that makes the function safe to call on output that has already
been through it.
"""

import pytest

from golden_retriever.html_meta import declared_charset, normalize_charset_declaration

SHORT = '<meta charset="windows-1252">'
"""The short spelling of a declaration."""

PRAGMA = '<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">'
"""The ``http-equiv`` spelling, which is the one encapsulating producers write."""


def head(*elements: str) -> str:
    """A small document whose head contains ``elements``."""
    return "<html><head>" + "".join(elements) + "</head><body><p>Hi.</p></body></html>"


# --- Reading a declaration ---


@pytest.mark.parametrize("element", [SHORT, PRAGMA], ids=["charset", "http-equiv"])
def test_either_spelling_is_recognized(element: str) -> None:
    assert declared_charset(head(element)) == "windows-1252"


@pytest.mark.parametrize(
    "element",
    [
        "<meta charset=us-ascii>",
        "<meta charset='us-ascii'>",
        '<META CHARSET="us-ascii">',
        '<meta charset = "us-ascii" >',
        '<meta charset="us-ascii"/>',
        "<meta http-equiv=Content-Type content='text/html; charset=us-ascii'>",
        '<meta content="text/html; charset=us-ascii" http-equiv="Content-Type">',
        '<meta http-equiv="content-type" content="text/html;charset=us-ascii">',
    ],
    ids=[
        "bare",
        "single-quoted",
        "uppercase",
        "spaced-equals",
        "self-closing",
        "bare-http-equiv",
        "attributes-reversed",
        "no-space-before-parameter",
    ],
)
def test_the_ways_a_producer_may_have_written_it(element: str) -> None:
    """Attribute order, quoting, case and surrounding whitespace all vary between
    producers, and none of them changes what was declared."""
    assert declared_charset(head(element)) == "us-ascii"


def test_the_value_is_returned_exactly_as_written() -> None:
    """Not normalized and not validated: the caller is told what the producer claimed,
    which is the only thing that is knowable here."""
    assert declared_charset(head('<meta charset="  Windows-1252  ">')) == (
        "  Windows-1252  "
    )
    assert declared_charset(head('<meta charset="no-such-codec">')) == "no-such-codec"


@pytest.mark.parametrize(
    "document",
    [
        "<p>No head, no meta.</p>",
        head(),
        head('<meta name="Generator" content="Something 1.0">'),
        head("<title>charset=us-ascii</title>"),
        head('<meta content="text/html; charset=us-ascii">'),
        head("<meta charset>"),
    ],
    ids=[
        "fragment",
        "empty-head",
        "other-meta",
        "text-that-looks-like-one",
        "content-without-http-equiv",
        "valueless-attribute",
    ],
)
def test_a_document_that_declares_nothing_reports_nothing(document: str) -> None:
    assert declared_charset(document) is None


def test_a_charset_attribute_wins_over_the_pragma_on_one_element() -> None:
    """Both on one element is a producer contradicting itself, and the short spelling is
    the one a browser gives precedence to."""
    element = (
        '<meta charset="us-ascii" http-equiv="Content-Type" '
        'content="text/html; charset=utf-8">'
    )
    assert declared_charset(head(element)) == "us-ascii"


def test_only_the_head_is_searched() -> None:
    """A ``<meta>`` in the body is quoted text -- a forwarded mail, an example in a code
    block -- rather than a declaration this document is making."""
    document = "<html><head></head><body>" + SHORT + "</body></html>"
    assert declared_charset(document) is None
    assert declared_charset("<html><body>" + SHORT) is None


def test_a_fragment_with_no_head_is_searched_whole() -> None:
    """Encapsulated content is not always a whole document, and a declaration in a
    fragment is still the only one there is."""
    assert declared_charset(SHORT + "<p>Hi.</p>") == "windows-1252"


# --- Rewriting a declaration ---


@pytest.mark.parametrize("element", [SHORT, PRAGMA], ids=["charset", "http-equiv"])
def test_either_spelling_is_rewritten_in_place(element: str) -> None:
    """Only the value changes, so the producer's own spelling of the element survives --
    a rewrite that replaced the element would drop the ``Content-Type`` with it."""
    rewritten = normalize_charset_declaration(head(element), "utf-8")
    assert declared_charset(rewritten) == "utf-8"
    assert rewritten == head(element.replace("windows-1252", "utf-8"))


def test_utf_8_is_the_default() -> None:
    assert declared_charset(normalize_charset_declaration(head(SHORT))) == "utf-8"


def test_a_document_with_a_head_gets_the_declaration_as_its_first_child() -> None:
    """As early in the head as possible, because a declaration a browser reads after it
    has already guessed is a declaration it ignores."""
    rewritten = normalize_charset_declaration(head("<title>Hi</title>"), "utf-8")
    assert rewritten == head('<meta charset="utf-8">', "<title>Hi</title>")


def test_a_document_without_a_head_gets_the_declaration_prepended() -> None:
    rewritten = normalize_charset_declaration("<p>Hi.</p>", "utf-8")
    assert rewritten == '<meta charset="utf-8"><p>Hi.</p>'


def test_nothing_but_the_declaration_changes() -> None:
    """No line break and no reindentation, so the diff against the extracted HTML is
    exactly the declaration and nothing that could shift the content."""
    document = "<html><head>\r\n<title>Hi</title>\r\n</head><body>x</body></html>"
    rewritten = normalize_charset_declaration(document, "utf-8")
    assert rewritten.replace('<meta charset="utf-8">', "") == document


@pytest.mark.parametrize(
    "document",
    [
        head(SHORT),
        head(PRAGMA),
        head("<title>Hi</title>"),
        "<p>Hi.</p>",
        "<html><body><p>Hi.</p></body></html>",
    ],
    ids=["charset", "http-equiv", "inserted", "prepended", "body-only"],
)
def test_rewriting_twice_changes_nothing_the_second_time(document: str) -> None:
    """The insertion cases are the ones this pins: a declaration this function added
    must be one it finds again, or output written out repeatedly grows a ``<meta>`` per
    pass."""
    once = normalize_charset_declaration(document, "utf-8")
    assert normalize_charset_declaration(once, "utf-8") == once


def test_an_encoding_with_no_codec_is_refused() -> None:
    """The name is interpolated into markup, so a value that is not a codec name is
    rejected rather than written into the document."""
    with pytest.raises(ValueError, match="no available codec"):
        normalize_charset_declaration(head(SHORT), 'utf-8"><script>alert(1)</script>')
    with pytest.raises(ValueError, match="no available codec"):
        normalize_charset_declaration(head(SHORT), "not-a-codec")


def test_a_refused_encoding_leaves_the_document_alone() -> None:
    document = head(SHORT)
    with pytest.raises(ValueError, match="no available codec"):
        normalize_charset_declaration(document, "not-a-codec")
    assert declared_charset(document) == "windows-1252"


def test_the_declared_name_is_written_out_as_given() -> None:
    """``cp1252`` and ``windows-1252`` are the same codec under two names, and the
    caller decides which name the document should claim."""
    rewritten = normalize_charset_declaration(head(SHORT), "cp1252")
    assert declared_charset(rewritten) == "cp1252"
