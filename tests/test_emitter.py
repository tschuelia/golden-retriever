"""Tests for deferred decoding.

These bypass the drivers entirely and drive the emitter by hand, because the
properties that matter here are about ordering and grouping: which bytes reach a
decoder together, where a replacement character lands relative to the text around
it, and that no output can ever fail to encode as UTF-8. Driving it directly is
also the only way to build a case the RTF syntax makes hard to write, such as a
double-byte pair split between two fonts.
"""

from collections.abc import Mapping

import pytest

from golden_retriever.emitter import REPLACEMENT_CHARACTER, Emitted, Emitter
from golden_retriever.result import DiagnosticCode

FFFD = REPLACEMENT_CHARACTER

HIGH_SURROGATE = -10179
"""``\\u-10179``: 0xD83D, the high half of U+1F600."""

LOW_SURROGATE = -8704
"""``\\u-8704``: 0xDE00, the low half of U+1F600."""


def resolve(
    emitter: Emitter,
    *,
    fonts: Mapping[int, str] | None = None,
    document: str = "cp1252",
) -> Emitted:
    return emitter.resolve(
        font_encodings={} if fonts is None else fonts, document_encoding=document
    )


def codes(emitted: Emitted) -> list[str]:
    return [diagnostic.code for diagnostic in emitted.diagnostics]


def test_an_empty_emitter_resolves_to_nothing() -> None:
    emitted = resolve(Emitter())
    assert emitted == Emitted("", ())


def test_bytes_without_a_font_use_the_document_encoding() -> None:
    emitter = Emitter()
    emitter.add_bytes(b"r\xe9sum\xe9", None)
    assert resolve(emitter).text == "résumé"


def test_a_fonts_encoding_wins_over_the_document_encoding() -> None:
    """MS-OXRTFEX 2.2.3.2: a reader "SHOULD use the code page information, as specified
    for each font in a font table"."""
    emitter = Emitter()
    emitter.add_bytes(b"\xe0", 1)
    emitter.add_bytes(b"\xe9", 2)
    emitted = resolve(emitter, fonts={1: "cp1252", 2: "cp1251"}, document="cp932")
    assert emitted.text == "àй"
    assert emitted.diagnostics == ()


def test_a_font_id_of_none_ignores_the_font_table() -> None:
    """HTMLTAG content is decoded in the document code page whatever font is
    selected."""
    emitter = Emitter()
    emitter.add_bytes(b"\xe9", None)
    assert resolve(emitter, fonts={0: "cp932"}).text == "é"


def test_a_double_byte_pair_in_one_run_decodes_as_one_character() -> None:
    """RTF 1.9.1 (Escaped Expressions) allows both bytes of a double-byte character to
    be escaped, so ``\\'82\\'a0`` arrives as two separate escapes."""
    emitter = Emitter()
    emitter.add_bytes(b"\x82", 1)
    emitter.add_bytes(b"\xa0", 1)
    assert resolve(emitter, fonts={1: "cp932"}).text == "あ"


def test_a_double_byte_pair_survives_a_font_change() -> None:
    """The headline case for carrying a decoder across runs.

    ``\\f1\\'82\\f2\\'a0`` splits a lead byte and its trailing byte into two runs. They
    are still one character, because both fonts name the same code page.
    """
    emitter = Emitter()
    emitter.add_bytes(b"\x82", 1)
    emitter.add_bytes(b"\xa0", 2)
    emitted = resolve(emitter, fonts={1: "cp932", 2: "cp932"})
    assert emitted.text == "あ"
    assert emitted.diagnostics == ()


def test_a_dangling_lead_byte_is_replaced_before_the_text_that_follows() -> None:
    """Position is the assertion: the replacement character belongs where the byte was,
    not after the paragraph break."""
    emitter = Emitter()
    emitter.add_bytes(b"\x82", 1)
    emitter.add_text("\r\n")
    emitter.add_bytes(b"A", 1)
    emitted = resolve(emitter, fonts={1: "cp932"})
    assert emitted.text == f"{FFFD}\r\nA"
    assert codes(emitted) == [DiagnosticCode.UNDECODABLE_BYTES]


def test_decoded_text_stops_a_pair_from_forming_across_it() -> None:
    """A lead byte must not reach across a character the producer wrote between them.

    The trailing byte's own fate is Python's cp932 mapping to answer; all that matters
    here is that the two bytes did not become one character.
    """
    emitter = Emitter()
    emitter.add_bytes(b"\x82", 1)
    emitter.add_text("-")
    emitter.add_bytes(b"\xa0", 1)
    emitted = resolve(emitter, fonts={1: "cp932"})
    assert emitted.text.startswith(f"{FFFD}-")
    assert "あ" not in emitted.text


def test_a_font_change_to_another_encoding_starts_a_new_decoder() -> None:
    emitter = Emitter()
    emitter.add_bytes(b"\x82", 1)
    emitter.add_bytes(b"A", 2)
    emitted = resolve(emitter, fonts={1: "cp932", 2: "cp1252"})
    assert emitted.text == f"{FFFD}A"
    assert codes(emitted) == [DiagnosticCode.UNDECODABLE_BYTES]


def test_segments_keep_document_order() -> None:
    emitter = Emitter()
    emitter.add_bytes(b"a", None)
    emitter.add_text("—")
    emitter.add_bytes(b"b", 1)
    emitter.add_unicode(0x2603)
    emitter.add_bytes(b"c", None)
    assert resolve(emitter, fonts={1: "cp1252"}).text == "a—b☃c"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (65, "A"),
        (0x2603, "☃"),
        (-3891, ""),
        (-4064, ""),
        (0x10000, "\U00010000"),
    ],
)
def test_a_unicode_escape_names_a_character(value: int, expected: str) -> None:
    """RTF 1.9.1: "the character code U+F020 is given by ``\\u-4064``".

    Values above 32767 arrive negative because "most RTF control words accept signed
    16-bit numbers as arguments", so the sign is part of the character.
    """
    emitter = Emitter()
    emitter.add_unicode(value)
    emitted = resolve(emitter)
    assert emitted.text == expected
    assert emitted.diagnostics == ()


def test_a_surrogate_pair_becomes_one_character() -> None:
    """RTF has no other way to write a character outside the basic multilingual
    plane."""
    emitter = Emitter()
    emitter.add_unicode(HIGH_SURROGATE)
    emitter.add_unicode(LOW_SURROGATE)
    emitted = resolve(emitter)
    assert emitted.text == "\U0001f600"
    assert emitted.diagnostics == ()


def test_a_high_surrogate_alone_is_replaced_at_resolve_time() -> None:
    emitter = Emitter()
    emitter.add_unicode(HIGH_SURROGATE)
    emitted = resolve(emitter)
    assert emitted.text == FFFD
    assert codes(emitted) == [DiagnosticCode.UNPAIRED_SURROGATE]


def test_a_low_surrogate_alone_is_replaced_immediately() -> None:
    emitter = Emitter()
    emitter.add_unicode(LOW_SURROGATE)
    emitter.add_text("x")
    emitted = resolve(emitter)
    assert emitted.text == f"{FFFD}x"
    assert codes(emitted) == [DiagnosticCode.UNPAIRED_SURROGATE]


def test_two_high_surrogates_are_both_replaced() -> None:
    emitter = Emitter()
    emitter.add_unicode(HIGH_SURROGATE)
    emitter.add_unicode(HIGH_SURROGATE)
    emitted = resolve(emitter)
    assert emitted.text == FFFD * 2
    assert codes(emitted) == [DiagnosticCode.UNPAIRED_SURROGATE] * 2


@pytest.mark.parametrize("interrupt", ["text", "bytes"])
def test_a_high_surrogate_is_replaced_before_whatever_interrupts_it(
    interrupt: str,
) -> None:
    """Anything but the matching escape ends the pair, and the replacement character has
    to land before that content rather than after it."""
    emitter = Emitter()
    emitter.add_unicode(HIGH_SURROGATE)
    if interrupt == "text":
        emitter.add_text("x")
    else:
        emitter.add_bytes(b"x", None)
    emitted = resolve(emitter)
    assert emitted.text == f"{FFFD}x"
    assert codes(emitted) == [DiagnosticCode.UNPAIRED_SURROGATE]


@pytest.mark.parametrize("value", [0x110000, 9999999999, -9999999999])
def test_a_unicode_escape_naming_no_character_is_replaced(value: int) -> None:
    """A parameter this far out of range is broken syntax rather than lost data, so
    there is nothing to diagnose about the document's content."""
    emitter = Emitter()
    emitter.add_unicode(value)
    emitted = resolve(emitter)
    assert emitted.text == FFFD
    assert emitted.diagnostics == ()


@pytest.mark.parametrize(
    "values",
    [
        [HIGH_SURROGATE],
        [LOW_SURROGATE],
        [HIGH_SURROGATE, HIGH_SURROGATE],
        [LOW_SURROGATE, HIGH_SURROGATE],
        [HIGH_SURROGATE, LOW_SURROGATE],
        [0xD800],
        [0xDFFF],
    ],
)
def test_resolved_text_is_always_utf_8_encodable(values: list[int]) -> None:
    """The invariant a caller depends on: whatever the document did, the result can be
    written out.

    A lone surrogate is a valid :class:`str` and fails only later, at encode time, in
    the caller's code rather than here.
    """
    emitter = Emitter()
    for value in values:
        emitter.add_unicode(value)
    emitter.add_bytes(b"tail", None)
    emitted = resolve(emitter)
    assert emitted.text.encode("utf-8")


def test_a_surrogate_produced_by_a_decoder_is_swept_up() -> None:
    """Code page 65000 is UTF-7, whose decoder can produce a lone surrogate from bytes
    that no ``\\uN`` escape was involved in."""
    emitter = Emitter()
    emitter.add_bytes(b"+2D8-", None)
    emitted = resolve(emitter, document="utf_7")
    assert emitted.text == FFFD
    assert emitted.text.encode("utf-8")
    assert codes(emitted) == [DiagnosticCode.UNPAIRED_SURROGATE]


def test_an_unknown_font_falls_back_and_is_reported_once() -> None:
    """A document can select a font it never defined; that is a reason to record a
    diagnostic, not to lose the text."""
    emitter = Emitter()
    emitter.add_bytes(b"\xe9", 7)
    emitter.add_text("-")
    emitter.add_bytes(b"\xe9", 7)
    emitted = resolve(emitter, fonts={0: "cp932"}, document="cp1252")
    assert emitted.text == "é-é"
    assert codes(emitted) == [DiagnosticCode.UNKNOWN_FONT]
    assert "7" in emitted.diagnostics[0].message


def test_undecodable_bytes_are_counted_together() -> None:
    emitter = Emitter()
    emitter.add_bytes(b"a\x81b\x8dc", None)
    emitted = resolve(emitter)
    assert emitted.text == f"a{FFFD}b{FFFD}c"
    assert codes(emitted) == [DiagnosticCode.UNDECODABLE_BYTES]
    assert "2" in emitted.diagnostics[0].message


def test_a_replacement_character_in_decoded_text_is_not_a_decoding_problem() -> None:
    """Only what a decoder produced counts, or every ``\\u65533`` escape would claim the
    document had undecodable bytes."""
    emitter = Emitter()
    emitter.add_text(FFFD)
    emitter.add_unicode(0xFFFD)
    emitted = resolve(emitter)
    assert emitted.text == FFFD * 2
    assert emitted.diagnostics == ()


def test_diagnostics_come_in_the_order_they_happened() -> None:
    """Appending happens during the scan and decoding after it, so a surrogate problem
    precedes a code page problem however the document was written."""
    emitter = Emitter()
    emitter.add_bytes(b"\x81", 3)
    emitter.add_unicode(HIGH_SURROGATE)
    emitter.add_text("x")
    emitted = resolve(emitter)
    assert codes(emitted) == [
        DiagnosticCode.UNPAIRED_SURROGATE,
        DiagnosticCode.UNKNOWN_FONT,
        DiagnosticCode.UNDECODABLE_BYTES,
    ]


def test_resolving_twice_changes_nothing() -> None:
    """Not part of the contract, but a second call must not double a diagnostic or
    reorder the text if a driver or a fuzz case makes one."""
    emitter = Emitter()
    emitter.add_bytes(b"\x81", None)
    emitter.add_unicode(HIGH_SURROGATE)
    first = resolve(emitter)
    assert resolve(emitter) == first
