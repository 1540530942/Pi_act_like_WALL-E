from __future__ import annotations

import base64
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Annotated, Any

import requests
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from face_router import create_face_task, is_face_skill
from skill_router import create_action_task
from voice_intents import resolve_voice_intent


BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
RESULTS_FILE = DATA_DIR / "results.json"
EVENTS_FILE = DATA_DIR / "events.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
TOKEN_FILE = DATA_DIR / ".audio_token"
ACTION_CATALOG_PATH = (BASE_DIR / "../action_move/skill_catalog.json").resolve()
ACTION_SERVER = os.getenv("AUDIO_ACTION_SERVER", "http://action-move:8094")
FACE_SERVER = os.getenv("AUDIO_FACE_SERVER", "http://127.0.0.1:8096")
CAMERA_SERVER = os.getenv("AUDIO_CAMERA_SERVER", "http://camera-snapshot:8099")
COMMON_ASR_URL = os.getenv("COMMON_ASR_URL", "https://www.wangyutang.cn/common/api/asr/transcribe")
MAX_RESULTS = 100
MAX_EVENTS = 200
MAX_DASHBOARD_RESULTS = 40
MAX_DASHBOARD_EVENTS = 60
DATA_LOCK = threading.Lock()
HTTP_TIMEOUT_SECONDS = 3.0

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="TurboPi Audio Recognition", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class AudioResult(BaseModel):
    device_id: str = Field("turbopi-01", max_length=80)
    text: str = Field("", max_length=2000)
    wav_path: str = Field("", max_length=500)
    skill_id: str = Field("", max_length=80)
    audio_base64: str = Field("", max_length=12000000)
    audio_mime: str = Field("audio/wav", max_length=120)
    audio_filename: str = Field("", max_length=255)
    audio_url: str = Field("", max_length=500)
    audio_duration_seconds: float = 0.0
    raw: dict[str, Any] = Field(default_factory=dict)
    reported_at: float = 0.0


class PipelineEvent(BaseModel):
    device_id: str = Field("turbopi-01", max_length=80)
    stage: str = Field(..., max_length=80)
    status: str = Field("ok", max_length=40)
    message: str = Field("", max_length=500)
    details: dict[str, Any] = Field(default_factory=dict)
    reported_at: float = 0.0


class TextCommand(BaseModel):
    device_id: str = Field("web-audio", max_length=80)
    text: str = Field(..., max_length=2000)
    wav_path: str = Field("", max_length=500)
    source: str = Field("web-recording", max_length=80)
    route_action: bool = True
    raw: dict[str, Any] = Field(default_factory=dict)


class AudioSettings(BaseModel):
    input_mode: str = Field("wonderechopro", pattern="^(web_input|wonderechopro)$")
    manual_recording_enabled: bool = False


DEFAULT_SETTINGS = {
    "input_mode": "wonderechopro",
    "manual_recording_enabled": False,
}


def expected_token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    return ""


def require_token(x_audio_token: Annotated[str | None, Header()] = None) -> None:
    expected = expected_token()
    if not expected:
        return
    if not x_audio_token or not secrets.compare_digest(x_audio_token, expected):
        raise HTTPException(status_code=401, detail="invalid audio token")


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        try:
            data, _ = json.JSONDecoder().raw_decode(text)
        except json.JSONDecodeError:
            backup = path.with_suffix(f"{path.suffix}.corrupt-{int(time.time())}.bak")
            path.replace(backup)
            return []
    return data if isinstance(data, list) else []


def write_json_list(path: Path, items: list[dict[str, Any]], limit: int) -> None:
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(items[-limit:], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def load_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULT_SETTINGS)
    merged = {**DEFAULT_SETTINGS, **data}
    return AudioSettings(**merged).model_dump()


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    normalized = AudioSettings(**{**load_settings(), **settings}).model_dump()
    tmp_path = SETTINGS_FILE.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(SETTINGS_FILE)
    return normalized


def load_results() -> list[dict[str, Any]]:
    return load_json_list(RESULTS_FILE)


def load_events() -> list[dict[str, Any]]:
    return load_json_list(EVENTS_FILE)


def save_results(results: list[dict[str, Any]]) -> None:
    write_json_list(RESULTS_FILE, results, MAX_RESULTS)


def save_events(events: list[dict[str, Any]]) -> None:
    write_json_list(EVENTS_FILE, events, MAX_EVENTS)


def append_event(item: dict[str, Any]) -> dict[str, Any]:
    if not item.get("reported_at"):
        item["reported_at"] = time.time()
    with DATA_LOCK:
        events = load_events()
        events.append(item)
        save_events(events)
    return item


def append_result(item: dict[str, Any]) -> dict[str, Any]:
    if not item.get("reported_at"):
        item["reported_at"] = time.time()
    with DATA_LOCK:
        results = load_results()
        results.append(item)
        save_results(results)
    return item


def sanitize_audio_filename(name: str) -> str:
    candidate = Path(name or "recording.wav").name
    suffix = Path(candidate).suffix.lower()
    if suffix in {".wav", ".mp3", ".ogg", ".m4a", ".flac"}:
        return candidate
    stem = Path(candidate).stem or "recording"
    return f"{stem}.wav"


def save_embedded_audio(payload: dict[str, Any]) -> tuple[str, float]:
    audio_base64 = str(payload.get("audio_base64") or "").strip()
    if not audio_base64:
        return str(payload.get("audio_url") or ""), float(payload.get("audio_duration_seconds") or 0.0)

    try:
        content = base64.b64decode(audio_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid audio_base64 payload: {exc}") from exc

    filename = sanitize_audio_filename(str(payload.get("audio_filename") or payload.get("wav_path") or "recording.wav"))
    stored_name = f"{int(time.time() * 1000)}-{secrets.token_hex(4)}-{filename}"
    stored_path = UPLOADS_DIR / stored_name
    stored_path.write_bytes(content)

    duration = float(payload.get("audio_duration_seconds") or 0.0)
    if duration <= 0 and stored_path.suffix.lower() == ".wav":
        try:
            with wave.open(str(stored_path), "rb") as handle:
                frames = handle.getnframes()
                rate = handle.getframerate()
            duration = frames / rate if rate else 0.0
        except wave.Error:
            duration = 0.0

    payload["audio_base64"] = ""
    payload["audio_filename"] = filename
    payload["audio_url"] = f"/audio/api/audio/{stored_name}"
    payload["audio_duration_seconds"] = duration
    return payload["audio_url"], duration


def resolve_audio_intent(text: str) -> dict[str, Any] | None:
    return resolve_voice_intent(text, ACTION_CATALOG_PATH)


def fetch_json(url: str) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_bytes(url: str) -> tuple[bytes, str]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"Accept": "image/jpeg,application/json"})
    with opener.open(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read(), response.headers.get("content-type") or "application/octet-stream"


def action_snapshot() -> dict[str, Any]:
    base = ACTION_SERVER.rstrip("/")
    snapshot: dict[str, Any] = {
        "server": ACTION_SERVER,
        "online": False,
        "health": None,
        "tasks": [],
        "error": "",
    }
    if not base:
        snapshot["error"] = "AUDIO_ACTION_SERVER is empty"
        return snapshot
    try:
        snapshot["health"] = fetch_json(f"{base}/api/health")
        tasks_payload = fetch_json(f"{base}/api/tasks")
        snapshot["tasks"] = tasks_payload.get("tasks", [])
        snapshot["online"] = True
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        snapshot["error"] = str(exc)
    return snapshot


def camera_snapshot() -> dict[str, Any]:
    base = CAMERA_SERVER.rstrip("/")
    snapshot: dict[str, Any] = {
        "server": CAMERA_SERVER,
        "online": False,
        "health": None,
        "latest": None,
        "control": None,
        "error": "",
    }
    if not base:
        snapshot["error"] = "AUDIO_CAMERA_SERVER is empty"
        return snapshot
    try:
        snapshot["health"] = fetch_json(f"{base}/api/health")
        snapshot["latest"] = fetch_json(f"{base}/api/latest")
        snapshot["control"] = fetch_json(f"{base}/api/control")
        snapshot["online"] = True
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        snapshot["error"] = str(exc)
    return snapshot


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict[str, Any]:
    results = load_results()
    events = load_events()
    latest = results[-1] if results else None
    latest_event = events[-1] if events else None
    age = time.time() - float(latest.get("reported_at") or 0) if latest else 0
    return {
        "status": "ok",
        "service": "TurboPi Audio Recognition",
        "has_result": bool(latest),
        "latest": latest,
        "latest_event": latest_event,
        "age_seconds": age,
    }


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    results = load_results()
    events = load_events()
    latest = results[-1] if results else None
    latest_event = events[-1] if events else None
    age = time.time() - float(latest.get("reported_at") or 0) if latest else 0
    return {
        "status": "ok",
        "service": "TurboPi Audio Recognition",
        "action_server": ACTION_SERVER,
        "latest": latest,
        "latest_event": latest_event,
        "age_seconds": age,
        "results": list(reversed(results[-MAX_DASHBOARD_RESULTS:])),
        "events": list(reversed(events[-MAX_DASHBOARD_EVENTS:])),
        "action": action_snapshot(),
        "camera": camera_snapshot(),
        "settings": load_settings(),
        "server_time": time.time(),
    }


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    return {"settings": load_settings()}


@app.post("/api/settings")
def update_settings(payload: AudioSettings, x_audio_token: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    require_token(x_audio_token)
    updates = payload.model_dump(exclude_unset=True) if hasattr(payload, "model_dump") else payload.dict(exclude_unset=True)
    settings = save_settings(updates)
    append_event(
        {
            "device_id": "cloud",
            "stage": "input_mode",
            "status": "ok",
            "message": f"input mode updated to {settings['input_mode']}",
            "details": settings,
            "reported_at": time.time(),
        }
    )
    return {"ok": True, "settings": settings}


@app.post("/api/manual-recording/start")
def start_manual_recording(x_audio_token: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    require_token(x_audio_token)
    settings = save_settings({"manual_recording_enabled": True})
    append_event(
        {
            "device_id": "cloud",
            "stage": "manual_recording",
            "status": "running",
            "message": "manual WonderEchoPro recording started",
            "details": settings,
            "reported_at": time.time(),
        }
    )
    return {"ok": True, "settings": settings}


@app.post("/api/manual-recording/stop")
def stop_manual_recording(x_audio_token: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    require_token(x_audio_token)
    settings = save_settings({"manual_recording_enabled": False})
    append_event(
        {
            "device_id": "cloud",
            "stage": "manual_recording",
            "status": "stopped",
            "message": "manual WonderEchoPro recording stopped",
            "details": settings,
            "reported_at": time.time(),
        }
    )
    return {"ok": True, "settings": settings}


@app.post("/api/tasks/clear")
def clear_action_tasks() -> dict[str, Any]:
    try:
        return post_json(f"{ACTION_SERVER.rstrip('/')}/api/tasks/clear", {})
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"failed to clear action tasks: {exc}") from exc


@app.post("/api/camera/open")
def open_camera() -> dict[str, Any]:
    try:
        return post_json(f"{CAMERA_SERVER.rstrip('/')}/api/capture", {"mode": "continuous", "interval_ms": 1000})
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"failed to open camera: {exc}") from exc


@app.post("/api/camera/close")
def close_camera() -> dict[str, Any]:
    try:
        return post_json(f"{CAMERA_SERVER.rstrip('/')}/api/stop", {})
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail=f"failed to close camera: {exc}") from exc


@app.get("/api/camera/latest.jpg")
def latest_camera_image() -> Response:
    try:
        content, content_type = fetch_bytes(f"{CAMERA_SERVER.rstrip('/')}/api/latest.jpg")
        return Response(content=content, media_type=content_type, headers={"Cache-Control": "no-store"})
    except urllib.error.HTTPError as exc:
        raise HTTPException(status_code=exc.code, detail="camera image unavailable") from exc
    except (OSError, urllib.error.URLError) as exc:
        raise HTTPException(status_code=502, detail=f"failed to fetch camera image: {exc}") from exc


@app.get("/api/results")
def list_results() -> dict[str, Any]:
    return {"results": list(reversed(load_results()))}


@app.get("/api/audio/{name}")
def get_uploaded_audio(name: str) -> FileResponse:
    safe_name = Path(name).name
    target = (UPLOADS_DIR / safe_name).resolve()
    if target.parent != UPLOADS_DIR.resolve() or not target.exists():
        raise HTTPException(status_code=404, detail="audio not found")
    media_type = "audio/wav" if target.suffix.lower() == ".wav" else "application/octet-stream"
    return FileResponse(target, media_type=media_type, filename=safe_name, headers={"Cache-Control": "no-store"})


@app.get("/api/events")
def list_events() -> dict[str, Any]:
    return {"events": list(reversed(load_events()))}


@app.post("/api/results")
def add_result(payload: AudioResult, x_audio_token: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    require_token(x_audio_token)
    item = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    text = str(item.get("text") or "").strip()
    skill = resolve_audio_intent(text) if text and text != "noise_or_unrecognized_audio" else None
    face_task: dict[str, Any] | None = None
    face_error = ""
    if skill and is_face_skill(skill["id"]):
        item["skill_id"] = skill["id"]
        try:
            face_task = create_face_task(FACE_SERVER, skill["id"], text, source="audio_result")
            append_event(
                {
                    "device_id": item.get("device_id") or "turbopi-01",
                    "stage": "face_route",
                    "status": "ok",
                    "message": f"routed result to face {skill['id']}",
                    "details": {"state": face_task.get("state", face_task)},
                    "reported_at": time.time(),
                }
            )
        except Exception as exc:  # noqa: BLE001 - keep uploaded result even if display route fails
            face_error = str(exc)
            append_event(
                {
                    "device_id": item.get("device_id") or "turbopi-01",
                    "stage": "face_route",
                    "status": "failed",
                    "message": face_error,
                    "details": {"skill_id": skill["id"]},
                    "reported_at": time.time(),
                }
            )
        raw = item.get("raw") if isinstance(item.get("raw"), dict) else {}
        item["raw"] = {**raw, "face_task": face_task, "face_error": face_error}
    save_embedded_audio(item)
    append_result(item)
    return {"ok": True, "result": item, "skill": skill, "face_task": face_task, "face_error": face_error}


@app.post("/api/events")
def add_event(payload: PipelineEvent, x_audio_token: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    require_token(x_audio_token)
    item = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    append_event(item)
    return {"ok": True, "event": item}


@app.post("/api/asr/transcribe")
async def proxy_asr_transcribe(
    file: UploadFile = File(...),
    language: str = Form("zh"),
) -> dict[str, Any]:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty audio file")

    endpoint = COMMON_ASR_URL
    data = {"language": language or "zh"}
    files = {"file": (file.filename or "recording.wav", content, file.content_type or "audio/wav")}
    try:
        response = requests.post(endpoint, data=data, files=files, timeout=180)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        append_event(
            {
                "device_id": "web-audio",
                "stage": "model_asr",
                "status": "failed",
                "message": f"ASR proxy failed: {exc}",
                "details": {"provider": "common_api", "endpoint": endpoint},
                "reported_at": time.time(),
            }
        )
        raise HTTPException(status_code=502, detail=f"ASR proxy failed: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="ASR provider returned non-JSON response") from exc

    payload.setdefault("provider", "common_api")
    payload.setdefault("endpoint", endpoint)
    return payload


@app.post("/api/recognize-text")
def recognize_text(payload: TextCommand, x_audio_token: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    require_token(x_audio_token)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty recognized text")

    append_event(
        {
            "device_id": payload.device_id,
            "stage": "model_asr",
            "status": "ok",
            "message": "recognized text received from real ASR API",
            "details": {"source": payload.source, "text": text},
            "reported_at": time.time(),
        }
    )

    skill = resolve_audio_intent(text)
    action_task: dict[str, Any] | None = None
    face_task: dict[str, Any] | None = None
    action_error = ""
    face_error = ""
    if skill and payload.route_action:
        skill_id = skill["id"]
        if is_face_skill(skill_id):
            try:
                face_task = create_face_task(FACE_SERVER, skill_id, text, source="audio_recognition")
                append_event(
                    {
                        "device_id": payload.device_id,
                        "stage": "face_route",
                        "status": "ok",
                        "message": f"routed text to face {skill_id}",
                        "details": {"state": face_task.get("state", face_task)},
                        "reported_at": time.time(),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - surface routing failure in UI
                face_error = str(exc)
                append_event(
                    {
                        "device_id": payload.device_id,
                        "stage": "face_route",
                        "status": "failed",
                        "message": face_error,
                        "details": {"skill_id": skill_id},
                        "reported_at": time.time(),
                    }
                )
        else:
            try:
                action_task = create_action_task(ACTION_SERVER, skill_id, source="audio_recognition")
                append_event(
                    {
                        "device_id": payload.device_id,
                        "stage": "action_route",
                        "status": "ok",
                        "message": f"routed text to action {skill_id}",
                        "details": {"task": action_task.get("task", action_task)},
                        "reported_at": time.time(),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - surface routing failure in UI
                action_error = str(exc)
                append_event(
                    {
                        "device_id": payload.device_id,
                        "stage": "action_route",
                        "status": "failed",
                        "message": action_error,
                        "details": {"skill_id": skill_id},
                        "reported_at": time.time(),
                    }
                )
    elif not skill:
        append_event(
            {
                "device_id": payload.device_id,
                "stage": "skill_route",
                "status": "skipped",
                "message": "no matching voice skill",
                "details": {"text": text},
                "reported_at": time.time(),
            }
        )

    result = append_result(
        {
            "device_id": payload.device_id,
            "text": text,
            "wav_path": payload.wav_path,
            "skill_id": skill["id"] if skill else "",
            "raw": {
                **payload.raw,
                "source": payload.source,
                "action_task": action_task,
                "action_error": action_error,
                "face_task": face_task,
                "face_error": face_error,
            },
            "reported_at": time.time(),
        }
    )
    return {
        "ok": True,
        "result": result,
        "skill": skill,
        "action_task": action_task,
        "action_error": action_error,
        "face_task": face_task,
        "face_error": face_error,
    }
