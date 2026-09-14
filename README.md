# golden-retriever

[![CI](https://github.com/tschuelia/golden-retriever/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/tschuelia/golden-retriever/actions/workflows/ci.yml)

A Python package.

## Development

Install the development environment and the package:

```console
pixi install
pixi run postinstall
```

Run the tests and quality checks:

```console
pixi run test
pixi run -e lint lint
pixi run -e lint format-check
```

The test suite is also available for every supported Python version:

```console
pixi run -e py312 test
pixi run -e py313 test
pixi run -e py314 test
```
