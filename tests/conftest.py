"""Helpers shared by the test suite.

The golden fixtures are read as **bytes**, never as text. MS-OXRTFEX 2.2.3.2 maps
``\\par`` to CRLF, so every expected output contains CR characters that a text-mode read
would silently translate away on some platforms -- and a line-ending regression would
then pass everywhere except where it was noticed.
"""

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
"""Where the hand-authored documents live."""

TEXT_PAIRS = ("fromtext_plain",)
"""Fixtures whose ``.rtf`` de-encapsulates to the matching ``.txt``."""

HTML_PAIRS = (
    "minimal_html",
    "multi_codepage_fonts",
    "nested_htmlrtf",
    "nonvisible_destinations",
    "pict_and_bin",
    "unicode_and_surrogates",
)
"""Fixtures whose ``.rtf`` de-encapsulates to the matching ``.html``."""

GOLDEN_DOCUMENTS = TEXT_PAIRS + HTML_PAIRS
"""Every golden document, by name.

Listed rather than discovered from the directory, and shared so that the golden tests
and the mutation fuzz cannot drift apart: a fixture that went missing would make an
auto-discovering suite quietly smaller instead of red.
"""


def read_bytes(name: str) -> bytes:
    """Read a fixture file exactly as it is stored on disk.

    :param name: File name within ``tests/fixtures``.
    """
    return (FIXTURES / name).read_bytes()
