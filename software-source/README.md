# AUTOSYNAPSE — Temporal Vehicle Intelligence Prototype

An evidence-first demo built from the project's Neural Knowledge Fabric design. It simulates EV telemetry, stores time-stamped samples and graph facts in SQLite, calculates a pre-event window, labels certainty, and returns a traceable investigation in a React dashboard.

## Open the live demo

[Launch AUTOSYNAPSE](https://highway-couples-decades-specialist.trycloudflare.com/)

This is a temporary public link. It stays available while the local app and Cloudflare Quick Tunnel are running. The public instance contains synthetic telemetry only.

## Run locally

1. Install Python 3.10 or newer.
2. In PowerShell, from this folder, run `.install.ps1`.
3. Start it with `.start.ps1`.
4. Open `http://127.0.0.1:8000`. API reference: `http://127.0.0.1:8000/api/docs`.

The app seeds a synthetic cooling-flow-drop scenario on first start. The **Generate scenario** control can add a cooling-flow-drop, sensor-dropout, or high-load sample case. SQLite data is stored in `data/autosynapse.db`.

## What the demo does

- **FastAPI + Pydantic** expose typed dashboard, investigation, simulation, report, health, model-status, and WebSocket routes. Natural-language requests only map to allow-listed tools; there is no free-form SQL endpoint.
- **SQLite + SQLAlchemy** store raw samples, events, signal episodes, temporal graph nodes, and edges. Facts carry valid time, record time, source, method, and score.
- **NumPy + Pandas** prepare sample windows and calculate trends. **scikit-learn Isolation Forest** screens multivariate patterns.
- **React + Tailwind CSS + Plotly** render the dashboard, timeline, evidence cards, and graph view. FastAPI WebSockets provide status updates.
- **llama.cpp** can be connected through a loopback OpenAI-compatible endpoint using `LLAMA_CPP_URL`. The default response uses a deterministic evidence template. If a local model responds, its summary is accepted only with known evidence IDs and after numeric and causal-language screening. SmolLM2/Qwen model weights are not included.
- **python-can** and **CARLA** have explicit optional read-only adapters in `backend/can_adapter.py` and `backend/carla_adapter.py`. Neither adapter is enabled or connected by the public demo.
- The Dockerfile can target Linux, including ARM64. Quantization and target-board profiling require actual hardware; the report's 2 GB / 2-core figures are design targets, not measurements.
- VS Code recommendations live in `.vscode/extensions.json`; `pytest` is listed for future development checks, but this package does not claim test coverage. `scripts/profile_target.sh` records live RAM and API latency on a Linux/ARM target when run there.

## Research features left for follow-up

The prototype uses a compact temporal graph, simple episode segmentation, rule-screened contributor ranking, and Isolation Forest. Learned temporal graph models such as TGN/TGAT, trained embeddings, DBC-based CAN decoding, real vehicle acquisition, fleet scale-out, and on-device ARM benchmarking need labelled data and hardware validation. The demo does not claim root-cause diagnosis.

## Public data boundary

There is no vehicle-log upload endpoint, no VIN collection, and no real vehicle connection. The app sends no telemetry to an external model; an optional SLM endpoint must be loopback-only. Plotly is bundled with its MIT license. The browser loads React, Tailwind, and fonts from public CDNs, so it needs internet access to render those libraries.

To create a temporary link from a machine with `cloudflared` installed, start the app and run:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000 --no-autoupdate
```

For an always-on public service, deploy the Dockerfile to a managed host, use HTTPS, add authentication and persistent storage, and keep real vehicle data behind an access-controlled deployment.

On this workspace, `start_public.ps1` starts the local API plus a hidden Cloudflare Tunnel and prints the new public URL. Run `stop_public.ps1` to stop both.

For an ARM64 image build, use Docker Buildx with `--platform linux/arm64`; verify the dependency wheels and profile the resulting image on the actual target.

## API

- `GET /api/dashboard` — totals, events, current signal series, model status
- `GET /api/events` — recent demo events
- `GET /api/investigate/{event_id}?before=10` — temporal evidence and graph subgraph
- `POST /api/ask` — bounded evidence-first investigation
- `POST /api/simulate` — add one capped synthetic scenario
- `GET /api/report/{event_id}` — JSON investigation export
- `GET /api/health`, `GET /api/model`, `WS /api/ws`

**Prototype 0.1:** the timeline and alerts are generated; anomaly scores are screening outputs; candidate contributors are hypotheses. Do not use this software to service a vehicle or make a safety decision.
