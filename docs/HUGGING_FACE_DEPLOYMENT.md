# Hugging Face public demonstration

Talk2Data keeps Ollama as the local development provider. The Hugging Face deployment
uses the same governed core with a small Transformers model running inside a Gradio Space.

## Runtime design

```text
Gradio interface
    -> Qwen local interpretation
    -> Domain Pack identifier validation
    -> question admissibility and policy
    -> Business Query IR
    -> parameterized synthetic SQLite query
    -> result-sense verification
    -> certified claims and receipt
```

The model does not calculate metrics, authorize users, write SQL, or create certified
numbers. If model output is malformed, the deterministic interpreter can fall back to the
Domain Pack rules unless `T2D_HF_MODEL_REQUIRED=true` is set.

## Default model and free-hardware target

The default is `Qwen/Qwen2.5-0.5B-Instruct`. It is intentionally small enough for the
16 GB CPU Basic Space environment. The model ID can be changed through the Space variable
`T2D_HF_MODEL_ID` without changing Talk2Data's evidence and verification contracts.

Hugging Face account eligibility determines whether a new compute Space can be created on
CPU Basic or ZeroGPU. This repository never requests paid hardware automatically.

## Build locally

```bash
python -m pip install -e '.[dev]'
python scripts/build_hf_space.py
python scripts/validate_hf_space.py --bundle dist/hf-space
```

The bundle contains the Gradio template and a copy of `src/talk2data`. It deliberately
excludes SQLite state, `.env` files, credentials, caches, and bytecode. A deployment
manifest records the SHA-256 hash of every published file.

## Publish manually

1. Create a Hugging Face write token.
2. Export it without committing it:

```bash
export HF_TOKEN=hf_...
```

3. Build and publish:

```bash
python scripts/build_hf_space.py
python scripts/publish_hf_space.py \
  --space-id yashumani8130/talk2data-conversational-intelligence
```

The script creates a public Gradio Space when permitted by the account and uploads the
validated bundle. It does not request upgraded hardware or enable billing.

## Publish from GitHub Actions

Add the write token as repository secret `HF_TOKEN`. Run the **Publish Talk2Data Hugging
Face Space** workflow and provide the destination Space ID. The workflow validates the
bundle before publishing it.

## Space variables

- `T2D_HF_MODEL_ID`: local model repository ID.
- `T2D_HF_DEVICE`: `auto`, `cpu`, `cuda`, or `mps`.
- `T2D_HF_MODEL_REQUIRED`: fail the request rather than use deterministic fallback.
- `T2D_STATE_DIRECTORY`: disposable session and synthetic database directory.

## Public-data boundary

Only employer-neutral synthetic data and generic telecom terminology are allowed in the
public Space. Do not upload production connection strings, real schemas, customer data,
internal documents, enterprise prompts, or Unified AI Brain content.
