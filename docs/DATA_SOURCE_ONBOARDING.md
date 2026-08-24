# Data Source Onboarding and Tenant Runtime Packages

Talk2Data uses one stable, versioned runtime. A tenant package supplies the governed configuration around that runtime rather than generating a separate application codebase.

## Public builder

Open the GitHub Pages setup flow:

```text
https://yashumani.github.io/talk2data-conversational-intelligence/setup/
```

The browser-based builder collects only non-secret deployment metadata:

- project and tenant identifiers;
- approved PostgreSQL schema, table, and column names;
- semantic metric and dimension mappings;
- the name of an environment variable that will hold the database DSN;
- local Ollama model and runtime limits.

It does not request, retain, or upload a database password or connection string.

## Runtime package contents

A generated ZIP contains:

```text
.env.example
docker-compose.yml
README.md
checksums.json
config/talk2data.yaml
config/domain-packs/<tenant>.yaml
config/physical-mappings/<tenant>.yaml
scripts/start.sh
scripts/start.ps1
.github/workflows/validate.yml
.devcontainer/devcontainer.json   # optional
```

The package references the stable runtime image:

```text
ghcr.io/yashumani/talk2data-conversational-intelligence:main
```

Every generated file is covered by `checksums.json`. ZIP timestamps and file order are fixed so the same approved request produces the same package bytes.

## API-driven generation

An administrator can use the runtime API instead of the browser generator:

```text
POST /v1/onboarding/validate
POST /v1/onboarding/package
```

Both endpoints require the `TALK2DATA_ADMIN` role. The request can use the tenant's currently approved physical mapping or submit a complete `TenantPhysicalMappingPack` for validation. The API rejects:

- mismatched tenant IDs;
- unapproved mapping packs;
- missing connectors for available semantic metrics;
- aggregation or dimension incompatibilities;
- non-`env://` secret references;
- invalid project, model, port, or connector selections.

The package response includes mapping version and mapping hash headers, but no secret value.

## Start a generated package

```bash
cp .env.example .env
# Set the required T2D_POSTGRES_DSN value in .env.
docker compose up -d
```

Then open:

```text
http://localhost:8000/demo
http://localhost:8000/docs
http://localhost:8000/health/ready
```

The generated Compose stack starts:

```text
Ollama
  -> selected local model
Talk2Data runtime
  -> Tenant Domain Pack
  -> physical mapping pack
  -> read-only PostgreSQL connector
  -> verification and query receipts
```

## Security boundary

- The builder never collects a credential.
- Mapping files may contain only `env://NAME` references.
- The runtime resolves the environment variable locally.
- Database values are bound parameters.
- Physical identifiers must be approved simple identifiers.
- The model does not generate executable SQL.
- The runtime image contains no tenant data.
- A numeric claim is released only after source coverage and result verification pass.

## GitHub responsibilities

GitHub Pages hosts the guided builder. GitHub Actions validates the application and generated-package contract. GitHub Container Registry distributes the stable runtime image. Codespaces provides a complete temporary evaluation environment. Continuous production execution remains on a user-owned workstation, server, VM, or container platform.
