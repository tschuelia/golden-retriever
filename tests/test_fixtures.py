"""Golden documents, compared byte for byte.

The inline tests each pin one rule. These pin whole documents of the shape a producer
writes -- header, font table, header tables, then a body -- so that a change which is
correct in isolation but wrong in combination still fails.

The pairs are listed in ``conftest.py`` rather than discovered from the directory: a
fixture that went missing would make an auto-discovering suite quietly smaller instead of
red. The mutation fuzz reads the same list.
"""

import pytest
from conftest import HTML_PAIRS, TEXT_PAIRS, read_bytes

from ottertf import deencapsulate
from ottertf.result import ContentType

PAIRS = [(name, "txt", ContentType.TEXT) for name in TEXT_PAIRS] + [
    (name, "html", ContentType.HTML) for name in HTML_PAIRS
]
"""Every pair, as ``(name, output suffix, expected content type)``."""

golden = pytest.mark.parametrize(
    ("name", "suffix", "content_type"), PAIRS, ids=[name for name, _, _ in PAIRS]
)


@golden
def test_a_golden_document_matches_its_golden_output(
    name: str, suffix: str, content_type: ContentType
) -> None:
    """Compared as bytes, and encoded rather than decoded: MS-OXRTFEX 2.2.3.2 maps
    ``\\par`` to CRLF, and reading the golden as text would translate those away on some
    platforms and hide a line-ending regression on the others."""
    result = deencapsulate(read_bytes(f"{name}.rtf"))
    assert result.content_type is content_type
    assert result.body.encode("utf-8") == read_bytes(f"{name}.{suffix}")


@golden
def test_a_golden_document_is_clean_input(
    name: str, suffix: str, content_type: ContentType
) -> None:
    """Every golden is a document a producer could have written, so nothing about it is
    worth reporting -- which is what makes ``diagnostics`` meaningful elsewhere."""
    result = deencapsulate(read_bytes(f"{name}.rtf"))
    assert result.diagnostics == ()


@golden
def test_strict_mode_changes_no_output(
    name: str, suffix: str, content_type: ContentType
) -> None:
    """``strict`` decides whether a problem is raised or recorded; it never decides
    which characters come out."""
    lenient = deencapsulate(read_bytes(f"{name}.rtf"))
    strict = deencapsulate(read_bytes(f"{name}.rtf"), strict=True)
    assert strict == lenient


def test_the_charset_a_golden_document_declares_is_reported() -> None:
    """``minimal_html`` carries the ``http-equiv`` declaration a producer writes, inside
    an HTMLTAG group like the rest of its markup."""
    result = deencapsulate(read_bytes("minimal_html.rtf"))
    assert result.declared_html_charset == "us-ascii"


@golden
def test_a_golden_document_still_has_its_line_endings(
    name: str, suffix: str, content_type: ContentType
) -> None:
    """A ``.gitattributes`` regression would rewrite these files on checkout, and every
    other assertion here would then fail for a reason that has nothing to do with the
    code.

    Every line feed in the expected output belongs to a CRLF, so a conversion in either
    direction is caught.
    """
    output = read_bytes(f"{name}.{suffix}")
    assert b"\r\n" in read_bytes(f"{name}.rtf")
    assert b"\r\n" in output
    assert output.count(b"\n") == output.count(b"\r\n")
