# Dependency and workflow reproducibility

This hardening changes installation and automation, not the chat, data, identity or provider
contracts. CSV still needs no GCP or model credentials. It does not close live acceptance.

## Supported dependency profiles

| Profile | Installation | Purpose |
| --- | --- | --- |
| `runtime` | `python scripts/dependencies.py install runtime` | Standalone CSV/reference API; no BigQuery, DuckDB or JWT extra |
| `internal` | `python scripts/dependencies.py install internal` | Separate signed internal API with BigQuery and Parquet dependencies |
| `dev` | `python scripts/dependencies.py install dev` | Editable project, internal extras, tests, lint/type checks and lock compiler |

Start in a fresh Python virtual environment. CI tests CPython 3.11, 3.12 and 3.13 on Linux;
containers use CPython 3.12. Universal lock markers retain platform-specific dependencies, but
do not certify other Python/platform combinations. An unsupported wheel fails installation;
the installer does not fall back to an unreviewed source build. Installing a smaller profile over
an existing larger environment does not remove packages: recreate the environment to isolate it.

Each profile has a complete, exact-version, SHA-256-hashed dependency graph in `requirements/`.
The development lock constrains the two runtime locks so tests and shipped profiles use the
same shared package versions. Pip, setuptools and wheel are also included. Installation uses
`--require-hashes --only-binary=:all:` for third-party distributions, then installs this checkout
with `--no-deps --no-build-isolation`, followed by `pip check`. This prevents an unrecorded
dependency or isolated build-backend resolution. The local project is bound to the reviewed
source revision, not represented as a third-party wheel hash.

`requirements/manifest.json` records hashes of all three locks and their dependency inputs.
The installer fails before invoking pip when the inputs or locks have changed. The manifest is
a consistency check under code review, not a signature or proof that dependencies are safe.
Normal CI, Codespaces, both application Dockerfiles and the activation guide use this installer.

## Maintaining locks

The `dev` profile includes `uv==0.12.8`. With it installed and on PATH:

```bash
# Preserve existing selections while resolving any intentional input changes.
python scripts/dependencies.py lock
python scripts/dependencies.py check

# Explicitly refresh all allowed dependency versions for a reviewed update.
python scripts/dependencies.py lock --upgrade
```

Commit input changes, all affected lockfiles and the manifest together. Review package/version
changes and rerun the full Python/PostgreSQL matrix, CSV recovery, internal-package and frontend
acceptance before integrating. Never hand-edit hashes to silence an install failure. A failed
lock generation leaves the manifest invalid until generation completes successfully.

Generation follows the official [uv compilation workflow](https://docs.astral.sh/uv/pip/compile/).
The first compiler bootstrap and host Python/pip come from the maintainer's approved environment;
the tool rejects a different compiler version. No bootstrap download script is executed by the product.

## Workflow actions

All remote `uses:` references in the 21 repository workflows are pinned to verified upstream
40-character commit SHAs. Comments retain the major version for readability. Annotated tags
were resolved to their underlying commit before pinning. Local actions use the checked-out
revision; container actions must use a SHA-256 digest. The workflow validator rejects a return
to mutable tags or branches, including in reusable jobs. Dependabot continues to propose reviewed
action updates. This implements GitHub's [action-pinning guidance](https://docs.github.com/en/actions/reference/security/secure-use).

## Explicitly outside this hardening

- Container base images, PostgreSQL service images, Codespaces images/features and hosted runner
  environments still use version tags; OS packages are not yet a hermetic/digest-pinned build.
- Terraform provider selections still need a reviewed provider lockfile in the deployment
  environment. No Terraform apply or cloud activation is performed here.
- Optional legacy Hugging Face/Transformers jobs install additional unpinned model/demo packages;
  they are not the locked CSV/internal release path. Model artifacts are not covered by these locks.
- Action pins cover direct workflow references, not every transitive download performed by an action.
- Existing dependency update proposals must regenerate these locks and manifest; a source-only
  dependency change is deliberately rejected by CI. Locks do not replace vulnerability review.
- Branch protection, protected environments, license choice, real Claude/BigQuery/SSO evidence
  and enterprise-owner acceptance remain separate release controls.

Do not describe the whole product build as bit-for-bit reproducible or production-approved on
the strength of these dependency and action pins alone.

## Verification record

The fresh CPython 3.12 runtime install passed its hash checks and `pip check`; importing the CSV
application succeeded with neither Google nor DuckDB packages installed. The locked development
install passed 840 local tests with 27 explicitly disabled database/live checks. The new dependency
and workflow guards passed 33 tests with 97.69% combined coverage; CI enforces a separate 96%
floor for these tools. A second lock generation produced identical lock and manifest bytes.

The full PostgreSQL-backed Python matrix, frontend and packaged runtime validation belong to
the exact source recorded in [PR #26](https://github.com/yashumani/talk2data-conversational-intelligence/pull/26),
not to a generic branch-name claim. Refer to that record for hosted results and the integrated
source. The live provider and owner gates remain separate even when all development checks pass.
