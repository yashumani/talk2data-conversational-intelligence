---
title: Talk2Data Conversational Intelligence
emoji: 📊
colorFrom: indigo
colorTo: green
sdk: gradio
python_version: 3.12
app_file: app.py
fullWidth: true
header: mini
pinned: false
license: apache-2.0
short_description: Governed local-model chat over synthetic telecom data with verification receipts.
preload_from_hub:
  - Qwen/Qwen2.5-0.5B-Instruct
---

# Talk2Data Conversational Intelligence

This Space is the public, synthetic demonstration of Talk2Data. A small open model runs
inside the Space and interprets business language. All metric definitions, authorization,
data execution, calculations, validation, and certified claims remain deterministic.

## Demonstration boundary

- Model: `Qwen/Qwen2.5-0.5B-Instruct` by default, configurable with `T2D_HF_MODEL_ID`.
- Data: synthetic telecommunications facts generated at startup.
- Context: Unified AI Brain integration is intentionally not connected in this Space.
- Persistence: local sessions and SQLite files are disposable and recreated after a restart.
- Security: no production credentials, proprietary schemas, or real customer data belong here.

The model never calculates or certifies a number. It proposes governed identifiers, and
Talk2Data rejects any identifier that does not exist in the approved Domain Pack.
