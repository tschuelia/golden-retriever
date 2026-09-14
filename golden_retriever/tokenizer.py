"""Single-pass byte-level RTF scanner (RTF 1.9.1, Basic Entities).

Design
======

The scanner works on ``bytes`` and never decodes. Which code page a text byte
belongs to is not known until the font table has been read, and in malformed
input text can precede ``{\\fonttbl...}``, so decoding here would mean guessing.
Bytes are handed on untouched and decoded once, later, by whoever knows the code
page.

It is a scanner rather than a grammar because two constructs are not
context-free: ``\\binN`` is a length-prefixed payload that may contain braces
and backslashes, and ``\\{`` escapes a brace that would otherwise open a group.
Both need a reader that can consume a counted run of raw bytes.

Every token is consumed, never buffered: the loop finds the next byte that can
end a run of text, emits everything before it as one ``TEXT`` token, and
dispatches on that single byte.

Syntax, per RTF 1.9.1 Basic Entities
====================================

- A control word is ``\\<ASCII Letter Sequence><Delimiter>``. The letter
  sequence is ``a`` through ``z`` and ``A`` through ``Z``, and "a control word's
  name cannot be longer than 32 letters".
- The delimiter is a space, which "serves only to delimit a control word and is
  ignored in subsequent processing"; or a digit or minus sign introducing a
  numeric parameter, where "an RTF parser must allow for up to 10 digits
  optionally preceded by a minus sign"; or "any character other than a letter or
  a digit", which terminates the name without being part of it. Only the space
  is consumed.
- A control symbol is "a backslash followed by a single, non-alphabetical
  character". Control symbols have no delimiter, so a space after one is text.
- Braces open and close groups.
- "CRLFs should be ignored by RTF readers except that they can act as control
  word delimiters", so a bare CR or LF produces no token at all.

Three more rules come from elsewhere in the specification:

- ``\\'hh`` is "a hexadecimal value, based on the specified character set"
  (Character Formatting, Special Characters).
- "A carriage return (character value 13) or line feed (character value 10) is
  treated as a ``\\par`` control if the character is preceded by a backslash"
  (Character Formatting, Special Characters).
- ``\\binN``: "the numeric parameter N is the number of bytes that follow.
  Unlike most other control words, ``\\binN`` takes a 32-bit parameter and the
  bytes are any 8-bit values" (Pictures, Picture Data).

A raw tab byte is deliberately left inside ``TEXT``. The specification says "a
tab (character value 9) should be treated as a ``\\tab`` control word", and it
already is: every code page decodes 0x09 to U+0009, which is exactly what
``\\tab`` produces.

Leniency
========

Malformed input is described, not rejected -- this scanner raises nothing for any
input whatsoever, and reports what it can about the rest. Two cases are
underspecified, and both resolve towards emitting no character rather than an
invented one:

- ``\\'`` not followed by two hexadecimal digits is reported as the control
  symbol ``'``, which no character table defines, so it is ignored. Emitting the
  apostrophe as text instead would add a character the producer did not write.
- A letter run longer than 32 letters, or a parameter longer than 10 digits, is
  malformed. The scanner takes the longest name and parameter the specification
  allows and leaves the overflow to be read as text, which is what the delimiter
  rule does with any other character it does not recognize.

A trailing backslash at end of input is dropped: there is nothing left for it to
escape.
"""

import re
from collections.abc import Iterator
from enum import StrEnum
from typing import NamedTuple

__all__ = [
    "MAX_CONTROL_WORD_LETTERS",
    "MAX_PARAMETER_DIGITS",
    "Token",
    "TokenKind",
    "tokenize",
]

MAX_CONTROL_WORD_LETTERS = 32
"""RTF 1.9.1: "a control word's name cannot be longer than 32 letters"."""

MAX_PARAMETER_DIGITS = 10
"""RTF 1.9.1: "up to 10 digits optionally preceded by a minus sign"."""


class TokenKind(StrEnum):
    """What a :class:`Token` stands for.

    The values are strings so that a failed assertion on a token sequence reads as
    the RTF it came from.
    """

    TEXT = "text"
    """Undecoded document text, in :attr:`Token.data`."""

    GROUP_START = "group-start"
    """An unescaped ``{``."""

    GROUP_END = "group-end"
    """An unescaped ``}``."""

    WORD = "word"
    """A control word: :attr:`Token.name` and :attr:`Token.param`."""

    SYMBOL = "symbol"
    """A control symbol: its single character is :attr:`Token.name`."""

    HEX = "hex"
    """A ``\\'hh`` escape: one byte, in both :attr:`Token.data` and
    :attr:`Token.param`."""

    BINARY = "binary"
    """A ``\\binN`` payload: the raw bytes found, in :attr:`Token.data`."""


class Token(NamedTuple):
    """One lexical unit of an RTF document.

    Which fields carry meaning depends on :attr:`kind`; the rest keep their
    defaults. Nothing here records where in the input the token came from, and
    that is deliberate: a consumer that can name a source position is a consumer
    that can be tempted to delete by position later, which is how a suppressed
    escape sequence ends up deleting an identical byte somewhere visible.
    """

    kind: TokenKind
    """Which of the seven constructs this is."""

    data: bytes = b""
    """Raw undecoded bytes: ``TEXT`` content, a ``BINARY`` payload, or the single
    byte of a ``HEX`` escape."""

    name: str = ""
    """A ``WORD`` name without its backslash, or the one character of a ``SYMBOL``.

    Control word names are ASCII by definition. A symbol character is reported as
    its Latin-1 character, which is exact for every control symbol the
    specification defines and, for anything else, only has to not match a table
    entry.
    """

    param: int | None = None
    """A ``WORD``'s numeric parameter, ``None`` if it declared none.

    On a ``HEX`` token this is the byte value, 0 to 255. On a ``BINARY`` token it
    is the *declared* length, which is longer than ``len(data)`` exactly when the
    payload ran past the end of the document.
    """


# The bytes that can end a run of plain text. Everything between two of them is
# emitted as a single TEXT token, so this is the whole reason the scanner is fast
# on documents that are mostly text.
_SPECIAL = re.compile(rb"[{}\\\r\n]")

_CONTROL_WORD = re.compile(
    (
        f"([A-Za-z]{{1,{MAX_CONTROL_WORD_LETTERS}}})"
        f"(-?[0-9]{{1,{MAX_PARAMETER_DIGITS}}})?"
        "[ ]?"
    ).encode("ascii")
)
"""Name, optional signed parameter, optional single delimiting space.

The digit count is bounded by the specification's own limit rather than by
``+``, which also keeps ``int()`` away from inputs long enough to hit CPython's
integer conversion limit.
"""

_HEX_DIGITS = re.compile(rb"[0-9A-Fa-f]{2}")

_BRACE_OPEN = 0x7B
_BRACE_CLOSE = 0x7D
_BACKSLASH = 0x5C
_APOSTROPHE = 0x27
_CARRIAGE_RETURN = 0x0D
_LINE_FEED = 0x0A

# Tokens that carry no payload, built once. A document is mostly braces and
# control words, and none of these need to allocate.
_GROUP_START_TOKEN = Token(TokenKind.GROUP_START)
_GROUP_END_TOKEN = Token(TokenKind.GROUP_END)
_PAR_TOKEN = Token(TokenKind.WORD, name="par")
_APOSTROPHE_TOKEN = Token(TokenKind.SYMBOL, name="'")
_HEX_TOKENS = tuple(
    Token(TokenKind.HEX, bytes((value,)), param=value) for value in range(256)
)


def tokenize(data: bytes) -> Iterator[Token]:
    """Yield the tokens of ``data``, in document order.

    Lazy, and safe on any input: no byte sequence makes this raise, and no byte of
    ``data`` is silently dropped except the insignificant ones the specification
    says to ignore -- bare CR and LF, a control word's single delimiting space,
    and a backslash at end of input.

    :param data: Uncompressed RTF bytes.
    """
    pos = 0
    end = len(data)
    # Bound the attribute lookups outside the loop; this runs once per byte of a
    # document that can be megabytes long.
    search_special = _SPECIAL.search
    match_control_word = _CONTROL_WORD.match
    match_hex_digits = _HEX_DIGITS.match

    while pos < end:
        special = search_special(data, pos)
        if special is None:
            yield Token(TokenKind.TEXT, data[pos:])
            return

        start = special.start()
        if start > pos:
            yield Token(TokenKind.TEXT, data[pos:start])
        pos = start + 1
        byte = data[start]

        if byte == _BRACE_OPEN:
            yield _GROUP_START_TOKEN
            continue
        if byte == _BRACE_CLOSE:
            yield _GROUP_END_TOKEN
            continue
        if byte != _BACKSLASH:
            # A bare CR or LF. Insignificant, and not even a token.
            continue
        if pos >= end:
            # A trailing backslash escapes nothing.
            return

        control_word = match_control_word(data, pos)
        if control_word is not None:
            digits = control_word.group(2)
            param = int(digits) if digits is not None else None
            name = control_word.group(1).decode("ascii")
            pos = control_word.end()
            if name == "bin" and param is not None and param > 0:
                # Slicing past the end yields what is there, which is how a
                # truncated payload is reported: param stays as declared.
                payload = data[pos : pos + param]
                pos += len(payload)
                yield Token(TokenKind.BINARY, payload, param=param)
            else:
                yield Token(TokenKind.WORD, name=name, param=param)
            continue

        # Not a letter, so this is a control symbol.
        byte = data[pos]
        pos += 1
        if byte == _APOSTROPHE:
            hex_digits = match_hex_digits(data, pos)
            if hex_digits is None:
                yield _APOSTROPHE_TOKEN
            else:
                pos = hex_digits.end()
                yield _HEX_TOKENS[int(hex_digits.group(), 16)]
            continue
        if byte in (_CARRIAGE_RETURN, _LINE_FEED):
            yield _PAR_TOKEN
            continue
        yield Token(TokenKind.SYMBOL, name=chr(byte))
