"""Group scoping, and which destinations produce visible text.

Why a stack of copies
=====================

RTF state is scoped by groups, so ``{`` pushes a copy of the enclosing frame and
``}`` pops it. That single rule satisfies three separate requirements at once:

- MS-OXRTFEX 2.1.3.1.3: "The state of the HTMLRTF control word MUST transfer when
  entering groups and be restored when exiting groups".
- RTF 1.9.1 (Unicode RTF): a ``\\ucN`` keyword's values "are scoped like character
  properties", and "when leaving an RTF group that specified a ``\\ucN`` value, the
  reader must revert to the previous value".
- The current font, whose code page decides how the following text bytes decode.

Copying on entry is what makes all three automatic rather than three separate
save-and-restore paths, each with its own chance of an unbalanced restore.

Destinations
============

MS-OXRTFEX 2.2.3.2 gives two rules for what to leave out, and both are about
groups rather than individual control words:

- "Ignore and skip any standard RTF destination groups that do not produce visible
  text (such as \\colortbl groups), except for the \\fonttbl group. The
  de-encapsulating RTF reader SHOULD process a font table group and at least
  remember the code page that corresponds to each font."
- "Ignore any ignorable destination groups (that is, groups that start with "\\*")
  other than the HTMLTAG destination group."

The second rule carries most of the weight. Everything a producer marks ``\\*`` is
skipped without this module needing to know what it was, which is what keeps
:data:`NON_VISIBLE_DESTINATIONS` short.

Keeping that set short is the point. It is the one place in this package where a
wrong entry causes *silent content loss* rather than a crash: an extra name means
a document's text disappears with nothing to show that it ever existed. So it
holds only destinations that a specification names as carrying no visible text,
and that real documents write without a ``\\*`` prefix. Anything else is left to
the ``\\*`` rule, which errs the safe way -- text is kept.

Deliberately absent
===================

- **``\\field``.** Its ``\\fldrslt`` subgroup is the field's visible result, and it
  is ordinary body content. The instruction half is ``{\\*\\fldinst ...}``, which
  the ``\\*`` rule already skips.
- **``\\object``.** Same shape: ``{\\*\\objdata ...}`` is the binary payload and is
  ignorable, while ``\\result`` holds the visible rendering.
- **``\\header`` and ``\\footer``.** Page furniture does produce visible text, so
  the rule quoted above does not reach it.
- **``\\upr``.** RTF 1.9.1 gives it two subgroups holding the same text twice, the
  second as ``{\\*\\ud ...}``. Leaving ``\\upr`` out of the set means the ``\\*``
  rule drops exactly one of the two, which is the wanted outcome; naming it here
  would drop both.
"""

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "DEFAULT_UC_SKIP",
    "FONTTBL_WORD",
    "HTMLTAG_WORD",
    "IGNORABLE_SYMBOL",
    "NON_VISIBLE_DESTINATIONS",
    "Destination",
    "Frame",
    "GroupStack",
    "classify_destination",
]

DEFAULT_UC_SKIP = 1
"""RTF 1.9.1: "a default of 1 should be assumed if no ``\\ucN`` keyword has been
seen"."""

FONTTBL_WORD = "fonttbl"
"""The one non-visible destination MS-OXRTFEX 2.2.3.2 requires a reader to process."""

HTMLTAG_WORD = "htmltag"
"""MS-OXRTFEX 2.1.3.1.4: ``HTMLTAG = %x5C.2A.5C.68.74.6D.6C.74.61.67``."""

IGNORABLE_SYMBOL = "*"
"""The control symbol marking "groups that start with "\\*"" (MS-OXRTFEX 2.2.3.2)."""

NON_VISIBLE_DESTINATIONS = frozenset(
    {
        # The header tables of RTF 1.9.1's document area. None of them is text:
        # each is a numbered table the body refers to by index. MS-OXRTFEX 2.2.3.2
        # names \colortbl as its example of the class.
        "colortbl",
        "filetbl",
        "listoverridetable",
        "listtable",
        "revtbl",
        "rsidtbl",
        "stylesheet",
        # RTF 1.9.1 (Information Group): document metadata -- title, author,
        # keywords and the rest. Real text, but never part of the message body.
        "info",
        # RTF 1.9.1 (Pictures): picture data, written as hexadecimal digits when
        # it is not a \binN payload. Those digits are TEXT tokens, so this entry
        # is what stops an image from arriving as a run of hex.
        "pict",
        # MS-OXRTFEX 2.1.3.1.5, on the MHTMLTAG destination group: "This RTF
        # control word SHOULD be skipped on de-encapsulation". Note <8> gives the
        # reason -- its content "is also encapsulated in another HTMLTAG
        # destination group; thus, an MHTMLTAG destination group can be safely
        # ignored".
        "mhtmltag",
    }
)
"""Destination control words whose groups carry no visible text.

Short by design; see this module's docstring for what is deliberately not in it and why.
A name here suppresses the whole group, including nested groups.
"""


class Destination(StrEnum):
    """What kind of destination a group is in.

    The values are strings so that a failed assertion names the destination as the RTF
    spells it.
    """

    NORMAL = "normal"
    """Ordinary body content, to be de-encapsulated."""

    HTMLTAG = "htmltag"
    """An HTMLTAG destination group, whose CONTENT is copied out verbatim."""

    FONTTBL = "fonttbl"
    """The font table, read for its code pages but not copied out."""

    SKIP = "skip"
    """A group producing no visible text, to be ignored in full."""


@dataclass(slots=True)
class Frame:
    """The scoped state of one group.

    Mutable, and internal to the package: a driver mutates the top frame in place as
    it reads control words, and :meth:`copy` is what makes that safe across group
    boundaries.
    """

    dest: Destination = Destination.NORMAL
    """Which destination this group is in, inherited unless it declared its own."""

    font_id: int | None = None
    """The ``N`` of the ``\\fN`` in effect, or ``None`` for the document default."""

    uc_skip: int = DEFAULT_UC_SKIP
    """The ``N`` of ``\\ucN``: how many characters follow a ``\\uN`` to be discarded."""

    htmlrtf: bool = False
    """Whether ``\\htmlrtf`` is suppressing output (MS-OXRTFEX 2.1.3.1.3)."""

    expecting_destination: bool = True
    """Whether a destination control word may still appear.

    RTF 1.9.1 requires a destination control word to be the first item in its group, so
    this is true only until the group's first control word or text.
    """

    ignorable: bool = False
    """Whether this group opened with ``\\*``."""

    def copy(self) -> "Frame":
        """The frame a nested group starts from.

        Only the scoped character state is carried over. :attr:`expecting_destination`
        and :attr:`ignorable` describe a position within one group's token sequence
        rather than state to inherit, so they return to their defaults -- which is
        exactly right, because the nested group may declare a destination of its own.
        """
        return Frame(
            dest=self.dest,
            font_id=self.font_id,
            uc_skip=self.uc_skip,
            htmlrtf=self.htmlrtf,
        )

    def enter(self, dest: Destination) -> None:
        """Record that this group declared ``dest``.

        Entering an HTMLTAG destination clears HTMLRTF suppression for the group.
        MS-OXRTFEX 2.2.3.2 scopes the HTMLRTF rule to content "outside of an HTMLTAG
        destination group", and requires CONTENT fragments to be copied
        unconditionally -- so a producer that leaves ``\\htmlrtf1`` on around a tag it
        did write must not delete that tag. This is a documented deviation: read
        literally, nothing says to clear it.
        """
        self.dest = dest
        if dest is Destination.HTMLTAG:
            self.htmlrtf = False


class GroupStack:
    """The open groups, innermost last.

    Never empty: a document with more ``}`` than ``{`` is malformed, and answering
    with the outermost frame keeps the rest of it readable. :attr:`underflowed`
    records that it happened.
    """

    __slots__ = ("_frames", "underflowed")

    def __init__(self) -> None:
        self._frames: list[Frame] = [Frame()]

        self.underflowed = False
        """Whether a ``}`` arrived with no matching ``{``."""

    @property
    def top(self) -> Frame:
        """The innermost open group's frame."""
        return self._frames[-1]

    @property
    def depth(self) -> int:
        """How many groups are open.

        One for a document with no braces at all.
        """
        return len(self._frames)

    def push(self) -> Frame:
        """Open a group, and return its frame."""
        frame = self._frames[-1].copy()
        self._frames.append(frame)
        return frame

    def pop(self) -> Frame:
        """Close a group, and return the frame it had.

        A stray ``}`` sets :attr:`underflowed` and returns the outermost frame
        without discarding it.
        """
        if len(self._frames) == 1:
            self.underflowed = True
            return self._frames[0]
        return self._frames.pop()


def classify_destination(name: str, *, ignorable: bool) -> Destination | None:
    """Which destination a group's first control word puts it in.

    ``None`` means the control word names no destination, so the group keeps the one
    it inherited. :attr:`Destination.NORMAL` is never returned: it is where a
    document starts, not somewhere a control word moves it to.

    HTMLTAG is checked before ``ignorable`` because it is the stated exception to the
    ``\\*`` rule -- "other than the HTMLTAG destination group". MS-OXRTFEX
    2.1.3.1.4 requires the prefix. Accepting the group without it is a project
    recovery policy: a producer that omits it has still written a tag, and treating
    that as body text would emit RTF markup into the output.

    :param name: A control word name, without its backslash.
    :param ignorable: Whether ``\\*`` opened this group.
    """
    if name == HTMLTAG_WORD:
        return Destination.HTMLTAG
    if name == FONTTBL_WORD:
        return Destination.FONTTBL
    if name in NON_VISIBLE_DESTINATIONS:
        return Destination.SKIP
    if ignorable:
        return Destination.SKIP
    return None
