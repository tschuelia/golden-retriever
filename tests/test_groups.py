"""Tests for group scoping and destination classification.

Two things are being pinned here. One is that state inherits into a group and is
restored when it closes, which is the whole reason the driver keeps a stack. The
other is the content of :data:`NON_VISIBLE_DESTINATIONS`, which is the one table in
this package where a wrong entry loses a document's text silently instead of
failing.
"""

import pytest

from ottertf.groups import (
    DEFAULT_UC_SKIP,
    NON_VISIBLE_DESTINATIONS,
    Destination,
    Frame,
    GroupStack,
    classify_destination,
)


def test_a_new_frame_starts_at_the_document_defaults() -> None:
    frame = Frame()
    assert frame.dest is Destination.NORMAL
    assert frame.font_id is None
    assert frame.uc_skip == DEFAULT_UC_SKIP == 1
    assert not frame.htmlrtf
    assert frame.expecting_destination
    assert not frame.ignorable


def test_a_copy_carries_the_scoped_state() -> None:
    frame = Frame(dest=Destination.HTMLTAG, font_id=3, uc_skip=2, htmlrtf=True)
    assert frame.copy() == Frame(
        dest=Destination.HTMLTAG, font_id=3, uc_skip=2, htmlrtf=True
    )


def test_a_copy_does_not_carry_the_position_within_a_group() -> None:
    """A nested group may declare a destination of its own, so both of these reset."""
    frame = Frame(expecting_destination=False, ignorable=True)
    copy = frame.copy()
    assert copy.expecting_destination
    assert not copy.ignorable


def test_state_transfers_on_entry_and_is_restored_on_exit() -> None:
    """MS-OXRTFEX 2.1.3.1.3: the HTMLRTF state "MUST transfer when entering groups and
    be restored when exiting groups".

    Its own illustration is ``\\b bold { bold \\b0 non-bold } bold``, which is this
    sequence with suppression in place of bold.
    """
    stack = GroupStack()
    stack.top.htmlrtf = True

    inner = stack.push()
    assert inner.htmlrtf
    inner.htmlrtf = False
    assert not stack.top.htmlrtf

    stack.pop()
    assert stack.top.htmlrtf


def test_the_font_and_the_skip_count_are_scoped_the_same_way() -> None:
    """RTF 1.9.1: a ``\\ucN`` value applies to its group, and "when leaving an RTF group
    that specified a ``\\ucN`` value, the reader must revert to the previous value"."""
    stack = GroupStack()
    stack.top.font_id = 1
    stack.top.uc_skip = 1

    stack.push()
    stack.top.font_id = 7
    stack.top.uc_skip = 3
    stack.push()
    assert stack.top.font_id == 7
    assert stack.top.uc_skip == 3

    stack.pop()
    stack.pop()
    assert stack.top.font_id == 1
    assert stack.top.uc_skip == 1


def test_depth_counts_the_open_groups() -> None:
    """One at the start: a document with no braces still has state to keep."""
    stack = GroupStack()
    assert stack.depth == 1
    stack.push()
    stack.push()
    assert stack.depth == 3
    stack.pop()
    assert stack.depth == 2


def test_a_stray_group_end_is_recorded_and_survivable() -> None:
    """A document with more ``}`` than ``{`` is malformed, and the rest of it is still
    worth reading, so the outermost frame is never discarded."""
    stack = GroupStack()
    assert not stack.underflowed

    stack.pop()
    assert stack.underflowed
    assert stack.depth == 1

    stack.top.font_id = 4
    stack.push()
    assert stack.top.font_id == 4


def test_entering_an_htmltag_destination_clears_suppression() -> None:
    """A documented deviation.

    MS-OXRTFEX 2.2.3.2 scopes the HTMLRTF skipping rule to content "outside of an
    HTMLTAG destination group" and requires CONTENT fragments to be copied, so a
    producer that leaves ``\\htmlrtf1`` on around a tag it did write must not have that
    tag deleted.
    """
    frame = Frame(htmlrtf=True)
    frame.enter(Destination.HTMLTAG)
    assert frame.dest is Destination.HTMLTAG
    assert not frame.htmlrtf


@pytest.mark.parametrize(
    "dest", [Destination.SKIP, Destination.FONTTBL, Destination.NORMAL]
)
def test_entering_any_other_destination_leaves_suppression_alone(
    dest: Destination,
) -> None:
    frame = Frame(htmlrtf=True)
    frame.enter(dest)
    assert frame.dest is dest
    assert frame.htmlrtf


@pytest.mark.parametrize("ignorable", [False, True])
def test_htmltag_is_the_exception_to_the_ignorable_rule(ignorable: bool) -> None:
    """MS-OXRTFEX 2.2.3.2: ignore ignorable destination groups "other than the HTMLTAG
    destination group".

    Accepted without the ``\\*`` too, though 2.1.3.1.4's ABNF includes it: a producer
    that omitted it has still written a tag, and treating it as body content would put
    RTF markup in the output.
    """
    assert classify_destination("htmltag", ignorable=ignorable) is Destination.HTMLTAG


@pytest.mark.parametrize("ignorable", [False, True])
def test_the_font_table_is_never_skipped(ignorable: bool) -> None:
    """MS-OXRTFEX 2.2.3.2: skip non-visible destinations "except for the \\fonttbl
    group"."""
    assert classify_destination("fonttbl", ignorable=ignorable) is Destination.FONTTBL


@pytest.mark.parametrize("name", sorted(NON_VISIBLE_DESTINATIONS))
def test_every_non_visible_destination_is_skipped_without_a_star(name: str) -> None:
    """These are the ones a producer writes without ``\\*``, which is the only reason
    they need naming at all."""
    assert classify_destination(name, ignorable=False) is Destination.SKIP


def test_an_unrecognized_word_is_skipped_only_when_the_group_is_ignorable() -> None:
    """``{\\*\\generator ...}`` needs no entry in the table; the ``\\*`` does the
    work."""
    assert classify_destination("generator", ignorable=True) is Destination.SKIP
    assert classify_destination("generator", ignorable=False) is None


@pytest.mark.parametrize("name", ["b", "f", "pard", "fs", "par", "rtf", "ansicpg"])
def test_an_ordinary_control_word_names_no_destination(name: str) -> None:
    """``None`` means the group keeps whatever destination it inherited."""
    assert classify_destination(name, ignorable=False) is None


@pytest.mark.parametrize(
    "name",
    [
        "field",
        "fldrslt",
        "object",
        "result",
        "header",
        "footer",
        "headerl",
        "footerf",
        "upr",
        "shptxt",
    ],
)
def test_destinations_that_carry_visible_text_are_not_skipped(name: str) -> None:
    """The regression that matters most: each of these produces text a reader must
    keep, and skipping one would delete content with nothing to show it existed.

    ``\\field`` and ``\\object`` keep their visible halves (``\\fldrslt``, ``\\result``)
    while their instruction and payload halves are ``{\\*\\fldinst ...}`` and
    ``{\\*\\objdata ...}``, which the ``\\*`` rule skips. ``\\upr`` holds the same text
    twice and relies on that rule to drop exactly one copy.
    """
    assert name not in NON_VISIBLE_DESTINATIONS
    assert classify_destination(name, ignorable=False) is None


def test_the_skip_set_is_keyed_the_way_the_tokenizer_reports_names() -> None:
    """A name carrying a backslash, or any uppercase, would never match."""
    assert all(
        name == name.lower() and name.isalpha() for name in NON_VISIBLE_DESTINATIONS
    )
