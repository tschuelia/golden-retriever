"""Tests pinning the shape of the public API.

These guard properties that are easy to break by accident and expensive to break in a
release: the exception hierarchy, the export list, and the immutability of the result
types.
"""

import dataclasses
import importlib.resources
import types

import pytest

import ottertf as gr

EXCEPTIONS = [
    gr.MalformedRtfError,
    gr.MissingFontTableError,
    gr.NotEncapsulatedRtfError,
    gr.UnsupportedCodePageError,
]


@pytest.mark.parametrize("exc", EXCEPTIONS)
def test_exceptions_derive_from_the_package_root(exc: type[Exception]) -> None:
    assert issubclass(exc, gr.OtteRTFError)


@pytest.mark.parametrize("exc", [gr.OtteRTFError, *EXCEPTIONS])
@pytest.mark.parametrize(
    "builtin", [TypeError, ValueError, LookupError, ArithmeticError]
)
def test_exceptions_do_not_alias_builtins(
    exc: type[Exception], builtin: type[Exception]
) -> None:
    """A caller's ``except TypeError`` must not swallow our errors.

    Inheriting from a builtin makes ``except OtteRTFError`` neither necessary
    nor sufficient, which is exactly the trap this package exists to avoid.
    """
    assert not issubclass(exc, builtin)


def test_root_exception_derives_from_exception() -> None:
    assert issubclass(gr.OtteRTFError, Exception)


def test_all_is_sorted_and_importable() -> None:
    assert list(gr.__all__) == sorted(gr.__all__)
    for name in gr.__all__:
        assert hasattr(gr, name), name


def test_all_covers_every_public_attribute() -> None:
    """Nothing public may exist that ``__all__`` does not mention.

    This is what catches a stray ``from x import y`` in ``__init__`` leaking ``y`` into
    the package namespace.
    """
    public = {
        name
        for name, value in vars(gr).items()
        # Submodules are an implementation detail, not public surface.
        if not name.startswith("_") and not isinstance(value, types.ModuleType)
    }
    assert public == set(gr.__all__) - {"__version__"}


def test_version_is_a_string() -> None:
    assert isinstance(gr.__version__, str)
    assert gr.__version__


def test_py_typed_is_packaged() -> None:
    """PEP 561 marker must ship, or downstream type checking silently degrades."""
    marker = importlib.resources.files("ottertf").joinpath("py.typed")
    assert marker.is_file()


@pytest.mark.parametrize("cls", [gr.DeEncapsulationResult, gr.Diagnostic, gr.FontInfo])
def test_result_types_are_frozen(cls: type) -> None:
    assert dataclasses.fields(cls) is not None
    assert cls.__dataclass_params__.frozen  # type: ignore[attr-defined]


def test_content_type_values() -> None:
    assert gr.ContentType.HTML == "html"
    assert gr.ContentType.TEXT == "text"
    assert gr.ContentType.NATIVE_RTF == "native-rtf"


def test_diagnostic_codes_are_plain_strings() -> None:
    """Callers may compare against literals without importing the enum."""
    assert gr.DiagnosticCode.UNKNOWN_FONT == "unknown-font"
    assert isinstance(gr.DiagnosticCode.UNKNOWN_FONT, str)


def _result(
    html: str | None = None, text: str | None = None
) -> gr.DeEncapsulationResult:
    return gr.DeEncapsulationResult(
        content_type=gr.ContentType.HTML if html is not None else gr.ContentType.TEXT,
        html=html,
        text=text,
        document_codepage=1252,
        document_encoding="cp1252",
        declared_html_charset=None,
    )


def test_body_returns_html_then_text() -> None:
    assert _result(html="<p>x</p>").body == "<p>x</p>"
    assert _result(text="x").body == "x"


def test_body_raises_a_package_error_when_empty() -> None:
    empty = gr.DeEncapsulationResult(
        content_type=gr.ContentType.HTML,
        html=None,
        text=None,
        document_codepage=None,
        document_encoding="cp1252",
        declared_html_charset=None,
    )
    with pytest.raises(gr.OtteRTFError):
        _ = empty.body


def test_result_defaults_are_empty_not_shared() -> None:
    a, b = _result(html="a"), _result(html="b")
    assert a.fonts == {} and a.diagnostics == ()
    assert a.fonts is not b.fonts


def test_result_is_immutable() -> None:
    result = _result(html="<p>x</p>")
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.html = "other"  # type: ignore[misc]
