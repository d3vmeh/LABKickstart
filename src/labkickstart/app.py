from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .kits import Kit, build_registry
from .runs import RunStore
from .sensors import MockPhotogateSensor, MockSensor, Sample, SensorSource

STATIC = Path(__file__).parent / "static"


def _broadcast_payload(s: Sample) -> dict:
    return {"device_id": s.device_id, "t": s.t, "channel": s.channel, "value": s.value}


class Hub:
    """Owns the sensor source, run store, the active kit, and live subscribers."""

    def __init__(self, source: SensorSource):
        self.source = source
        self.runs = RunStore()
        self.kits: dict[str, Kit] = build_registry()
        self.active_kit_id: str | None = None
        self.active_kit_params: dict = {}
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._task: asyncio.Task | None = None

    @property
    def active_kit(self) -> Kit | None:
        return self.kits.get(self.active_kit_id) if self.active_kit_id else None

    def configure_kit(self, kit_id: str, params: dict) -> None:
        if kit_id not in self.kits:
            raise KeyError(f"unknown kit: {kit_id}")
        self.kits[kit_id].configure(params)
        self.active_kit_id = kit_id
        self.active_kit_params = dict(params)

    async def start(self) -> None:
        self._task = asyncio.create_task(self._pump())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _pump(self) -> None:
        async for sample in self.source.stream():
            self._dispatch(sample)
            kit = self.active_kit
            if kit is not None:
                for derived in kit.derive(sample):
                    self._dispatch(derived)

    def _dispatch(self, sample: Sample) -> None:
        if self.runs.active is not None:
            self.runs.write(sample)
        payload = _broadcast_payload(sample)
        for q in list(self._subscribers):
            if q.full():
                continue
            q.put_nowait(payload)

    def subscribe(self) -> asyncio.Queue[dict]:
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(q)


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub = Hub(MockPhotogateSensor())
    app.state.hub = hub
    await hub.start()
    try:
        yield
    finally:
        await hub.stop()


app = FastAPI(title="LABKickstart", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text())


@app.get("/api/devices")
async def devices():
    hub: Hub = app.state.hub
    return [
        {"device_id": d.device_id, "name": d.name, "rssi": d.rssi, "connected": d.connected}
        for d in hub.source.devices()
    ]


@app.get("/api/kits")
async def list_kits() -> dict:
    hub: Hub = app.state.hub
    return {
        "kits": [k.info.to_json() for k in hub.kits.values()],
        "active": (
            {"id": hub.active_kit_id, "params": hub.active_kit_params}
            if hub.active_kit_id else None
        ),
    }


@app.post("/api/kit")
async def set_kit(payload: dict) -> dict:
    hub: Hub = app.state.hub
    if hub.runs.active is not None:
        raise HTTPException(status_code=409, detail="cannot change kit during a run")
    kit_id = (payload or {}).get("id")
    params = (payload or {}).get("params") or {}
    if not kit_id:
        raise HTTPException(status_code=400, detail="id is required")
    try:
        hub.configure_kit(kit_id, params)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": hub.active_kit_id, "params": hub.active_kit_params}


@app.get("/api/runs")
async def list_runs() -> dict:
    hub: Hub = app.state.hub
    return {"active": hub.runs.active.to_json() if hub.runs.active else None,
            "runs": hub.runs.list()}


@app.post("/api/arm")
async def arm(payload: dict) -> dict:
    hub: Hub = app.state.hub
    if hub.active_kit is None:
        raise HTTPException(status_code=409, detail="select a kit before arming")
    name = (payload or {}).get("name", "run")
    try:
        run = hub.runs.start(name)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return run.to_json()


@app.post("/api/stop")
async def stop() -> dict:
    hub: Hub = app.state.hub
    run = hub.runs.stop()
    if run is None:
        raise HTTPException(status_code=409, detail="no active run")
    return run.to_json()


@app.delete("/api/runs")
async def delete_all_runs() -> dict:
    hub: Hub = app.state.hub
    try:
        deleted = hub.runs.delete_all()
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"deleted": deleted}


@app.get("/api/runs/{run_id}/csv")
async def run_csv(run_id: str):
    hub: Hub = app.state.hub
    p = hub.runs.path_for(run_id)
    if p is None:
        raise HTTPException(status_code=404, detail="run not found")
    return FileResponse(p, media_type="text/csv", filename=p.name)


@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket) -> None:
    await ws.accept()
    hub: Hub = ws.app.state.hub
    q = hub.subscribe()
    try:
        while True:
            payload = await q.get()
            await ws.send_text(json.dumps(payload))
    except WebSocketDisconnect:
        pass
    finally:
        hub.unsubscribe(q)
