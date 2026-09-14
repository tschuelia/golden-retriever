# Agent instructions

All RTF handling in this package must be derived from:

- [MS-OXRTFEX](https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-oxrtfex/906fbb0f-2467-490e-8c3e-bdc31c5e9d35)
  — RTF Compressed and RTF-Encapsulated HTML
- [Rich Text Format (RTF) Specification, version 1.9.1](<https://learn.microsoft.com/en-us/previous-versions/office/developer/office-2007/dd351035(v=office.12)>)
- [Code Page Identifiers](https://learn.microsoft.com/en-us/windows/win32/intl/code-page-identifiers)

When you add a spec-derived table or rule, cite the section in a comment. That
citation is what makes the provenance auditable later.

Test fixtures must be hand-authored from the specification.

## Runtime dependencies

Stick to the standard library
only whenever possible. If a third-party library is useful, it must have an open-source license that allows this repo to be MIT. Do not add one without discussing it first.

## Working in this repo

- Prefix commands with `pixi run`; the tools are not on the global PATH.
- Run `pixi lock` after editing `pixi.toml`, and commit the updated `pixi.lock`.
- Lint tooling lives in the `lint` environment, which is built with
  `no-default-feature = true`. Run it as `pixi run -e lint lint`.
- Tests: `pixi run test`. Performance checks are marked `slow` and deselected by
  default; run them with `pixi run test-slow`.
- Type annotations are mandatory (`disallow_untyped_defs`), tests included.

## Committing

Do not commit or push. Report what changed and let the repository owner review
and commit.
