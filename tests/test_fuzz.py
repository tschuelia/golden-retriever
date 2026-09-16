"""Fuzzing the contract, on inputs no producer would ever write.

Two generators, both seeded from one constant so that a failure reproduces exactly:

- Random bytes behind a ``{\\rtf1\\fromhtml1`` header, which is what makes them reach
  the HTML driver at all rather than being turned away as native RTF.
- Mutations of the golden documents, which stay well-formed for long enough to break
  somewhere deep in the reader instead of in its first few tokens.

What is being fuzzed is the promise the README makes, not any particular output: for any
``bytes`` input, only a :class:`~ottertf.OtteRTFError` escapes, the body
is always encodable as UTF-8, and ``strict`` decides whether a problem is raised rather
than which characters come out.

Each test asserts that some of its cases got through, too. A regression that made every
input raise immediately would otherwise satisfy every other assertion here.
"""

import random
from collections.abc import Callable

import pytest
from conftest import GOLDEN_DOCUMENTS, read_bytes

from ottertf import ContentType, OtteRTFError, deencapsulate
from ottertf.detect import detect_content_type

SEED = 1252
"""Fixed, so that a failing case is the same case tomorrow.

Raising it to find new cases is a change to make deliberately, and to keep.
"""

RANDOM_CASES = 1000
"""Cases per random generator, of which there are two."""

MUTATIONS = 200
"""Mutations per golden document."""

HEADER = b"{\\rtf1\\fromhtml1"
"""Enough of a header for MS-OXRTFEX 2.2.3.1 to route the rest to the HTML driver."""

FRAGMENTS = [
    # Structure, which is what decides whether anything else is reached at all.
    b"{",
    b"}",
    b"\\",
    b"\\*",
    b"\r\n",
    b" ",
    b";",
    # Header words, including values with no decoder and no font table to resolve.
    b"\\ansi",
    b"\\ansicpg1252",
    b"\\ansicpg1200",
    b"\\ansicpg99999",
    b"\\deff0",
    b"\\deff9",
    b"\\fonttbl",
    b"\\f0",
    b"\\f9",
    b"\\fcharset0",
    b"\\fcharset2",
    b"\\fcharset128",
    b"\\fcharset199",
    b"\\cpg1251",
    # Destinations, both the skipped kinds and the two that must not be skipped.
    b"\\htmltag84",
    b"\\mhtmltag84",
    b"\\htmlbase",
    b"\\colortbl",
    b"\\stylesheet",
    b"\\info",
    b"\\pict",
    b"\\field",
    b"\\fldinst",
    b"\\fldrslt",
    b"\\generator",
    # Suppression, whose whole job is to interact with group boundaries.
    b"\\htmlrtf",
    b"\\htmlrtf0",
    b"\\htmlrtf1",
    # Characters, escapes and the skip count that governs them.
    b"\\par",
    b"\\tab",
    b"\\line",
    b"\\_",
    b"\\-",
    b"\\{",
    b"\\}",
    b"\\\\",
    b"\\uc0",
    b"\\uc1",
    b"\\uc9",
    b"\\u8212",
    b"\\u-10179",
    b"\\u-8704",
    b"\\u",
    b"\\u99999999999",
    b"\\'e4",
    b"\\'zz",
    b"\\'",
    # Length-prefixed payloads, the one construct a scanner cannot resynchronize in.
    b"\\bin4",
    b"\\bin",
    b"\\bin-1",
    b"\\bin99999",
    # Text, including bytes cp1252 leaves undefined and a control word past the
    # 32-letter limit RTF 1.9.1 sets.
    b"text",
    b"<br>",
    b"?",
    b"\x80\x81\x8d\x90\x9d",
    b"\xff\xfe\x00",
    b"\\" + b"z" * 40,
]
"""The pieces a token-salad case is assembled from.

Uniform random bytes rarely contain a backslash where it matters, so nearly all of their
cases die as plain text. These give the reader something to actually parse.
"""


def _random_bytes(rng: random.Random) -> bytes:
    return rng.randbytes(rng.randrange(1, 200))


def _token_salad(rng: random.Random) -> bytes:
    return b"".join(rng.choice(FRAGMENTS) for _ in range(rng.randrange(1, 60)))


def _mutate(rng: random.Random, data: bytes) -> bytes:
    """One byte-level corruption of ``data``.

    Truncation is in here because it is the mutation that reaches every ran-off-the-end
    path at once: a payload, a control word, a hex escape or a group can all be cut in
    half by it.
    """
    offset = rng.randrange(len(data))
    match rng.choice(("delete", "duplicate", "flip", "truncate")):
        case "delete":
            return data[:offset] + data[offset + 1 :]
        case "duplicate":
            return data[: offset + 1] + data[offset:]
        case "flip":
            flipped = data[offset] ^ (1 << rng.randrange(8))
            return data[:offset] + bytes((flipped,)) + data[offset + 1 :]
        case _:
            return data[:offset]


def _survives(data: bytes) -> bool:
    """Whether ``data`` de-encapsulates, having checked everything promised of it.

    Anything other than a :class:`~ottertf.OtteRTFError` propagates out
    of here and fails the calling test, which is the assertion this whole module exists
    to make.
    """
    # Recognition is lenient by default, so this never raises at all: a caller has to be
    # able to ask what a stream holds before deciding what to do with it.
    detect_content_type(data)

    try:
        lenient = deencapsulate(data)
    except OtteRTFError:
        # Strict is only ever allowed to raise more, so there is nothing left to check.
        with pytest.raises(OtteRTFError):
            deencapsulate(data, strict=True)
        return False

    assert lenient.content_type in (ContentType.HTML, ContentType.TEXT), data
    assert (lenient.html is None) != (lenient.text is None), data
    # The output has to survive being written out, which is the only thing a caller is
    # certain to do with it. A lone surrogate would raise here rather than at their end.
    assert isinstance(lenient.body.encode("utf-8"), bytes)

    try:
        strict = deencapsulate(data, strict=True)
    except OtteRTFError:
        return True
    assert strict.body == lenient.body, data
    return True


# --- Random input ---


@pytest.mark.parametrize(
    "generator", [_random_bytes, _token_salad], ids=["random-bytes", "token-salad"]
)
def test_random_input_stays_inside_the_contract(
    generator: Callable[[random.Random], bytes],
) -> None:
    rng = random.Random(SEED)
    survived = 0
    for _ in range(RANDOM_CASES):
        if _survives(HEADER + generator(rng)):
            survived += 1
    assert survived, "no random case reached the end of the reader"


def test_a_document_of_nothing_but_the_header_is_handled() -> None:
    """The degenerate case the generators above can only produce by chance."""
    assert deencapsulate(HEADER).body == ""


# --- Mutated golden documents ---


@pytest.mark.parametrize("name", GOLDEN_DOCUMENTS)
def test_mutating_a_golden_document_stays_inside_the_contract(name: str) -> None:
    """A golden document is valid input, so a single corrupted byte in one is the
    closest thing to the damage a truncated or badly decompressed stream does."""
    original = read_bytes(f"{name}.rtf")
    rng = random.Random(SEED)
    survived = 0
    for _ in range(MUTATIONS):
        if _survives(_mutate(rng, original)):
            survived += 1
    assert survived, f"every mutation of {name} was rejected"


@pytest.mark.parametrize("name", GOLDEN_DOCUMENTS)
def test_truncating_a_golden_document_anywhere_stays_inside_the_contract(
    name: str,
) -> None:
    """Every prefix, not a sample of them.

    A truncation is what a caller gets from a stream that was cut short, and the offsets
    that matter -- mid control word, mid ``\\binN`` payload, mid hex escape -- are only a
    few bytes wide, so sampling would step over them.
    """
    original = read_bytes(f"{name}.rtf")
    for length in range(len(original) + 1):
        _survives(original[:length])
