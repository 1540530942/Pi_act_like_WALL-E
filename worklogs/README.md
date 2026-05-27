# TurboPi Audio Recognition

## Local Deployment

The deployed project is self-contained in this directory:

```text
C:\Users\Administrator\Desktop\Workspace\Project_Codex\wangyutang_platform\audio_recognition
```

Start the visualization/API service from this directory:

```powershell
$env:AUDIO_ACTION_SERVER="http://127.0.0.1:8094"
python -m uvicorn server:app --host 0.0.0.0 --port 8095
```

Open the monitoring page:

```text
http://127.0.0.1:8095/
```

The page refreshes every 2 seconds and shows:

- WonderEchoPro/edge listener recording and ASR events.
- Latest recognized text and matched `action_move` skill.
- Browser recording/upload test input.
- `action_move` health, Raspberry Pi online state, and task execution results.

The main aggregation endpoint is:

```text
GET /api/dashboard
```

This module records the current WonderEchoPro voice status on the Raspberry Pi and the preferred self-developed plan for connecting a future multimodal model.

The intended architecture uses only the WonderEchoPro hardware. The wakeup listener, recorder, model adapter, result upload, and visualization are self-developed in this module.

## Current Status

Checked on Raspberry Pi `192.168.137.2`, inside Docker container `turbopi`.

Hardware and runtime observations:

- WonderEchoPro-compatible serial device is present as `/dev/ttyUSB0`.
- The `ubuntu` user inside `turbopi` can read and write `/dev/ttyUSB0` through the `dialout` group.
- USB audio capture device is present:
  - `USB PnP Audio Device`
  - ALSA capture card: `card 2, device 0`
- `arecord` can capture audio successfully:
  - `arecord -D plughw:CARD=Device,DEV=0 -f S16_LE -r 16000 -c 1 -d 1 /tmp/test_mic.wav`
  - Output was a valid 16 kHz mono WAV file.
- ROS2 package `large_models` is installed under:
  - `/home/ubuntu/ros2_ws/src/large_models`
  - `/home/ubuntu/ros2_ws/install/large_models`
- Python package `speech` is installed for the container `ubuntu` user:
  - `/home/ubuntu/.local/lib/python3.10/site-packages/speech`

Important runtime detail:

- `vocal_detect` must be started as the `ubuntu` user in the container.
- Starting it as root fails because root cannot import the `speech` module from `ubuntu`'s local site-packages.

Working launch command:

```bash
docker exec -u ubuntu turbopi bash -lc '
  export ASR_LANGUAGE=Chinese
  source /opt/ros/humble/setup.bash
  source /home/ubuntu/ros2_ws/install/setup.bash
  ros2 launch large_models vocal_detect.launch.py awake_method:=WonderEchoPro enable_wakeup:=true mode:=1
'
```

Successful startup evidence:

```text
[vocal_detect]: Rate:48000 Size:3200 Channel:2 Device:hw:2,0
[vocal_detect]: start
```

ROS2 topics exposed while running:

```text
/vocal_detect/angle
/vocal_detect/asr_result
/vocal_detect/wakeup
```

ROS2 services exposed while running:

```text
/vocal_detect/enable_wakeup
/vocal_detect/set_mode
/vocal_detect/init_finish
```

## Verified Wakeup Path

`speech.awake.WonderEchoPro` treats the following serial frame as a wakeup event:

```text
aa 55 03 00 fb
```

A pseudo-terminal test injected that frame into `vocal_detect`, and the node published:

```text
/vocal_detect/wakeup
data: true
```

The node then entered the ASR phase:

```text
[vocal_detect]: asr...
```

This proves the WonderEchoPro serial wakeup path and ROS2 wakeup publication path are usable.

## Current Failure Point

The current built-in ASR path uses DashScope for Chinese recognition. It fails because the configured API key is empty or invalid.

Observed error:

```text
RecognitionCallback error: {"status_code": 401, "code": 401, "message": "Unauthorized, your api-key is invalid!"}
dashscope.common.error.InvalidParameter: Speech recognition has stopped.
```

This is not a WonderEchoPro hardware problem. The confirmed working pieces are:

- Serial wakeup.
- ROS2 `vocal_detect` startup.
- ROS2 wakeup topic publication.
- Microphone capture.

The missing piece is a valid ASR provider or a replacement ASR implementation.

## Recommended Self-Developed Plan

Prefer a small custom module instead of depending on the tutorial's all-in-one `large_models` ASR flow.

Target design:

```text
WonderEchoPro serial wakeup
  -> local recorder captures WAV
  -> multimodal model transcribes and understands intent
  -> normalized command is matched to action_move skills
  -> cloud action task or local ROS2 action executor runs the skill
  -> camera snapshot is requested for visual confirmation
```

This keeps hardware control local and bounded, while letting the future multimodal model handle speech recognition and intent parsing.

## Proposed Components

### 1. Edge Wakeup Listener

Runs on Raspberry Pi, inside or beside the `turbopi` container.

Responsibilities:

- Open `/dev/ttyUSB0` at `115200`.
- Wait for WonderEchoPro frame `aa 55 03 00 fb`.
- Debounce repeated wakeups.
- Trigger recording.
- Avoid taking over motion control directly.

### 2. Local Audio Recorder

Use ALSA directly for predictable capture:

```bash
arecord -D plughw:CARD=Device,DEV=0 -f S16_LE -r 16000 -c 1 -d 4 /tmp/wonderecho_command.wav
```

Recommended defaults:

- Sample rate: `16000`
- Channels: `1`
- Format: `S16_LE`
- Duration: `3..5` seconds
- Add optional voice activity detection later to stop early.

### 3. Multimodal Model Adapter

When the user provides the model, implement a provider-neutral adapter:

```python
class AudioUnderstandingProvider:
    def transcribe_and_parse(self, wav_path: str, image_path: str | None = None) -> dict:
        ...
```

Expected normalized output:

```json
{
  "text": "鍚戝乏鐪?,
  "intent": "robot_action",
  "skill_id": "look_left",
  "confidence": 0.92,
  "needs_confirmation": false
}
```

The adapter should support:

- Audio-only commands.
- Optional latest camera image as visual context.
- Strict JSON response validation.
- Timeout and retry.
- Logging raw transcript and normalized skill.

### 4. Skill Router

Map model output to the existing `action_move/skill_catalog.json`.

Rules:

- Only allow skills listed in the catalog.
- Reject unknown, low-confidence, or unsafe commands.
- Keep movement bounded by existing `action_move` defaults.
- Always rely on `action_move_executor.py` for ROS2 motion publishing.

Initial allowed skills:

```text
emergency_stop
reset_pose
look_left
look_right
look_up
look_down
move_forward
move_backward
move_left
move_right
turn_left
turn_right
```

### 5. Execution Path

Two viable execution modes:

Local-first:

```text
audio_recognition edge service -> action_move_executor.py -> ROS2
```

Cloud-mediated:

```text
audio_recognition edge service -> https://www.wangyutang.cn/action/api/tasks -> action_move edge poller -> ROS2
```

Recommended default: cloud-mediated.

Reason:

- Reuses the existing action queue.
- Keeps `/action/` page status and history consistent.
- Gives the user visibility into online state and latest task result.

### 6. Visual Confirmation

After a command executes:

- Request `/camera/api/capture` if available.
- Compare before/after images for motion and servo validation where useful.
- Store the latest command, transcript, skill, and snapshot path.

This can later support commands like:

```text
鐪嬩竴涓嬪乏杈规湁娌℃湁闅滅鐗?寰€鍓嶈蛋涓€鐐癸紝濡傛灉鍓嶉潰瀹夊叏
```

## Proposed File Layout

```text
audio_recognition/
  README.md
  edge_audio_listener.py
  model_provider.py
  recorder.py
  skill_router.py
  config.example.json
  systemd/
    turbopi-audio-recognition.service
```

## Deployment Notes

The service should run as the container `ubuntu` user or as a host process with access to:

- `/dev/ttyUSB0`
- ALSA capture device `plughw:CARD=Device,DEV=0`
- Network access to the multimodal model provider
- Network access to `https://www.wangyutang.cn/action`
- Optional access to `https://www.wangyutang.cn/camera`

Avoid launching the existing tutorial `vocal_detect` as a long-term dependency unless its ASR credentials are configured. The custom listener is simpler and avoids coupling wakeup, recording, ASR, and TTS into one node.

## Next Step After Model Is Provided

1. Define the model API request format for audio and optional image input.
2. Implement `model_provider.py`.
3. Implement `edge_audio_listener.py` with wakeup, recording, model call, and action task creation.
4. Test with these commands:
   - `鍚戝乏鐪媊
   - `鍚戝彸鐪媊
   - `鍚戝墠璧癭
   - `鍚戝悗璧癭
5. Add a systemd service only after manual tests are stable.

## Current Engineering Scaffold

The self-developed ASR scaffold is now kept in this directory.

Implemented files:

```text
audio_recognition/
  server.py                 Cloud/API service for presenting recognized text
  edge_audio_listener.py    Pi-side WonderEchoPro wakeup, record, model call, upload
  recorder.py               arecord wrapper for local WAV capture
  model_provider.py         Generic HTTP model provider adapter
  skill_router.py           Optional text to action_move skill mapping
  config.example.json       Runtime config template
  requirements.txt          Python dependencies
  Dockerfile                Cloud service image
  IMPLEMENTATION.md         Implementation notes and next steps
  static/                   Web page for latest text and history
```

The online page also visualizes pipeline events so the full path is inspectable:

```text
hardware_wakeup -> recording -> audio_conversion -> model_asr -> text_display
```

The ASR chain is real-data only. `model_provider.type` must point to an actual ASR transport such as `generic_http`; synthetic transcripts are intentionally not supported.

The remaining model-specific work should be done by filling `config.json` from `config.example.json`, especially:

```text
model_provider.endpoint
model_provider.api_key or AUDIO_MODEL_API_KEY
model_provider.model
model_provider.audio_field
model_provider.response_text_path
```

## Cloud Verification

The current Tencent Cloud deployment is available at:

```text
https://www.wangyutang.cn/audio/
```

Verified APIs:

```text
https://www.wangyutang.cn/audio/api/health
https://www.wangyutang.cn/audio/api/results
https://www.wangyutang.cn/audio/api/events
```


Visible pipeline stages:

```text
hardware_wakeup -> recording -> audio_conversion -> model_asr -> text_display
```

# Online Audio Input To Servo Direction

Current browser test path:

```text
https://www.wangyutang.cn/audio/
  -> browser microphone recording
  -> local ASR API http://127.0.0.1:8097/v1/audio/transcriptions
  -> cloud /audio/api/recognize-text
  -> cloud /action/api/tasks
  -> Raspberry Pi action-move poller
  -> persistent ROS servo controller
```

Supported voice intents for camera direction:

```text
鍚戝乏鐪?-> look_left
鍚戝彸鐪?-> look_right
鍚戜笂鐪?-> look_up
鍚戜笅鐪?-> look_down
澶嶄綅/鍥炴 -> reset_pose
鍋滄/鎬ュ仠 -> emergency_stop
```

The WonderEchoPro hardware is visible on the Raspberry Pi as:

```text
USB PnP Audio Device
ALSA capture: card 2, device 0
PipeWire source: alsa_input.usb-0c76_USB_PnP_Audio_Device-00.analog-stereo
```

For edge-side recording, configure `config.json` from `config.example.json`. The example now points the ASR adapter at:

```text
http://127.0.0.1:8097/v1/audio/transcriptions
```

If the ASR API runs on the Windows laptop instead of the Raspberry Pi, replace `127.0.0.1` with the laptop IP reachable from the Pi.
