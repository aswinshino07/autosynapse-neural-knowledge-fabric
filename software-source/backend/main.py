from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Request as FastRequest, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text, create_engine, desc
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

try:
    from sklearn.ensemble import IsolationForest
except Exception:  # optional on tiny edge targets; the robust-statistics fallback stays available
    IsolationForest = None


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "autosynapse.db"
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
FEATURES = ("battery_temp", "pump_current", "pack_current", "voltage", "soc", "speed")
UNITS = {"battery_temp": "°C", "pump_current": "A", "pack_current": "A", "voltage": "V", "soc": "%", "speed": "km/h"}


class Base(DeclarativeBase):
    pass


class RawSample(Base):
    __tablename__ = "raw_samples"
    id = Column(Integer, primary_key=True)
    session_id = Column(String(40), index=True)
    signal = Column(String(40), index=True)
    timestamp = Column(String(40), index=True)
    value = Column(Float, nullable=False)
    unit = Column(String(16), nullable=False)
    quality = Column(String(24), default="good")
    source = Column(String(32), default="SIMULATED")


class EventRecord(Base):
    __tablename__ = "events"
    id = Column(String(40), primary_key=True)
    session_id = Column(String(40), index=True)
    timestamp = Column(String(40), index=True)
    title = Column(String(120), nullable=False)
    event_type = Column(String(48), nullable=False)
    severity = Column(String(16), nullable=False)
    details = Column(Text, default="")
    source = Column(String(32), default="SIMULATED")


class Episode(Base):
    __tablename__ = "episodes"
    id = Column(String(40), primary_key=True)
    session_id = Column(String(40), index=True)
    signal = Column(String(40), index=True)
    pattern = Column(String(32), nullable=False)
    start_time = Column(String(40), index=True)
    end_time = Column(String(40), index=True)
    slope = Column(Float, default=0.0)
    magnitude = Column(Float, default=0.0)
    quality = Column(String(24), default="good")
    source = Column(String(32), default="SIMULATED")


class GraphNode(Base):
    __tablename__ = "graph_nodes"
    id = Column(String(40), primary_key=True)
    session_id = Column(String(40), index=True)
    kind = Column(String(32), index=True)
    label = Column(String(120), nullable=False)
    valid_from = Column(String(40), index=True)
    valid_to = Column(String(40))
    record_time = Column(String(40), nullable=False)
    source = Column(String(32), default="SIMULATED")
    props_json = Column(Text, default="{}")


class GraphEdge(Base):
    __tablename__ = "graph_edges"
    id = Column(String(40), primary_key=True)
    session_id = Column(String(40), index=True)
    src = Column(String(40), index=True)
    dst = Column(String(40), index=True)
    relation = Column(String(40), index=True)
    valid_from = Column(String(40), index=True)
    valid_to = Column(String(40))
    record_time = Column(String(40), nullable=False)
    method = Column(String(24), default="rule")
    score = Column(Float, default=1.0)
    source = Column(String(32), default="SIMULATED")


class AskRequest(BaseModel):
    question: str = Field(min_length=4, max_length=240)
    event_id: str | None = Field(default=None, max_length=40)


class SimulateRequest(BaseModel):
    scenario: str = Field(default="cooling_flow_drop", pattern="^(cooling_flow_drop|sensor_dropout|high_load)$")


app = FastAPI(
    title="AUTOSYNAPSE Neural Knowledge Fabric",
    version="0.1.0",
    description="A simulated, evidence-first automotive investigation prototype.",
    docs_url="/api/docs",
    redoc_url=None,
)
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

_rate_window: dict[str, deque[float]] = defaultdict(deque)
_rate_lock = asyncio.Lock()


@app.middleware("http")
async def bounded_demo_guard(request: FastRequest, call_next):
    request_id = str(uuid.uuid4())[:12]
    request.state.request_id = request_id
    request.state.demo_only = True
    if request.url.path in {"/api/ask", "/api/simulate"}:
        peer = request.client.host if request.client else "unknown"
        now = time.monotonic()
        async with _rate_lock:
            bucket = _rate_window[peer]
            while bucket and now - bucket[0] > 60:
                bucket.popleft()
            if len(bucket) >= 24:
                return JSONResponse(status_code=429, content={"detail": "Demo rate limit reached. Try again in a minute."})
            bucket.append(now)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def add_node(db: Session, session_id: str, kind: str, label: str, valid_from: str, source: str, props: dict[str, Any] | None = None) -> str:
    node_id = f"N-{uuid.uuid4().hex[:10]}"
    db.add(GraphNode(id=node_id, session_id=session_id, kind=kind, label=label, valid_from=valid_from,
                     valid_to=valid_from, record_time=stamp(datetime.now(timezone.utc)), source=source,
                     props_json=json.dumps(props or {}, separators=(",", ":"))))
    return node_id


def add_edge(db: Session, session_id: str, src: str, dst: str, relation: str, valid_from: str, method: str = "rule", score: float = 1.0) -> None:
    db.add(GraphEdge(id=f"E-{uuid.uuid4().hex[:10]}", session_id=session_id, src=src, dst=dst, relation=relation,
                     valid_from=valid_from, valid_to=valid_from, record_time=stamp(datetime.now(timezone.utc)),
                     method=method, score=float(max(0, min(1, score))), source="SIMULATED"))


def create_simulated_session(db: Session, scenario: str = "cooling_flow_drop") -> dict[str, Any]:
    """Generate a labelled synthetic episode. It is not vehicle or benchmark data."""
    session_id = f"SIM-{uuid.uuid4().hex[:8].upper()}"
    event_time = datetime.now(timezone.utc) - timedelta(minutes=1)
    start_time = event_time - timedelta(minutes=59)
    idx = np.arange(60, dtype=float)
    rng = np.random.default_rng(int(uuid.uuid4().hex[:8], 16))
    temp = 31.8 + 0.012 * idx + rng.normal(0, 0.12, size=idx.size)
    pump = 3.45 + rng.normal(0, 0.06, size=idx.size)
    pack_current = 82 + 6 * np.sin(idx / 8) + rng.normal(0, 2.2, size=idx.size)
    voltage = 392 - 0.08 * idx + rng.normal(0, 0.35, size=idx.size)
    soc = 72 - 0.025 * idx + rng.normal(0, 0.08, size=idx.size)
    speed = 55 + 8 * np.sin(idx / 9) + rng.normal(0, 1.6, size=idx.size)
    if scenario == "cooling_flow_drop":
        pump[48:] = np.linspace(3.35, 0.85, 12) + rng.normal(0, 0.04, 12)
        temp[50:] = temp[49] + np.linspace(0.42, 6.3, 10) + rng.normal(0, 0.10, 10)
    elif scenario == "sensor_dropout":
        temp[54:58] = np.nan
        speed[54:58] = np.nan
    else:
        pack_current[48:] = np.linspace(84, 155, 12) + rng.normal(0, 3, 12)
        temp[51:] = temp[50] + np.linspace(0.25, 4.4, 9) + rng.normal(0, 0.1, 9)
    matrix = pd.DataFrame({"battery_temp": temp, "pump_current": pump, "pack_current": pack_current,
                           "voltage": voltage, "soc": soc, "speed": speed})
    matrix = matrix.interpolate(limit_direction="both")
    stamps = [stamp(start_time + timedelta(minutes=int(i))) for i in range(60)]
    session_node = add_node(db, session_id, "session", f"Drive session {session_id}", stamps[0], "SIMULATED", {"scenario": scenario})
    vehicle_node = add_node(db, session_id, "vehicle", "EV-DEMO-01", stamps[0], "SIMULATED", {"identity": "synthetic"})
    add_edge(db, session_id, vehicle_node, session_node, "has_session", stamps[0])
    signal_nodes: dict[str, str] = {}
    for signal in FEATURES:
        signal_nodes[signal] = add_node(db, session_id, "signal", signal.replace("_", " ").title(), stamps[0], "SIMULATED", {"unit": UNITS[signal]})
        add_edge(db, session_id, session_node, signal_nodes[signal], "observes", stamps[0])
        for i, value in enumerate(matrix[signal].to_numpy(dtype=float)):
            db.add(RawSample(session_id=session_id, signal=signal, timestamp=stamps[i], value=float(value),
                             unit=UNITS[signal], quality="interpolated" if pd.isna((temp if signal == "battery_temp" else speed)[i]) and scenario == "sensor_dropout" else "good",
                             source="SIMULATED"))

    event_kind = "BatteryOverTempWarning" if scenario != "sensor_dropout" else "BMSCommunicationGap"
    event_title = "Battery over-temperature warning" if scenario != "sensor_dropout" else "BMS communication gap"
    event_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
    event_ts = stamps[-1]
    db.add(EventRecord(id=event_id, session_id=session_id, timestamp=event_ts, title=event_title,
                       event_type=event_kind, severity="high" if scenario != "sensor_dropout" else "medium",
                       details="Synthetic scenario event; no vehicle data is connected.", source="SIMULATED"))
    event_node = add_node(db, session_id, "event", event_title, event_ts, "SIMULATED", {"event_id": event_id, "severity": "high"})
    add_edge(db, session_id, session_node, event_node, "contains", event_ts)
    add_edge(db, session_id, event_node, signal_nodes["battery_temp"], "references", event_ts)

    for signal in ("battery_temp", "pump_current", "pack_current", "voltage", "speed"):
        values = matrix[signal].to_numpy(dtype=float)
        segment = values[-12:]
        slope = float(np.polyfit(np.arange(segment.size), segment, 1)[0])
        low = float(np.nanmin(segment))
        high = float(np.nanmax(segment))
        if abs(slope) < 0.035:
            pattern = "steady"
        elif slope > 0:
            pattern = "rising"
        else:
            pattern = "falling"
        if signal == "battery_temp" or (signal == "pump_current" and scenario == "cooling_flow_drop"):
            ep_id = f"EP-{uuid.uuid4().hex[:8].upper()}"
            episode = Episode(id=ep_id, session_id=session_id, signal=signal, pattern=pattern,
                              start_time=stamps[48], end_time=stamps[-1], slope=slope, magnitude=high-low,
                              quality="good", source="SIMULATED")
            db.add(episode)
            episode_node = add_node(db, session_id, "episode", f"{signal.replace('_',' ').title()} {pattern}", stamps[48],
                                    "SIMULATED", {"episode_id": ep_id, "slope": round(slope, 4), "unit": UNITS[signal]})
            add_edge(db, session_id, signal_nodes[signal], episode_node, "has_episode", stamps[48])
            add_edge(db, session_id, episode_node, event_node, "precedes", stamps[48], method="statistical", score=0.82 if signal == "pump_current" else 0.93)
            add_edge(db, session_id, episode_node, signal_nodes[signal], "derived_from", stamps[48], method="rule", score=1.0)
    db.commit()
    return {"session_id": session_id, "event_id": event_id, "timestamp": event_ts, "scenario": scenario}


def latest_event(db: Session) -> EventRecord | None:
    return db.query(EventRecord).order_by(desc(EventRecord.timestamp)).first()


def session_samples(db: Session, session_id: str, end_time: str | None = None, minutes: int | None = None) -> list[RawSample]:
    q = db.query(RawSample).filter(RawSample.session_id == session_id)
    if end_time:
        q = q.filter(RawSample.timestamp <= end_time)
    rows = q.order_by(RawSample.timestamp.asc()).all()
    if minutes is not None:
        cut = datetime.fromisoformat((end_time or rows[-1].timestamp).replace("Z", "+00:00")) - timedelta(minutes=minutes)
        rows = [r for r in rows if datetime.fromisoformat(r.timestamp.replace("Z", "+00:00")) >= cut]
    return rows


def summarize_samples(rows: list[RawSample]) -> dict[str, Any]:
    grouped: dict[str, list[RawSample]] = defaultdict(list)
    for row in rows:
        grouped[row.signal].append(row)
    out: dict[str, Any] = {}
    for signal, items in grouped.items():
        out[signal] = [{"t": row.timestamp, "v": round(row.value, 3), "unit": row.unit, "quality": row.quality} for row in items]
    return out


def anomaly_summary(db: Session, session_id: str) -> dict[str, Any]:
    rows = db.query(RawSample).filter(RawSample.session_id == session_id).order_by(RawSample.timestamp.asc()).all()
    frame = pd.DataFrame([{r.signal: r.value for r in rows if r.timestamp == ts} for ts in sorted({r.timestamp for r in rows})])
    frame = frame.reindex(columns=FEATURES).interpolate(limit_direction="both").ffill().bfill()
    if frame.empty:
        return {"available": False, "method": "none", "score": 0.0, "label": "Unknown"}
    method = "Isolation Forest" if IsolationForest is not None and len(frame) >= 24 else "Robust z-score fallback"
    tail = frame.tail(12)
    if method == "Isolation Forest":
        model = IsolationForest(n_estimators=80, contamination=0.10, random_state=7)
        model.fit(frame.to_numpy())
        raw = float(model.decision_function(tail.to_numpy())[-1])
        score = float(max(0.0, min(1.0, 0.5 - raw)))
    else:
        med = frame.median()
        mad = (frame - med).abs().median().replace(0, 1e-6)
        z = ((frame.tail(1).iloc[0] - med).abs() / (1.4826 * mad)).clip(0, 8)
        score = float(max(0.0, min(1.0, (float(z.max()) - 2.0) / 6.0)))
    return {"available": True, "method": method, "score": round(score, 3),
            "label": "Statistical flag" if score >= 0.45 else "No strong flag", "diagnosis": False}


def investigation(db: Session, event: EventRecord, before: int = 10) -> dict[str, Any]:
    before = max(1, min(int(before), 60))
    rows = session_samples(db, event.session_id, event.timestamp, before)
    grouped = summarize_samples(rows)
    temp = grouped.get("battery_temp", [])
    pump = grouped.get("pump_current", [])
    slope = 0.0
    delta_temp = 0.0
    if len(temp) >= 2:
        ys = np.array([x["v"] for x in temp], dtype=float)
        xs = np.arange(len(ys), dtype=float)
        slope = float(np.polyfit(xs, ys, 1)[0])
        delta_temp = float(ys[-1] - ys[0])
    delta_pump = (pump[-1]["v"] - pump[0]["v"]) if len(pump) >= 2 else 0.0
    anomaly = anomaly_summary(db, event.session_id)
    pump_plausible = delta_pump < -0.45 and delta_temp > 1.0
    evidence: list[dict[str, Any]] = []
    if temp:
        evidence.append({"id": "EV-01", "certainty": "Observed", "label": "Battery temperature samples",
                         "value": f"{temp[0]['v']:.1f} → {temp[-1]['v']:.1f} °C",
                         "detail": f"{len(temp)} minute samples in the {before}-minute pre-event window.",
                         "source": "raw_samples:battery_temp", "time": f"{temp[0]['t']} — {temp[-1]['t']}"})
        evidence.append({"id": "EV-02", "certainty": "Derived", "label": "Calculated temperature trend",
                         "value": f"{delta_temp:+.1f} °C total · {slope:+.2f} °C/min",
                         "detail": "Linear slope calculated from the retrieved sample window.",
                         "source": "derived:least_squares_slope", "time": f"{temp[0]['t']} — {temp[-1]['t']}"})
    if pump:
        evidence.append({"id": "EV-03", "certainty": "Observed", "label": "Cooling pump current",
                         "value": f"{pump[0]['v']:.2f} → {pump[-1]['v']:.2f} A",
                         "detail": "Recorded current trend; signal order alone does not prove physical causation.",
                         "source": "raw_samples:pump_current", "time": f"{pump[0]['t']} — {pump[-1]['t']}"})
    evidence.append({"id": "EV-04", "certainty": "Statistical flag", "label": "Multivariate pattern screen",
                     "value": f"{anomaly['label']} · score {anomaly['score']:.2f}",
                     "detail": f"{anomaly['method']}. Anomaly score is a triage signal, not a diagnosis.",
                     "source": "analytics:isolation_forest_or_fallback", "time": event.timestamp})
    if pump_plausible:
        evidence.append({"id": "EV-05", "certainty": "Hypothesis", "label": "Candidate contributor",
                         "value": "Pump-current decline may have contributed to the temperature rise.",
                         "detail": "Ranked using timing, trend co-occurrence and a configured engineering plausibility rule; it is not confirmed causality.",
                         "source": "rule_screen:cooling_flow_drop", "time": event.timestamp})
    else:
        evidence.append({"id": "EV-05", "certainty": "Unknown", "label": "Cause assessment",
                         "value": "Available evidence is insufficient to name a likely contributor.",
                         "detail": "The prototype abstains when a candidate does not clear its evidence threshold.",
                         "source": "abstain:insufficient_evidence", "time": event.timestamp})
    graph_nodes = db.query(GraphNode).filter(GraphNode.session_id == event.session_id).all()
    graph_edges = db.query(GraphEdge).filter(GraphEdge.session_id == event.session_id).all()
    nodes_by_id = {n.id: n for n in graph_nodes}
    graph = {"nodes": [{"id": n.id, "kind": n.kind, "label": n.label, "time": n.valid_from,
                        "source": n.source, "props": json.loads(n.props_json or "{}")}
                       for n in graph_nodes if n.kind in {"vehicle", "session", "event", "episode", "signal"}],
             "edges": [{"id": e.id, "src": e.src, "dst": e.dst, "relation": e.relation,
                        "method": e.method, "score": e.score, "time": e.valid_from}
                       for e in graph_edges if e.src in nodes_by_id and e.dst in nodes_by_id]}
    return {"event": {"id": event.id, "title": event.title, "timestamp": event.timestamp,
                      "severity": event.severity, "session_id": event.session_id, "source": "SIMULATED"},
            "window_minutes": before, "series": grouped, "evidence": evidence,
            "anomaly": anomaly, "graph": graph,
            "status": "DEMO / SIMULATED DATA — not vehicle-validated"}


def llm_status() -> dict[str, Any]:
    url = os.getenv("LLAMA_CPP_URL", "").strip()
    parsed = urlparse(url) if url else None
    local = parsed and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    return {"configured": bool(url and local), "runtime": "llama.cpp", "candidates": ["SmolLM2-360M-Instruct", "Qwen2.5-0.5B-Instruct"],
            "mode": "local endpoint configured" if url and local else "deterministic evidence template",
            "note": "Model weights and ARM performance are not included or benchmarked."}


def local_slm_summary(question: str, case: dict[str, Any]) -> tuple[str, list[str]] | None:
    """Optional llama.cpp paraphrase; remote endpoints and unsupported numeric claims are rejected."""
    status = llm_status()
    base = os.getenv("LLAMA_CPP_URL", "").strip().rstrip("/")
    if not status["configured"] or not base:
        return None
    allowed_ids = {item["id"] for item in case["evidence"]}
    evidence = [{"id": item["id"], "certainty": item["certainty"], "label": item["label"], "value": item["value"]}
                for item in case["evidence"]]
    body = {"model": os.getenv("LLAMA_CPP_MODEL", "SmolLM2-360M-Instruct"), "temperature": 0,
            "max_tokens": 130, "messages": [
                {"role": "system", "content": "Summarize only this evidence. Keep observed facts, derived calculations, statistical flags and hypotheses distinct. Never claim causality, diagnosis, or safety. Cite evidence IDs such as [EV-01]. Do not invent numbers. If uncertain, say so."},
                {"role": "user", "content": json.dumps({"question": question[:240], "evidence": evidence}, separators=(",", ":"))},
            ]}
    request = Request(base + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=2.5) as response:
            payload = json.loads(response.read(180_000))
        text = str(payload["choices"][0]["message"]["content"]).strip()
        refs = re.findall(r"EV-\d{2}", text)
        without_refs = re.sub(r"EV-\d{2}", "", text)
        if not refs or any(ref not in allowed_ids for ref in refs):
            return None
        if re.search(r"\d", without_refs) or re.search(r"\b(proves|proven|confirmed cause|root cause|definitely caused)\b", without_refs, re.I):
            return None
        return text[:900], list(dict.fromkeys(refs))
    except Exception:
        return None


def answer_from_evidence(question: str, case: dict[str, Any]) -> dict[str, Any]:
    ev = {item["id"]: item for item in case["evidence"]}
    parts = []
    if "EV-01" in ev and "EV-02" in ev:
        parts.append({"text": f"The simulated battery-temperature samples rose {ev['EV-02']['value']} before the warning.", "evidence": ["EV-01", "EV-02"]})
    if "EV-03" in ev:
        parts.append({"text": f"Cooling-pump current changed {ev['EV-03']['value']} over the same window.", "evidence": ["EV-03"]})
    if "EV-05" in ev:
        parts.append({"text": ev["EV-05"]["value"], "evidence": ["EV-05"]})
    parts.append({"text": f"The anomaly screen returned {case['anomaly']['label'].lower()} (score {case['anomaly']['score']:.2f}); this is not a diagnosis.", "evidence": ["EV-04"]})
    model = llm_status()
    generated = local_slm_summary(question, case)
    if generated:
        parts = [{"text": generated[0], "evidence": generated[1]}]
        model = model | {"mode": "local llama.cpp summary", "grounding_check": "citations valid; numeric/causal claims screened"}
    else:
        model = model | {"mode": "deterministic evidence template"}
    return {"answer": parts, "intent": "investigate_event", "plan": {"tool": "expand_window", "before_minutes": case["window_minutes"], "event_id": case["event"]["id"]},
            "model": model, "status": case["status"]}


def db_session_to_dict(event: EventRecord) -> dict[str, Any]:
    return {"id": event.id, "session_id": event.session_id, "timestamp": event.timestamp, "title": event.title,
            "type": event.event_type, "severity": event.severity, "details": event.details, "source": "SIMULATED"}


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        if db.query(EventRecord).count() == 0:
            create_simulated_session(db, "cooling_flow_drop")


@app.get("/")
def home():
    return FileResponse(FRONTEND / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "name": "AUTOSYNAPSE", "mode": "simulated demo", "database": "SQLite", "time": stamp(datetime.now(timezone.utc))}


@app.get("/api/model")
def model_status():
    return llm_status()


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    event = latest_event(db)
    if not event:
        return {"sessions": 0, "samples": 0, "events": [], "latest": None, "series": {}}
    samples = session_samples(db, event.session_id)
    case = investigation(db, event, 30)
    times = sorted({row.timestamp for row in samples})
    series: list[dict[str, Any]] = []
    by_key: dict[tuple[str, str], float] = {(r.timestamp, r.signal): r.value for r in samples}
    for ts in times[-45:]:
        series.append({"time": ts, **{signal: round(by_key[(ts, signal)], 3) for signal in FEATURES if (ts, signal) in by_key}})
    event_rows = db.query(EventRecord).order_by(desc(EventRecord.timestamp)).limit(8).all()
    return {"sessions": db.query(GraphNode).filter(GraphNode.kind == "session").count(),
            "samples": db.query(RawSample).count(), "event_count": db.query(EventRecord).count(),
            "flag_count": 1 if case["anomaly"]["score"] >= 0.45 else 0,
            "events": [db_session_to_dict(e) for e in event_rows],
            "latest": {"id": event.id, "title": event.title, "timestamp": event.timestamp, "severity": event.severity,
                       "session_id": event.session_id, "source": "SIMULATED"},
            "series": series, "anomaly": case["anomaly"], "model": llm_status(),
            "privacy": "Synthetic demo telemetry only"}


@app.get("/api/events")
def events(db: Session = Depends(get_db)):
    rows = db.query(EventRecord).order_by(desc(EventRecord.timestamp)).limit(40).all()
    return [db_session_to_dict(e) for e in rows]


@app.get("/api/investigate/{event_id}")
def investigate_event(event_id: str, before: int = 10, db: Session = Depends(get_db)):
    event = db.query(EventRecord).filter(EventRecord.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found in the demo dataset.")
    return investigation(db, event, before)


@app.post("/api/ask")
def ask(payload: AskRequest, db: Session = Depends(get_db)):
    question = payload.question.strip()
    # A bounded natural-language fast path; the user cannot submit SQL or choose an arbitrary tool.
    match = re.search(r"\b(\d{1,2})\s*(?:min|minute|minutes)\b", question.lower())
    before = max(1, min(int(match.group(1)), 60)) if match else 10
    event = db.query(EventRecord).filter(EventRecord.id == payload.event_id).first() if payload.event_id else latest_event(db)
    if not event:
        raise HTTPException(status_code=404, detail="No demo event is available to investigate.")
    case = investigation(db, event, before)
    return answer_from_evidence(question, case) | {"event": case["event"], "evidence": case["evidence"]}


@app.post("/api/simulate")
def simulate(payload: SimulateRequest, db: Session = Depends(get_db)):
    session_count = db.query(GraphNode).filter(GraphNode.kind == "session").count()
    if session_count >= 6:
        raise HTTPException(status_code=429, detail="Demo scenario limit reached. The synthetic dataset is capped at six sessions.")
    return create_simulated_session(db, payload.scenario) | {"message": "Synthetic scenario generated; not a real vehicle reading."}


@app.get("/api/report/{event_id}")
def report(event_id: str, before: int = 10, db: Session = Depends(get_db)):
    event = db.query(EventRecord).filter(EventRecord.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found.")
    case = investigation(db, event, before)
    return {"project": "AUTOSYNAPSE", "generated_at": stamp(datetime.now(timezone.utc)), "data_mode": "SIMULATED",
            "case": case, "disclaimer": "Hypotheses are correlation/rule screens, not confirmed root causes."}


@app.websocket("/api/ws")
async def updates(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            with SessionLocal() as db:
                event = latest_event(db)
                payload = {"time": stamp(datetime.now(timezone.utc)), "latest_event": db_session_to_dict(event) if event else None,
                           "samples": db.query(RawSample).count()}
            await websocket.send_json(payload)
            await asyncio.sleep(5)
    except WebSocketDisconnect:
        return


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")), reload=False)
