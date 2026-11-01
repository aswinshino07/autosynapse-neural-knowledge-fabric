# AUTOSYNAPSE

**Neural Knowledge Fabric for Temporal Automotive Intelligence and Explainable Vehicle Diagnostics**

AUTOSYNAPSE is a research prototype for evidence-linked analysis of time-stamped electric-vehicle telemetry. It combines a temporal knowledge graph concept, anomaly screening, incident timelines, and explainable investigation views.

> **Prototype boundary:** The current demo uses synthetic telemetry. It is not a validated diagnostic or safety system and should not be used to service a vehicle or make a driving decision.

## Project contents

- `software-source/` — browsable runnable source package: Python API, dashboard, adapters, and configuration. Generated database files and Python bytecode are excluded.
- `AUTOSYNAPSE_SOFTWARE_SOURCE.zip` — downloadable source bundle with the same cleaned files.
- `AUTOSYNAPSE_AI_Presentation.pptx` — editable 10-slide project presentation.
- `references.txt` — research and technical references used in the deck.

## Technology stack

- **Backend:** Python, FastAPI, Pydantic, SQLAlchemy, SQLite, NumPy, Pandas, scikit-learn Isolation Forest
- **Frontend:** React, Tailwind CSS, Plotly
- **Streaming:** FastAPI WebSockets
- **Optional integrations:** llama.cpp over a loopback OpenAI-compatible endpoint, read-only `python-can` and CARLA adapters
- **Deployment:** Docker; Linux and ARM64 are targets that require platform-specific validation

## Run locally

1. Clone this repository and open `software-source/` in PowerShell.
2. Run `.install.ps1`, then `.start.ps1`.
3. Open `http://127.0.0.1:8000`.

The demo seeds a synthetic scenario on first start. Optional model and vehicle adapters remain inactive unless configured. Model weights are not included.

## Live demo

[Open the current demo](https://highway-couples-decades-specialist.trycloudflare.com/). This is a temporary Cloudflare Quick Tunnel link; it stays online only while the local app and tunnel are running.

## Research status

The architecture and presentation describe the proposed Neural Knowledge Fabric. The prototype demonstrates a bounded, evidence-first workflow; it does not establish real-world accuracy, fleet readiness, or hardware performance. The original research PDF is not included.
