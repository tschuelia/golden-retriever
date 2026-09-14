"""Helpers shared by the test suite.

The golden fixtures are read as **bytes**, never as text. MS-OXRTFEX 2.2.3.2 maps
``\\par`` to CRLF, so every expected output contains CR characters that a text-mode read
would silently translate away on some platforms -- and a line-ending regression would
then pass everywhere except where it was noticed.
"""

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
"""Where the hand-authored documents live."""


def read_bytes(name: str) -> bytes:
    """Read a fixture file exactly as it is stored on disk.

    :param name: File name within ``tests/fixtures``.
    """
    return (FIXTURES / name).read_bytes()
