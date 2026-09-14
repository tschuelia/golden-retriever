"""Golden Retriever."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("golden-retriever")
except PackageNotFoundError:  # pragma: no cover - package is installed in normal use
    __version__ = "0.0.0"

__all__ = ["__version__"]
