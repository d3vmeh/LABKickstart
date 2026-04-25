from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .runs import RunStore
from .sensors import MockSensor, Sample, SensorSource

STATIC = Path(__file__).parent / "static"


class Hub:
    """Owns the sensor source, the run store, and live subscribers."""

    def __init__(self, source: SensorSource):
        self.source = source
        self.runs = RunStore()
        self._subscribers: set[asyncio.Queue[dict]] = set()
        self._task: asyncio.Task | None = None

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
            if self.runs.active is not None:
                self.runs.write(sample)
            payload = {
                "device_id": sample.device_id,
                "t": sample.t,
                "channel": sample.channel,
                "value": sample.value,
            }
            for q in list(self._subscribers):
                if q.full():
                    continue  # drop for slow clients
                q.put_nowait(payload)

    def subscribe(self) -> asyncio.Queue[dict]:
        q: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict]) -> None:
        self._subscribers.discard(q)


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub = Hub(MockSensor())
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


@app.get("/api/runs")
async def list_runs() -> dict:
    hub: Hub = app.state.hub
    return {"active": hub.runs.active.to_json() if hub.runs.active else None,
            "runs": hub.runs.list()}


@app.post("/api/arm")
async def arm(payload: dict) -> dict:
    hub: Hub = app.state.hub
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
