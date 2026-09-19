# Contributing to Talk2Data

Thank you for helping build a governed conversational-data platform. The community alpha welcomes
documentation, tests, accessibility improvements, security hardening, connectors that preserve the
read-only boundary, and visualization implementations from the finite matrix.

## Before opening work

1. Read [the Code of Conduct](CODE_OF_CONDUCT.md), [governance](GOVERNANCE.md), and
   [security policy](SECURITY.md).
2. Search existing issues and the [visualization matrix](docs/VISUALIZATION_IMPLEMENTATION_MATRIX.md).
3. Open or claim one narrowly scoped issue. For visualization work, identify the registry ID and
   keep the canonical chart semantics intact.
4. Use synthetic or explicitly redistributable data only. Never submit employer, customer,
   employee, credential, production schema, or private knowledge-base material.

## Development

Python 3.11–3.13 and Node 24 are supported. Create a clean environment and install locked profiles:

```bash
python -m venv .venv
source .venv/bin/activate
python scripts/dependencies.py install dev
(cd apps/web && npm ci)
```

Run the same core checks used by pull requests:

```bash
ruff check .
ruff format --check .
mypy src
pytest
python scripts/validate_community.py
python scripts/validate_visualization_inventory.py
(cd apps/web && npm test && npm run build)
```

## Pull requests

- Keep CSV, private BigQuery/Parquet, and public synthetic profiles separate.
- Put authorization, metric meaning, query compilation, and claim certification in deterministic
  services—not prompts or UI code.
- Add regression tests for every behavior change. The project target is at least 96% line and
  branch coverage in hosted CI.
- Explain security and data-boundary impact, limitations, and verification evidence.
- Do not copy source code, screenshots, datasets, or visual assets from inspiration galleries.
  Reimplement the product contract independently and preserve attribution links in the inventory.

## DCO sign-off

Every commit must include a `Signed-off-by` trailer matching the commit author:

```bash
git commit -s -m "feat: describe the contribution"
```

The sign-off certifies the [Developer Certificate of Origin](DCO). Do not sign for another person.

## Review and release

Maintainers require green checks, CODEOWNERS review, resolved conversations, and the applicable
manual evidence. A merged change is not automatically a release. The authoritative launch gates
are in [the public alpha checklist](docs/PUBLIC_ALPHA_RELEASE_CHECKLIST.md).
