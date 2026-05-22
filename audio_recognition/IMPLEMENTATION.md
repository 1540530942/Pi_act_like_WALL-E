# Audio Recognition Implementation Notes

## Goal

Build a self-developed real-data ASR path:

```text
user speech
  -> WonderEchoPro hardware wakeup or browser microphone recording
  -> real WAV audio capture
  -> Project_ASR/online_api real ASR endpoint
  -> recognized text
  -> web display
  -> optional action_move skill routing
```

Only the WonderEchoPro hardware is used on the Raspberry Pi side. The software flow does not depend on Hiwonder speech software; it reads the wakeup frame, records audio with ALSA, and sends that real audio to the configured ASR API.

## No Synthetic Data Policy

- Do not return fabricated transcripts.
- Do not mark a command successful unless the ASR/API/action service returned a real result.
- If recording, ASR, routing, or the robot action fails, surface the failure in `/audio/api/events` and the web UI.
- Voice routing is restricted to a safe allow-list: camera direction, reset, and emergency stop.

## Files

```text
audio_recognition/
  server.py                 Cloud/API service for latest text display and action routing
  edge_audio_listener.py    Pi-side wakeup, record, model call, result upload
  recorder.py               ALSA arecord wrapper
  model_provider.py         Generic HTTP ASR adapter
  skill_router.py           Text -> action_move skill mapping
  config.example.json       Runtime config template
  static/                   Web page for recording, ASR result, and event history
```

## Implemented Flow

- Browser path:
  - `https://www.wangyutang.cn/audio/`
  - records microphone audio in the browser,
  - submits WAV audio to `Project_ASR/online_api`,
  - posts the real transcript to `/audio/api/recognize-text`,
  - optionally creates an action task for the Raspberry Pi.
- Raspberry Pi edge path:
  - waits for WonderEchoPro wakeup,
  - records WAV with `arecord`,
  - sends the audio file to the configured ASR API,
  - uploads the real transcript and pipeline events.

## Manual Test

On Raspberry Pi:

```bash
cd /home/pi/audio_recognition
cp config.example.json config.json
# edit model_provider.endpoint so the Pi can reach the ASR API
python3 edge_audio_listener.py --config config.json --once
```

For cloud display:

```bash
uvicorn server:app --host 0.0.0.0 --port 8095
```

Then open:

```text
https://www.wangyutang.cn/audio/
```

## Current Cloud Endpoints

```text
GET  /audio/api/health
GET  /audio/api/results
POST /audio/api/results
GET  /audio/api/events
POST /audio/api/events
POST /audio/api/recognize-text
GET  /audio/api/intermediate/cases
GET  /audio/api/intermediate/cases/{case_id}
POST /audio/api/intermediate/cases/{case_id}/replay
POST /audio/api/simulate/text
```

## Offline Evaluation And Replay Data

The service keeps evaluation and replay artifacts under `audio_recognition/data/intermediate/`:

```text
data/intermediate/cases.jsonl       append-only case index for ASR, routing, and replay
data/intermediate/latest_case.json  latest captured case for quick inspection
data/intermediate/audio/            copied uploaded or captured audio for replay datasets
```

Each persisted case comes from a real capture, upload, or ASR/result report. It links one pipeline pass with a stable `case_id`, recognized text, optional copied audio, raw ASR payload, planner result, selected skill, and action/face routing outputs. Replay and simulation endpoints run with dispatch disabled and do not create new cases, so synthetic tests do not pollute the evaluation dataset.

Edge capture computes the same planner result with dispatch disabled, then uploads the real audio and ASR payload to the cloud. Cloud `/api/results` owns the actual action/face dispatch, which keeps the real execution path single-owner and avoids double-running commands when the Raspberry Pi is connected.

## ReAct Control Path

The current control path uses a single-tool ReAct protocol:

```text
transcript
  -> DecisionEnvelope
  -> LlmReactAgent
  -> Tool Validator
  -> Safety Guard
  -> Dispatcher
  -> Envelope Store / Replay
```

Files:

```text
envelope.py          DecisionEnvelope / ToolCall / TaskStep
react_agent.py       LLM ReAct agent, one tool_call or finish per turn
tool_validator.py    tool whitelist, skill whitelist, duration clipping/rejection
safety_guard.py      negative instruction rejection, emergency_stop priority, sequence limits
dispatcher.py        dry_run / cloud_queue / local_first-compatible dispatch wrapper
observation_executor.py  get_robot_state / camera_snapshot / ask_confirmation observation path
envelope_store.py    data/envelopes/*.json + index.jsonl
replay.py            replay from text/tool_calls/tasks with dry_run diff
```

Protocol:

```text
protocol_version = react_v1_single_tool
Each LLM turn may return exactly one tool_call or finish.
Bulk tool_calls are rejected and recorded in envelope.errors.
```

Current default behavior keeps existing APIs stable:

```text
/api/recognize-text and /api/results still return the legacy result shape.
route_transcript still returns skill_id/plan/action_task/face_task fields.
The same call now also carries an envelope payload.
Simulation and replay use dry_run and do not create real evaluation samples.
```

Safety notes:

```text
ReAct Agent never controls hardware directly.
Tool calls are validated before becoming tasks.
Emergency commands such as 不要动 / 别动 / 停止 / 急停 bypass the LLM and produce emergency_stop.
Safety Guard can reject or replace tasks before dispatch.
Dispatcher is the only execution layer.
Edge listener plans with dispatch disabled; cloud /api/results remains the current real dispatch owner.
```

Observation path:

```text
camera_snapshot / get_robot_state / ask_confirmation
  -> observation_executor
  -> envelope.observations
  -> tool_result in ReAct messages
  -> next LLM turn
```

`get_robot_state` currently reads the configured action controller `/health` endpoint when available.
`ask_confirmation` records a synchronous pending observation for the prototype path.
`camera_snapshot` requires `camera_server`; missing configuration is recorded as a failed observation instead of being silently ignored.

## ReAct Regression Check

When the LLM is being deployed, run the checks that do not require the model:

```bash
python audio_recognition/react_regression_check.py --skip-llm --action-server http://127.0.0.1:18765
```

After qwen3.5-9b is available through the LV tunnel:

```bash
python audio_recognition/react_regression_check.py \
  --llm-endpoint http://127.0.0.1:18002/v1/chat/completions \
  --action-server http://127.0.0.1:18765
```

For real Pi execution, add `--real`. The script performs an emergency stop before and after real execution:

```bash
python audio_recognition/react_regression_check.py \
  --llm-endpoint http://127.0.0.1:18002/v1/chat/completions \
  --action-server http://127.0.0.1:18765 \
  --real
```

## Deployment Direction

- Run `server.py` on Tencent Cloud behind `/audio/`.
- Run `edge_audio_listener.py` on Raspberry Pi as a systemd service after manual testing.
- Keep ASR API credentials in environment variables or private config files.
- When the ASR API runs on the laptop, the Raspberry Pi config must use the laptop LAN IP, not `127.0.0.1`.
