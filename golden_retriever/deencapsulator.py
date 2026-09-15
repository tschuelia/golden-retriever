"""De-encapsulating HTML and plain text (MS-OXRTFEX 2.2.3.2 and 2.2.3.3).

One reader, two outputs
=======================

The two algorithms are one reader. MS-OXRTFEX 2.2.3.3 asks for every control token to
be translated to "its textual equivalent" with "any RTF formatting control words that
do not have a textual representation" ignored, ``\\par`` and ``\\line`` becoming CRLF
and ``\\tab`` a horizontal tab. 2.2.3.2 asks for exactly the same thing outside HTMLTAG
destination groups, and adds rules for what is inside them. So the two differ in which
content type the result carries and in HTMLTAG handling, and share everything else.

Neither is a transformation of the input: content is *emitted*, never deleted. Anything
suppressed is simply never handed to the emitter, so there is no pass that could delete
a byte in a visible run because an identical byte occurred in a hidden one.

What suppression suppresses
===========================

MS-OXRTFEX 2.1.3.1.3 makes ``\\htmlrtf`` a toggle: while it is enabled the reader "MUST
NOT copy any subsequent text and control words in the RTF content until the state is
disabled". 2.2.3.2 states one exception -- "Ignore and skip any text and RTF control
words that are suppressed by any HTMLRTF control word other than the \\fN control word.
The de-encapsulating RTF reader SHOULD track the current font even when the
corresponding \\fN control word is inside of a fragment that is disabled with an HTMLRTF
control word."

Suppression therefore stops *output*, not bookkeeping. This reader extends the stated
``\\fN`` exception to the other control words that copy nothing and only carry state:
``\\ucN``, ``\\ansicpgN``, ``\\deffN``, and a group's destination -- including
``{\\fonttbl...}``, which 2.2.3.2 requires a reader to process. Reading them costs
nothing and losing one of them mojibakes or duplicates content that was never
suppressed at all.

Inside an HTMLTAG destination
=============================

MS-OXRTFEX 2.1.3.1.4 gives the group as ``"{" HTMLTAG [HTMLTagParameter] DELIMITER
CONTENT "}"``, and 2.1.3.1.4.2 makes CONTENT "a fragment of the original HTML content".
Three things follow, each done in one place below:

- The ``HTMLTagParameter`` is part of the control word, so it never reaches the output.
  The scanner has consumed the DELIMITER space already; a second space belongs to the
  fragment.
- The character table is the one in 2.1.3.1.4.2, not the RTF 1.9.1 Special Characters
  table. The two disagree about ``\\_``, and a control word the CONTENT table omits
  produces nothing.
- Text bytes decode in "the default code page, as specified in the RTF header"
  (MS-OXRTFEX 2.2.3.2) whatever ``\\fN`` is in effect. A tag is markup the producer
  wrote; the fonts describe how to render the message, not how its tags were spelled.

A nested group inherits the destination like every other frame field, so a producer that
wraps part of a fragment in a group gets the same three rules inside it.

Skippable data after ``\\uN``
=============================

RTF 1.9.1 (Unicode RTF) has a ``\\uN`` escape "followed immediately by equivalent
character(s) in ANSI representation", so that "old readers will ignore the ``\\uN``
keyword and pick up the ANSI representation properly": a reader that understood ``\\uN``
"should ignore the next N' characters, where N' corresponds to the last ``\\ucN'`` value
encountered". Three of its counting rules are easy to get wrong, and each is one line
below:

- "Any RTF control word or symbol is considered a single character", however many bytes
  it occupies -- and "a ``\\binN`` keyword, its argument, and the binary data that
  follows are considered one character".
- "A keyword-terminating space may be present (before the ANSI characters) that is not
  counted in the characters to skip". The scanner consumes that space already.
- "If an RTF scope delimiter character (that is, an opening or closing brace) is
  encountered while scanning skippable data, the skippable data is considered to end
  before the delimiter."

A control word inside skippable data still has its state applied here, for the same
reason as above, while its output is dropped and it still counts as one skipped
character. Counting it is what matters: a producer that emitted no ANSI representation
at all would otherwise have a real character of the following text eaten.

One control word is exempt, which is a deviation: a ``\\uN`` cancels a skip in progress
rather than being counted by it. Skippable data is by definition an *ANSI*
representation, and a ``\\uN`` is not one -- it is a character with no other spelling in
the document, so counting it deletes content. It is also what makes a surrogate pair
written as ``\\u-10179\\u-8704``, with no ANSI representation between the halves, arrive
as a pair rather than as one half and a discarded control word.

Strictness
==========

Every problem is recorded as a :class:`~golden_retriever.Diagnostic`. With
``strict=True`` the structural subset of them -- the ones in :data:`_STRICT_ERRORS`,
which describe damage to the document rather than to its content -- is raised instead,
at the point it is found. Both modes take the same path and produce the same characters
up to that point; ``strict`` only decides whether the reader stops.
"""

import logging
from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType

from golden_retriever.charmap import BODY_CHARMAP, HTMLTAG_CHARMAP, CharMap
from golden_retriever.codepages import encoding_for_codepage
from golden_retriever.detect import (
    DEFAULT_HEADER_TOKEN_LIMIT,
    RTF_HEADING,
    detect_content_type,
    has_rtf_heading,
)
from golden_retriever.emitter import Emitter
from golden_retriever.exceptions import (
    GoldenRetrieverError,
    MalformedRtfError,
    MissingFontTableError,
    NotEncapsulatedRtfError,
    UnsupportedCodePageError,
)
from golden_retriever.fonts import FONT_WORD, FontEntry, parse_font_table, resolve_fonts
from golden_retriever.groups import (
    IGNORABLE_SYMBOL,
    Destination,
    Frame,
    GroupStack,
    classify_destination,
)
from golden_retriever.html_meta import declared_charset
from golden_retriever.result import (
    ContentType,
    DeEncapsulationResult,
    Diagnostic,
    DiagnosticCode,
    FontInfo,
)
from golden_retriever.tokenizer import Token, TokenKind, tokenize

__all__ = ["DEFAULT_FALLBACK_CODEPAGE", "deencapsulate"]

DEFAULT_FALLBACK_CODEPAGE = 1252
"""Code page assumed when the document declares no usable ``\\ansicpgN``.

Windows-1252 is what Outlook writes for western-European locales and is the least
damaging guess: its printable range agrees with Latin-1 and ASCII.
"""

_LOGGER = logging.getLogger(__name__)

_ANSICPG_WORD = "ansicpg"
"""``\\ansicpgN``: the document's code page, i.e. "the default code page, as specified
in the RTF header" (MS-OXRTFEX 2.2.3.2)."""

_DEFAULT_FONT_WORD = "deff"
"""``\\deffN``: which font applies to text that no ``\\fN`` has claimed."""

_HTMLRTF_WORD = "htmlrtf"
"""MS-OXRTFEX 2.1.3.1.3: ``HTMLRTF = %x5C.68.74.6D.6C.72.74.66["0" / "1"]``."""

_UNICODE_WORD = "u"
"""``\\uN``: one Unicode character, "expressed as a decimal number" (RTF 1.9.1)."""

_UNICODE_SKIP_WORD = "uc"
"""``\\ucN``: how many characters of ANSI representation follow a ``\\uN``."""

_TOGGLE_OFF = 0
"""The parameter that disables a toggle control word, as ``\\htmlrtf0`` does."""

_STRICT_ERRORS: Mapping[str, type[GoldenRetrieverError]] = MappingProxyType(
    {
        # Structural damage: something is wrong with the document rather than with
        # the content it carries. Under strict these stop the read.
        DiagnosticCode.MISSING_RTF_MAGIC: MalformedRtfError,
        DiagnosticCode.UNPREFIXED_HTMLTAG: MalformedRtfError,
        DiagnosticCode.UNBALANCED_GROUPS: MalformedRtfError,
        DiagnosticCode.TRUNCATED_BIN: MalformedRtfError,
        DiagnosticCode.MISSING_FONT_TABLE: MissingFontTableError,
        DiagnosticCode.UNSUPPORTED_CODEPAGE: UnsupportedCodePageError,
    }
)
"""Which diagnostics ``strict=True`` raises, and as what.

Every other code describes damage *inside* the document -- an unknown font, bytes their
code page does not define, a surrogate with no partner -- which a stricter caller still
cannot do anything about, so it never escalates.
"""


class _Diagnostics:
    """The problems found so far, or the first one that ``strict`` refuses to tolerate.

    Raising as soon as a structural problem is found is what keeps the two modes
    producing the same characters: they follow the same path until one of them stops.
    """

    __slots__ = ("_items", "_strict")

    def __init__(self, *, strict: bool) -> None:
        self._items: list[Diagnostic] = []
        self._strict = strict

    def add(self, code: DiagnosticCode, message: str) -> None:
        """Record a problem, or raise it under ``strict``."""
        if self._strict:
            error = _STRICT_ERRORS.get(code)
            if error is not None:
                raise error(message)
        self._items.append(Diagnostic(code, message))

    def extend(self, diagnostics: Iterable[Diagnostic]) -> None:
        """Record problems another module found, escalating them the same way."""
        for diagnostic in diagnostics:
            self.add(DiagnosticCode(diagnostic.code), diagnostic.message)

    def collected(self) -> tuple[Diagnostic, ...]:
        """Everything recorded, in the order it was found."""
        return tuple(self._items)


class _Reader:
    """The de-encapsulating RTF reader, over one document's tokens.

    ``run`` makes the single pass. Everything the caller needs afterwards is on the
    three public attributes, and none of it is decoded: which code page applies is
    settled after the pass, by :func:`resolve_fonts` and :meth:`Emitter.resolve`.
    """

    __slots__ = (
        "_default_font",
        "_diagnostics",
        "_pending_skip",
        "_saw_font_table",
        "_saw_unprefixed_htmltag",
        "_skip_from_depth",
        "_stack",
        "_tokens",
        "codepage",
        "emitter",
        "font_entries",
    )

    def __init__(self, tokens: Iterator[Token], diagnostics: _Diagnostics) -> None:
        self._tokens = tokens
        self._diagnostics = diagnostics
        self._stack = GroupStack()
        # The group depth a skipped destination began at, or None. Nothing inside it
        # is read, so no nested group can classify its way back out.
        self._skip_from_depth: int | None = None
        self._pending_skip = 0
        self._default_font: int | None = None
        self._saw_font_table = False
        self._saw_unprefixed_htmltag = False

        self.emitter = Emitter()
        """What the document produced, still undecoded."""

        self.font_entries: dict[int, FontEntry] = {}
        """The font table as written, keyed by ``\\fN`` identifier."""

        self.codepage: int | None = None
        """The ``N`` of the document's first ``\\ansicpgN``, or ``None``."""

    def run(self) -> None:
        """Read the document, then record what its structure got wrong."""
        stack = self._stack
        for token in self._tokens:
            kind = token.kind

            if kind is TokenKind.GROUP_START:
                # "The skippable data is considered to end before the delimiter."
                self._pending_skip = 0
                stack.push()
                continue

            if kind is TokenKind.GROUP_END:
                self._pending_skip = 0
                stack.pop()
                if (
                    self._skip_from_depth is not None
                    and stack.depth < self._skip_from_depth
                ):
                    self._skip_from_depth = None
                continue

            if kind is TokenKind.BINARY:
                # Never content, in any destination -- but a payload that ran off the
                # end is structural damage worth reporting even inside a skipped
                # destination, which is where \binN actually occurs.
                if token.param is not None and token.param > len(token.data):
                    self._diagnostics.add(
                        DiagnosticCode.TRUNCATED_BIN,
                        f"a \\bin{token.param} payload ran past the end of the "
                        f"document with {len(token.data)} byte(s) present",
                    )
                self._count_skipped()
                continue

            if self._skip_from_depth is not None:
                continue

            frame = stack.top

            if kind is TokenKind.WORD:
                if frame.expecting_destination and self._enter_destination(
                    frame, token
                ):
                    continue
                self._word(frame, token)
                continue

            if kind is TokenKind.SYMBOL:
                if frame.expecting_destination:
                    if token.name == IGNORABLE_SYMBOL:
                        # The destination control word this marks ignorable is the
                        # next token, so the group's position does not advance.
                        frame.ignorable = True
                        continue
                    if self._leave_destination(frame):
                        continue
                if self._count_skipped() or frame.htmlrtf:
                    continue
                text = _charmap(frame).symbols.get(token.name)
                if text is not None:
                    self.emitter.add_text(text)
                continue

            if kind is TokenKind.HEX:
                if frame.expecting_destination and self._leave_destination(frame):
                    continue
                if self._count_skipped() or frame.htmlrtf:
                    continue
                self.emitter.add_bytes(token.data, self._font(frame))
                continue

            # TEXT, the only kind a partly consumed skip can leave something of.
            if frame.expecting_destination and self._leave_destination(frame):
                continue
            data = token.data
            if self._pending_skip:
                consumed = min(self._pending_skip, len(data))
                self._pending_skip -= consumed
                data = data[consumed:]
                if not data:
                    continue
            if not frame.htmlrtf:
                self.emitter.add_bytes(data, self._font(frame))

        self._finish()

    def _enter_destination(self, frame: Frame, token: Token) -> bool:
        """Classify a group's first control word.

        :returns: Whether the token has been dealt with, which it has unless it named no
            destination at all -- every destination control word is framing rather than
            content, so none of them produces a character.
        """
        frame.expecting_destination = False
        dest = classify_destination(token.name, ignorable=frame.ignorable)
        if dest is None:
            return False
        frame.enter(dest)
        if dest is Destination.SKIP:
            self._skip(token.name)
            return True
        if dest is Destination.FONTTBL:
            self._read_font_table()
            return True
        # HTMLTAG, whose CONTENT the rest of the group delivers. The HTMLTagParameter of
        # MS-OXRTFEX 2.1.3.1.4 is this token's parameter and is not part of that
        # content, so it is dropped here rather than read.
        if not frame.ignorable:
            self._report_unprefixed_htmltag()
        return True

    def _report_unprefixed_htmltag(self) -> None:
        """Report an HTMLTAG destination group written without its ``\\*``.

        MS-OXRTFEX 2.1.3.1.4 spells the destination ``\\*\\htmltag``. Reading the
        group anyway is a project recovery policy, not documented Microsoft product
        behavior. Only the deviation from the grammar is reported: treating the
        fragment as body content would emit RTF markup into the output.

        Once per document: a producer that omits the ``\\*`` omits it on every tag, and
        one diagnostic per tag would bury everything else in the list.
        """
        if self._saw_unprefixed_htmltag:
            return
        self._saw_unprefixed_htmltag = True
        self._diagnostics.add(
            DiagnosticCode.UNPREFIXED_HTMLTAG,
            "an HTMLTAG destination group opened with \\htmltag rather than "
            "\\*\\htmltag; its content was de-encapsulated as a tag anyway",
        )

    def _leave_destination(self, frame: Frame) -> bool:
        """Note that this group's first token was not a destination control word.

        :returns: Whether the group is skipped anyway, which it is when ``\\*`` opened
            it: MS-OXRTFEX 2.2.3.2 skips "groups that start with "\\*"" whether or not
            one of the specifications names the destination they went on to declare.
        """
        frame.expecting_destination = False
        if not frame.ignorable:
            return False
        frame.enter(Destination.SKIP)
        self._skip(IGNORABLE_SYMBOL)
        return True

    def _skip(self, name: str) -> None:
        """Stop reading until the group that opened at the current depth closes."""
        _LOGGER.debug("skipping the %s destination group", name)
        self._skip_from_depth = self._stack.depth

    def _count_skipped(self) -> bool:
        """Count one token of ANSI representation against the ``\\uN`` skip.

        :returns: Whether this token was inside skippable data, and so produces nothing.
        """
        if not self._pending_skip:
            return False
        self._pending_skip -= 1
        return True

    def _read_font_table(self) -> None:
        """Read one ``{\\fonttbl...}`` group, entries and all."""
        table = parse_font_table(self._tokens)
        self._saw_font_table = True
        for entry in table.entries:
            self.font_entries[entry.font_id] = entry
        if table.closed:
            # The table's own closing brace was consumed on this reader's behalf, so
            # the frame the opening brace pushed has to come off here. An unclosed
            # table leaves it, which is what reports the document as unbalanced.
            self._stack.pop()

    def _word(self, frame: Frame, token: Token) -> None:
        """Apply one control word: its state always, its output only if it has any."""
        name = token.name
        param = token.param

        if name == _UNICODE_WORD and param is not None:
            # A \uN cancels a skip still in progress instead of being consumed by it.
            # Skippable data is the "equivalent character(s) in ANSI representation" of
            # the escape before it, and a \uN is by definition not an ANSI
            # representation of anything -- it is a character with no other spelling in
            # the document, so counting it would delete content. It is also what makes
            # a surrogate pair written as \u-10179\u-8704, with no ANSI representation
            # between the halves, arrive at the emitter as a pair.
            self._pending_skip = 0
            if not frame.htmlrtf:
                self.emitter.add_unicode(param)
            self._pending_skip = frame.uc_skip
            return

        # RTF 1.9.1: "any RTF control word or symbol is considered a single character
        # for the purposes of counting skippable characters".
        skipped = self._count_skipped()

        if name == _HTMLRTF_WORD:
            # A toggle control word: "\htmlrtf and \htmlrtf1 both represent enabling".
            frame.htmlrtf = param != _TOGGLE_OFF
            return
        if name == FONT_WORD:
            if param is not None:
                frame.font_id = param
            return
        if name == _UNICODE_SKIP_WORD:
            if param is not None and param >= 0:
                frame.uc_skip = param
            return
        if name == _ANSICPG_WORD:
            if param is not None and self.codepage is None:
                self.codepage = param
            return
        if name == _DEFAULT_FONT_WORD:
            if param is not None and self._default_font is None:
                self._default_font = param
            return

        if skipped or frame.htmlrtf:
            return

        text = _charmap(frame).words.get(name)
        if text is not None:
            self.emitter.add_text(text)

    def _font(self, frame: Frame) -> int | None:
        """Which font's code page the bytes of this run belong to.

        ``None`` means the document's own code page. That is where text no ``\\fN`` and
        no ``\\deffN`` has claimed is decoded, and also where the CONTENT of an HTMLTAG
        destination group is decoded whatever font is in effect: a tag is markup the
        producer wrote in "the default code page, as specified in the RTF header"
        (MS-OXRTFEX 2.2.3.2), and the fonts describe how to render the message rather
        than how its tags were spelled.
        """
        if frame.dest is Destination.HTMLTAG:
            return None
        return frame.font_id if frame.font_id is not None else self._default_font

    def _finish(self) -> None:
        """Report what only the end of the document can show."""
        if self._stack.depth > 1 or self._stack.underflowed:
            self._diagnostics.add(
                DiagnosticCode.UNBALANCED_GROUPS,
                f"the document's groups do not balance: {self._stack.depth - 1} "
                f"still open at the end"
                if self._stack.depth > 1
                else "the document closed a group it had not opened",
            )
        if not self._saw_font_table:
            self._diagnostics.add(
                DiagnosticCode.MISSING_FONT_TABLE,
                "the document declares no \\fonttbl, so every text run was decoded "
                "in the document's code page",
            )


def deencapsulate(
    raw_rtf: bytes,
    *,
    strict: bool = False,
    fallback_codepage: int = DEFAULT_FALLBACK_CODEPAGE,
    header_token_limit: int = DEFAULT_HEADER_TOKEN_LIMIT,
) -> DeEncapsulationResult:
    """Extract the HTML or plain text encapsulated in ``raw_rtf``.

    :param raw_rtf: Uncompressed RTF bytes. If the content is stored as
        ``PidTagRtfCompressed``, decompress it first.
    :param strict: Raise on structural damage instead of recording a
        :class:`~golden_retriever.Diagnostic` and carrying on. This never changes which
        characters are produced -- only whether a problem is raised or reported.
    :param fallback_codepage: Code page to assume when the document declares no usable
        ``\\ansicpgN``.
    :param header_token_limit: How many header tokens may precede the ``\\fromhtml1`` /
        ``\\fromtext`` marker.
    :raises golden_retriever.NotEncapsulatedRtfError: The document is native RTF. Call
        :func:`~golden_retriever.detect_content_type` first to avoid this.
    :raises golden_retriever.GoldenRetrieverError: Any other failure. No other exception
        type escapes this function for ``bytes`` input.
    :raises TypeError: ``raw_rtf`` is not ``bytes``.
    :raises ValueError: ``fallback_codepage`` names a code page with no decoder.
    :returns: The decoded body, resolved encoding/font metadata, and any recoverable
        diagnostics. Exactly one of :attr:`~golden_retriever.DeEncapsulationResult.html`
        and :attr:`~golden_retriever.DeEncapsulationResult.text` is populated.
    """
    if not isinstance(raw_rtf, bytes):
        raise TypeError(f"raw_rtf must be bytes, not {type(raw_rtf).__name__}")
    fallback_encoding = encoding_for_codepage(fallback_codepage)
    if fallback_encoding is None:
        raise ValueError(
            f"fallback_codepage={fallback_codepage} has no decoder available"
        )

    content_type = detect_content_type(raw_rtf, header_token_limit=header_token_limit)
    if content_type is ContentType.NATIVE_RTF:
        raise NotEncapsulatedRtfError(
            "the document header carries neither \\fromhtml1 nor \\fromtext within its "
            f"first {header_token_limit} tokens, so it encapsulates nothing "
            "(MS-OXRTFEX 2.2.3.1)"
        )

    diagnostics = _Diagnostics(strict=strict)
    if not has_rtf_heading(raw_rtf):
        # MS-OXRTFEX A<13>: implementations "ignore the absence of the \rtf1 keyword
        # at the beginning of the RTF encoded text and try to de-encapsulate the text
        # anyway", so this is reported rather than refused.
        diagnostics.add(
            DiagnosticCode.MISSING_RTF_MAGIC,
            f"the document does not start with {RTF_HEADING.decode('ascii')}",
        )

    reader = _Reader(tokenize(raw_rtf), diagnostics)
    reader.run()

    document_encoding = fallback_encoding
    if reader.codepage is not None:
        named = encoding_for_codepage(reader.codepage)
        if named is None:
            diagnostics.add(
                DiagnosticCode.UNSUPPORTED_CODEPAGE,
                f"the document declares \\ansicpg{reader.codepage}, which has no "
                f"decoder; code page {fallback_codepage} was used instead",
            )
        else:
            document_encoding = named

    fonts, font_diagnostics = resolve_fonts(
        reader.font_entries.values(), document_encoding=document_encoding
    )
    diagnostics.extend(font_diagnostics)

    emitted = reader.emitter.resolve(
        font_encodings=_font_encodings(fonts), document_encoding=document_encoding
    )
    diagnostics.extend(emitted.diagnostics)

    is_html = content_type is ContentType.HTML
    return DeEncapsulationResult(
        content_type=content_type,
        html=emitted.text if is_html else None,
        text=None if is_html else emitted.text,
        document_codepage=reader.codepage,
        document_encoding=document_encoding,
        # Reported rather than acted on: the charset a producer declared describes the
        # bytes it encapsulated, and those are already decoded by the time this runs.
        # Plain text declares nothing, so there is nothing to look for there.
        declared_html_charset=declared_charset(emitted.text) if is_html else None,
        fonts=fonts,
        diagnostics=diagnostics.collected(),
    )


def _charmap(frame: Frame) -> CharMap:
    """Which character table a control word or symbol is read against here.

    MS-OXRTFEX 2.1.3.1.4.2 enumerates what a CONTENT fragment may contain, and that is
    not the RTF 1.9.1 Special Characters table: the two disagree about ``\\_``, and a
    control word the CONTENT table omits stands for nothing inside a tag.
    """
    return HTMLTAG_CHARMAP if frame.dest is Destination.HTMLTAG else BODY_CHARMAP


def _font_encodings(fonts: Mapping[int, FontInfo]) -> Mapping[int, str]:
    """The codec per ``\\fN`` identifier, which is all the emitter needs of a font."""
    return {font_id: info.encoding for font_id, info in fonts.items()}
