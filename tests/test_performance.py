"""Performance checks, deselected by default.

Marked ``slow`` and run with ``pixi run test-slow``. A wall-clock assertion in a test
suite is a shape check, not a benchmark: it exists to catch the kind of regression that
turns a single pass into a quadratic one -- a per-token string concatenation, a rescan of
the output, a table rebuilt inside a loop.

The threshold is therefore deliberately loose. The target is well under 50 ms for a
message-sized document; the number asserted is five times that, so the test states the
intent without failing on a busy machine.
"""

import time

import pytest

from golden_retriever import ContentType, deencapsulate

DOCUMENT_SIZE = 250_000
"""How many bytes to build: more than any mail body, enough for a quadratic path to
show."""

BUDGET_SECONDS = 0.25
"""Five times the target, because a shared CI runner is not a quiet machine."""

HEADER = (
    b"{\\rtf1\\ansi\\ansicpg1252\\fromhtml1\\deff0"
    b"{\\fonttbl{\\f0\\fswiss\\fcharset0 Arial;}"
    b"{\\f1\\fnil\\fcharset128 MS Mincho;}}"
    b"{\\colortbl;\\red0\\green0\\blue0;}"
    b"\\uc1\\pard\\plain"
)

BLOCK = (
    b"{\\*\\htmltag64 <p>}\\htmlrtf {\\pard\\plain\\f0\\fs22\\htmlrtf0 "
    b"Text with an escape r\\'e9sum\\'e9, a \\u8212  dash, {\\f1 \\'82\\'a0} in "
    b"another code page, and a {\\*\\htmltag84 <br>}break."
    b"\\htmlrtf\\par}\\htmlrtf0 {\\*\\htmltag72 </p>\\par}"
)
"""One paragraph of everything the reader has to do, repeated to build the document."""


def document() -> bytes:
    """A ``DOCUMENT_SIZE``-ish document of realistic encapsulated HTML."""
    repeats = (DOCUMENT_SIZE - len(HEADER)) // len(BLOCK)
    return HEADER + BLOCK * repeats + b"}"


@pytest.mark.slow
def test_a_message_sized_document_is_de_encapsulated_promptly() -> None:
    raw = document()
    assert len(raw) >= DOCUMENT_SIZE - len(BLOCK)

    start = time.perf_counter()
    result = deencapsulate(raw)
    elapsed = time.perf_counter() - start

    assert result.content_type is ContentType.HTML
    assert result.diagnostics == ()
    assert elapsed < BUDGET_SECONDS, f"{len(raw)} bytes took {elapsed:.3f}s"


@pytest.mark.slow
def test_cost_grows_with_the_input_rather_than_faster() -> None:
    """The property the loose threshold above cannot pin down.

    Doubling the input must roughly double the work. A quadratic path would show here as
    a ratio near four, whichever machine this runs on.
    """
    raw = document()
    doubled = raw[:-1] + BLOCK * ((len(raw) - len(HEADER)) // len(BLOCK)) + b"}"

    def timed(data: bytes) -> float:
        start = time.perf_counter()
        deencapsulate(data)
        return time.perf_counter() - start

    # Once through each first: the first call of the process pays for imports and for
    # every codec it looks up, which would land entirely on whichever ran first.
    timed(raw)
    timed(doubled)

    ratio = timed(doubled) / timed(raw)
    assert ratio < 3, f"{len(doubled)} bytes cost {ratio:.1f} times {len(raw)} bytes"


@pytest.mark.slow
def test_deep_nesting_does_not_recurse() -> None:
    """The reader keeps its own stack, so nesting is bounded by memory rather than by
    Python's recursion limit.

    A depth this far past that limit is what tells the two apart.
    """
    depth = 50_000
    raw = HEADER + b"{" * depth + b"text" + b"}" * depth + b"}"
    result = deencapsulate(raw)
    assert result.body == "text"
    assert result.diagnostics == ()
