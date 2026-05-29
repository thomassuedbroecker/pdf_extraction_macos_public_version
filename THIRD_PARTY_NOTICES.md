# Third-Party Notices

Review date: 2026-05-29

This project is licensed under the Apache License 2.0 as described in
`LICENSE`. This notice documents known third-party components, optional
services, packaging surfaces, and media assets used by the repository. It is a
transparency aid and not legal advice. Verify package metadata, transitive
dependencies, and packaging artifacts again before public release or commercial
redistribution.

## Python Runtime

The application requires Python 3.12 or later and declares direct runtime
dependencies in `pyproject.toml`.

| Component | Observed use | License or terms note |
| --- | --- | --- |
| Python | Application runtime | Python Software Foundation License Version 2 |
| `PySide6-Essentials` | Qt/PySide desktop UI framework | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only, with commercial licensing available from Qt. Follow LGPL obligations when packaging and redistributing the app. |
| `pypdf` | PDF metadata, page count, encryption check, and text extraction preview | BSD-3-Clause |
| `openpyxl` | `.xlsx` export | MIT |
| `platformdirs` | User config and log paths | MIT |

This repository does not currently include a generated SBOM or transitive
dependency license report. See `DEPENDENCY_LICENSE_TRANSPARENCY.md` for the
per-scope dependency mapping.

## Optional Dependencies and Local Services

| Component | Observed use | License or terms note |
| --- | --- | --- |
| `docling` | Optional structured PDF text extraction backend | Current package metadata indicates MIT, but it is optional and unpinned. Verify exact version metadata before release. |
| Ollama | Optional local LLM service accessed over HTTP | Ollama is not installed by this Python project. Its repository is MIT licensed, while downloaded local models can have separate model licenses and usage terms. |

The application can send extracted PDF text to a local Ollama server selected
by the user. The repository does not ship Ollama models. Any model used with
Ollama must be reviewed separately for license, redistribution, commercial-use,
privacy, and data-handling terms.

## Development and Test Tooling

| Component | Observed use | License or terms note |
| --- | --- | --- |
| `pytest` | Unit and UI test execution | MIT |
| `ruff` | Lint configuration and developer tooling | MIT |
| `setuptools` | Build backend | MIT |
| `wheel` | Build support | MIT |

Development tools are not part of the app runtime unless they are bundled in a
release artifact.

## Packaged macOS App

The repository includes `scripts/build_macos_app.py`, which creates a
lightweight `.app` bundle that launches the local Python environment. Before
publishing or redistributing a packaged app:

- Include this notice, `LICENSE`, and any required third-party notices with
  the distribution.
- Generate a dependency inventory from the exact environment used to build the
  app.
- Confirm whether PySide6/Qt libraries are bundled, dynamically loaded from a
  local environment, or expected to be installed separately.
- If PySide6/Qt libraries are bundled, retain Qt/PySide license texts and
  satisfy LGPL obligations, including allowing replacement or relinking where
  required.
- Review macOS signing, notarization, and trademark notices separately from
  open-source license notices.

## Media Assets

The repository includes documentation GIFs under `images/`:

| Asset | Observed use | Provenance note |
| --- | --- | --- |
| `images/add-folders.gif` | README demonstration media | Treat as project documentation media unless a source file states otherwise. |
| `images/llm-results.gif` | README demonstration media | Treat as project documentation media unless a source file states otherwise. |
| `images/llm-export-result-file.gif` | README demonstration media | Treat as project documentation media unless a source file states otherwise. |

These assets may show application UI, local files, prompts, model output, or
third-party product names. They do not grant rights in any underlying
third-party trademarks, model names, operating-system UI, or external service
interfaces. Do not reuse these media assets outside this project without
confirming provenance and permissions.

## Generated Documentation and Test PDFs

The tests create synthetic PDF files at runtime using `pypdf`; those generated
test artifacts are not checked in as third-party source material. If generated
documentation, generated screenshots, sample PDFs, or third-party PDFs are
added later, record their source, license, generation method, and reviewer.

## Maintenance Rule

Update this file when:

- A Python dependency, optional service, local model, packaging tool, media
  asset, or generated artifact is added or removed.
- Dependency versions are pinned, upgraded, or bundled into a packaged app.
- A release starts shipping vendored libraries, Qt/PySide binaries, model
  files, screenshots from third-party products, or sample PDFs.
- A generated SBOM or license scan becomes available.

