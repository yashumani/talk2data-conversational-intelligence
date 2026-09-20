# Versioning and compatibility

Talk2Data uses Semantic Versioning.

- `MAJOR` changes stable public contracts incompatibly.
- `MINOR` adds backward-compatible capabilities.
- `PATCH` corrects backward-compatible defects.
- Pre-release labels such as `alpha.1` identify evaluation candidates with intentionally unstable
  interfaces and no production support promise.

The current community candidate uses `0.7.0-alpha.2` for release artifacts and the PEP 440
equivalent `0.7.0a2` for the Python package. `VERSION`, `CHANGELOG.md`, `pyproject.toml`, the web package,
runtime metadata, and Pages release receipt must agree.

Breaking alpha changes must still be described in the changelog. Release artifacts are bound to
an exact 40-character source SHA; a mutable branch name is not release evidence.
