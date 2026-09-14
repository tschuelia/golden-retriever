"""Golden documents, compared byte for byte.

The inline tests each pin one rule. These pin whole documents of the shape a producer
writes -- header, font table, header tables, then a body -- so that a change which is
correct in isolation but wrong in combination still fails.

The pairs are listed explicitly rather than discovered from the directory: a fixture that
went missing would make an auto-discovering suite quietly smaller instead of red.
"""

import pytest
from conftest import read_bytes

from golden_retriever import deencapsulate
from golden_retriever.result import ContentType

TEXT_PAIRS = ["fromtext_plain"]
"""Fixtures whose ``.rtf`` de-encapsulates to the matching ``.txt``."""


@pytest.mark.parametrize("name", TEXT_PAIRS)
def test_a_plain_text_document_matches_its_golden_output(name: str) -> None:
    """Compared as bytes, and encoded rather than decoded: MS-OXRTFEX 2.2.3.3 maps
    ``\\par`` to CRLF, and reading the golden as text would translate those away on some
    platforms and hide a line-ending regression on the others."""
    result = deencapsulate(read_bytes(f"{name}.rtf"))
    assert result.content_type is ContentType.TEXT
    assert result.text is not None
    assert result.text.encode("utf-8") == read_bytes(f"{name}.txt")


@pytest.mark.parametrize("name", TEXT_PAIRS)
def test_a_golden_document_is_clean_input(name: str) -> None:
    """Every golden is a document a producer could have written, so nothing about it is
    worth reporting -- which is what makes ``diagnostics`` meaningful elsewhere."""
    result = deencapsulate(read_bytes(f"{name}.rtf"))
    assert result.diagnostics == ()


@pytest.mark.parametrize("name", TEXT_PAIRS)
def test_strict_mode_changes_no_output(name: str) -> None:
    """``strict`` decides whether a problem is raised or recorded; it never decides
    which characters come out."""
    lenient = deencapsulate(read_bytes(f"{name}.rtf"))
    strict = deencapsulate(read_bytes(f"{name}.rtf"), strict=True)
    assert strict == lenient


@pytest.mark.parametrize("name", TEXT_PAIRS)
def test_a_golden_document_still_has_its_line_endings(name: str) -> None:
    """A ``.gitattributes`` regression would rewrite these files on checkout, and every
    other assertion here would then fail for a reason that has nothing to do with the
    code."""
    assert b"\r\n" in read_bytes(f"{name}.rtf")
    assert b"\r\n" in read_bytes(f"{name}.txt")
    assert b"\n\n" not in read_bytes(f"{name}.txt")
