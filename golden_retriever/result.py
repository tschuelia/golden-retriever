"""Public result types returned by :func:`golden_retriever.deencapsulate`."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from golden_retriever.exceptions import GoldenRetrieverError

__all__ = [
    "ContentType",
    "DeEncapsulationResult",
    "Diagnostic",
    "DiagnosticCode",
    "FontInfo",
]


class ContentType(StrEnum):
    """What a document turned out to contain.

    ``NATIVE_RTF`` is only ever returned by
    :func:`golden_retriever.detect_content_type`; a
    :class:`DeEncapsulationResult` never carries it, because de-encapsulating
    native RTF raises
    :class:`golden_retriever.NotEncapsulatedRtfError` instead.
    """

    HTML = "html"
    """Encapsulated HTML: the document header carries ``\\fromhtml1``."""

    TEXT = "text"
    """Encapsulated plain text: the document header carries ``\\fromtext``."""

    NATIVE_RTF = "native-rtf"
    """Ordinary RTF with nothing encapsulated in it."""


class DiagnosticCode(StrEnum):
    """Stable identifiers for the problems recorded in a result.

    These are plain strings, so they compare equal to their literal spelling and can be
    logged or serialized directly. Codes are only ever added, never renamed.
    """

    MISSING_RTF_MAGIC = "missing-rtf-magic"
    """The document does not start with ``{\\rtf1`` (MS-OXRTFEX A<13>)."""

    UNBALANCED_GROUPS = "unbalanced-groups"
    """Groups were still open at end of input, or a stray ``}`` was found."""

    TRUNCATED_BIN = "truncated-bin"
    """A ``\\binN`` payload claimed more bytes than the document contained."""

    MISSING_FONT_TABLE = "missing-font-table"
    """The document declares no ``\\fonttbl``."""

    UNSUPPORTED_CODEPAGE = "unsupported-codepage"
    """A named code page has no decoder available; a fallback was used."""

    UNKNOWN_FONT = "unknown-font"
    """``\\fN`` referenced a font that the font table does not define."""

    UNDECODABLE_BYTES = "undecodable-bytes"
    """Bytes were not valid in their code page and became U+FFFD."""

    UNPAIRED_SURROGATE = "unpaired-surrogate"
    """A ``\\uN`` surrogate had no partner and became U+FFFD."""

    SYMBOL_FONT_CHARSET = "symbol-font-charset"
    """A font declared ``\\fcharset2`` (Symbol), which has no code page."""

    SKIPPED_DESTINATION = "skipped-destination"
    """A non-visible destination group was skipped."""


@dataclass(frozen=True, slots=True)
class FontInfo:
    """One entry of the document's ``\\fonttbl``.

    Exposed mainly for diagnosing mojibake: ``encoding`` is the codec that text
    tagged with this font was actually decoded with, after ``\\fcharset``,
    ``\\cpg`` and the document default have all been resolved.
    """

    font_id: int
    """The ``N`` in ``\\fN``."""

    name: str | None
    """The font name, or ``None`` if the entry declared none."""

    charset: int | None
    """The ``N`` in ``\\fcharsetN``, as declared."""

    codepage: int | None
    """The resolved Windows code page, or ``None`` if the document default applies."""

    encoding: str
    """The Python codec name actually used to decode text in this font."""


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A problem encountered while de-encapsulating, which did not stop it.

    With ``strict=True`` the structural subset of these is raised as an exception
    instead. See :class:`golden_retriever.MalformedRtfError`.
    """

    code: str
    """A :class:`DiagnosticCode` value."""

    message: str
    """A human-readable description, including relevant values."""


@dataclass(frozen=True, slots=True)
class DeEncapsulationResult:
    """The outcome of a successful de-encapsulation.

    Exactly one of :attr:`html` and :attr:`text` is set, matching :attr:`content_type`.
    Use :attr:`body` to get whichever it is.
    """

    content_type: ContentType
    """Either :attr:`ContentType.HTML` or :attr:`ContentType.TEXT`."""

    html: str | None
    """The extracted HTML, or ``None`` for plain-text content."""

    text: str | None
    """The extracted plain text, or ``None`` for HTML content."""

    document_codepage: int | None
    """The ``N`` in ``\\ansicpgN``, or ``None`` if the document declared none."""

    document_encoding: str
    """The Python codec used wherever no font-specific code page applied."""

    declared_html_charset: str | None
    """The charset the extracted HTML declares, verbatim and unnormalized.

    This is what the ``<meta>`` element says, not what the bytes actually were:
    an encapsulated document declaring ``windows-1252`` reports exactly that,
    even though :attr:`html` is already a decoded ``str``. Use
    :func:`golden_retriever.normalize_charset_declaration` before writing the
    output somewhere with a different encoding.
    """

    fonts: Mapping[int, FontInfo] = field(default_factory=dict)
    """The document's font table, keyed by ``\\fN`` identifier."""

    diagnostics: tuple[Diagnostic, ...] = ()
    """Problems encountered, in the order they occurred.

    Empty on clean input.
    """

    @property
    def body(self) -> str:
        """The extracted content, whichever of HTML or plain text it is."""
        if self.html is not None:
            return self.html
        if self.text is not None:
            return self.text
        raise GoldenRetrieverError(
            "result carries neither HTML nor plain text; this is a bug in "
            "golden-retriever"
        )
