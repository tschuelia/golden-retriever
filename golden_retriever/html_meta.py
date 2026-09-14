"""Reading and rewriting the charset declaration of extracted HTML.

De-encapsulation returns ``str``, but the extracted markup still carries whatever
charset its producer declared. Serializing that ``str`` as UTF-8 without touching the
declaration produces a file that lies about itself, so these helpers are kept separate
from extraction: extraction stays faithful, and rewriting is something the caller opts
into.
"""

__all__ = ["declared_charset", "normalize_charset_declaration"]


def declared_charset(html: str) -> str | None:
    """The charset ``html`` declares, verbatim, or ``None`` if it declares none.

    Recognizes both ``<meta charset=...>`` and the ``http-equiv`` form. The value is
    returned exactly as written -- not normalized, not validated against :mod:`codecs`.
    """
    raise NotImplementedError("declared_charset is not implemented yet")


def normalize_charset_declaration(html: str, encoding: str = "utf-8") -> str:
    """Return ``html`` with its charset declaration set to ``encoding``.

    Rewrites an existing ``<meta>`` declaration in place if there is one, and otherwise
    inserts one. Applying this twice with the same ``encoding`` is a no-op.
    """
    raise NotImplementedError("normalize_charset_declaration is not implemented yet")
