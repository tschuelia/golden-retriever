"""Reading and rewriting the charset declaration of extracted HTML.

De-encapsulation returns ``str``, but the extracted markup still carries whatever
charset its producer declared. Serializing that ``str`` as UTF-8 without touching the
declaration produces a file that lies about itself, so these helpers are kept separate
from extraction: extraction stays faithful, and rewriting is something the caller opts
into.

Scope
=====

A charset declaration is HTML rather than RTF, so nothing in this module derives from
MS-OXRTFEX; what it recognizes is the two spellings a producer writes:

- ``<meta charset="windows-1252">``
- ``<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">``

This is a targeted rewrite of one attribute value, not an HTML parser, and the limits
are deliberate:

- Only the head is searched -- everything up to the first ``</head>`` or ``<body>``.
  Further down, a ``<meta>`` is quoted text in a reply rather than a declaration of
  anything.
- A ``<meta>`` whose attribute values contain ``>`` is not recognized. That cannot occur
  in a charset declaration, and handling it would mean tokenizing the whole document.
- A declaration that is read is never validated or normalized. What the producer wrote is
  what :func:`declared_charset` reports, whether or not a decoder for it exists. A
  declaration that is *written* is checked, because its name reaches the markup.
"""

import codecs
import re

__all__ = ["declared_charset", "normalize_charset_declaration"]

_META = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
"""A ``<meta>`` start tag, which is where either spelling of the declaration sits."""

_HEAD_START = re.compile(r"<head\b[^>]*>", re.IGNORECASE)
"""Where an inserted declaration goes, so that it precedes anything else in the head."""

_HEAD_END = re.compile(r"</head\b|<body\b", re.IGNORECASE)
"""Where a ``<meta>`` stops being a declaration, whichever of the two comes first."""

_ATTRIBUTE = re.compile(
    r"""(?P<name>[^\s"'>/=]+)                        # up to the delimiter that ends it
        \s*=\s*                                      # whitespace is allowed either side
        (?P<value>"[^"]*"|'[^']*'|[^\s"'`=<>]+)      # double-quoted, single, or bare
    """,
    re.VERBOSE,
)
"""One ``name=value`` attribute of a start tag.

A quoted value is taken whole, so the ``charset=`` inside a ``Content-Type`` is never
mistaken for an attribute of the element itself. An attribute with no value at all
matches nothing here, which is correct: it declares nothing.
"""

_CHARSET_PARAMETER = re.compile(r"charset\s*=\s*(?P<value>[^\s;\"']+)", re.IGNORECASE)
"""The ``charset`` parameter of a ``Content-Type``, whose parameters are
``;``-separated."""


def declared_charset(html: str) -> str | None:
    """The charset ``html`` declares, verbatim, or ``None`` if it declares none.

    Recognizes both ``<meta charset=...>`` and the ``http-equiv`` form. The value is
    returned exactly as written -- not normalized, not validated against :mod:`codecs`.
    """
    span = _charset_span(html)
    if span is None:
        return None
    start, end = span
    return html[start:end]


def normalize_charset_declaration(html: str, encoding: str = "utf-8") -> str:
    """Return ``html`` with its charset declaration set to ``encoding``.

    Rewrites an existing ``<meta>`` declaration in place if there is one, and otherwise
    inserts one. Applying this twice with the same ``encoding`` is a no-op.

    :param encoding: The name to declare, written out as given. Only the declaration
        changes; nothing here re-encodes anything.
    :raises ValueError: ``encoding`` names no codec Python can find. The name is
        interpolated into markup, so anything that is not a codec name is refused rather
        than written into the document.
    """
    try:
        codecs.lookup(encoding)
    except LookupError as error:
        raise ValueError(f"encoding={encoding!r} names no available codec") from error

    span = _charset_span(html)
    if span is not None:
        start, end = span
        return html[:start] + encoding + html[end:]

    # Nothing to rewrite, so one is added and nothing else about the markup changes: no
    # line break, no reindentation, so that a second call finds this declaration and
    # returns the same string again.
    declaration = f'<meta charset="{encoding}">'
    head = _HEAD_START.search(html)
    if head is None:
        return declaration + html
    return html[: head.end()] + declaration + html[head.end() :]


def _charset_span(html: str) -> tuple[int, int] | None:
    """Where the value of the first charset declaration in ``html`` sits.

    A span rather than a string, because reading the declaration and rewriting it are
    then the same search. ``None`` if the head declares no charset.
    """
    end_of_head = _HEAD_END.search(html)
    head = html if end_of_head is None else html[: end_of_head.start()]
    for element in _META.finditer(head):
        span = _declared_span(element)
        if span is not None:
            return span
    return None


def _declared_span(element: re.Match[str]) -> tuple[int, int] | None:
    """Where this one ``<meta>`` element's charset value sits, if it declares one.

    A ``charset`` attribute wins over the ``http-equiv`` form when an element carries
    both, and the ``http-equiv`` form counts only when it names ``Content-Type``: a
    ``content`` attribute on its own belongs to some other kind of ``<meta>``.
    """
    tag = element.group()
    charset: tuple[int, int] | None = None
    content: tuple[int, int] | None = None
    is_content_type = False
    for attribute in _ATTRIBUTE.finditer(tag):
        name = attribute.group("name").lower()
        start, end = _value_span(attribute)
        value = tag[start:end]
        if name == "charset" and charset is None:
            charset = (start, end)
        elif name == "http-equiv" and value.strip().lower() == "content-type":
            is_content_type = True
        elif name == "content" and content is None:
            parameter = _CHARSET_PARAMETER.search(value)
            if parameter is not None:
                content = (
                    start + parameter.start("value"),
                    start + parameter.end("value"),
                )

    span = charset
    if span is None and is_content_type:
        span = content
    if span is None:
        return None
    offset = element.start()
    return offset + span[0], offset + span[1]


def _value_span(attribute: re.Match[str]) -> tuple[int, int]:
    """Where an attribute's value sits, inside its quotes if it has any."""
    start, end = attribute.span("value")
    if attribute.group("value")[0] in "\"'":
        return start + 1, end - 1
    return start, end
