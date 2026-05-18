# Audio Recognition

`audio_recognition` provides the web and edge voice-control entrypoint for TurboPi / WonderEchoPro.

## What It Does

- Provides a FastAPI web page for voice-control monitoring.
- Supports two modes: web input and WonderEchoPro capture.
- Proxies audio recognition through `common_api` at `/common/api/asr/transcribe`.
- Routes recognized text to robot movement tasks through the action service.
- Routes expression commands such as `笑一笑` to the face display service.
- Shows latest transcript, task status, camera preview, ASR payloads, and pipeline events.
- Includes a broadcast volume control that writes to `/action/api/settings`.

## Main Files

- `server.py`: cloud-side FastAPI service and dashboard APIs.
- `edge_audio_listener.py`: Raspberry Pi edge listener for WonderEchoPro recording.
- `model_provider.py`: provider-neutral ASR HTTP adapter.
- `voice_intents.py`: voice command alias mapping.
- `face_router.py`: face-display routing helper, with expression duration set to at least 5 seconds.
- `static/`: web UI.

## Runtime Data

Runtime data is intentionally not committed. The service creates `data/results.json`, `data/events.json`, and uploaded audio under `data/uploads/` at runtime.

## Quick Start

```bash
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8095
```

Open the service page and use either text input, uploaded audio, or WonderEchoPro manual capture.
