# Voice To Servo Direction Chain

Date: 2026-05-14

## Goal

Build the self-developed chain:

```text
WonderEchoPro hardware / browser microphone
-> audio recording
-> ASR text
-> intent routing
-> TurboPi camera servo action
```

## Hardware Detection

Raspberry Pi detects the WonderEchoPro hardware audio path as a USB audio device:

```text
USB: 0c76:161f JMTek, LLC. USB PnP Audio Device
ALSA capture: card 2, device 0
PipeWire source: alsa_input.usb-0c76_USB_PnP_Audio_Device-00.analog-stereo
```

The implementation treats WonderEchoPro as hardware only. Wakeup/recording/ASR/routing are owned by this project.

## Online Browser Path

Public page:

```text
https://www.wangyutang.cn/audio/
```

The page contains an Online Audio Input panel:

```text
browser recording
-> http://127.0.0.1:8097/v1/audio/transcriptions
-> /audio/api/recognize-text
-> /action/api/tasks
```

The local ASR API lives in:

```text
C:\Users\Administrator\Desktop\Workspace\Project_Codex\Project_ASR\online_api
```

It uses native llama.cpp server on port `8096` and FastAPI wrapper on port `8097`.

## Intent Safety

Voice routing uses a safe allow-list. It intentionally does not allow `remote_shutdown`.

Allowed camera/servo intents:

```text
向左看 -> look_left
向右看 -> look_right
向上看 -> look_up
向下看 -> look_down
复位/回正 -> reset_pose
停止/急停 -> emergency_stop
```

## API

Cloud text routing:

```http
POST /audio/api/recognize-text
Content-Type: application/json

{
  "device_id": "web-audio",
  "text": "向左看",
  "route_action": true,
  "raw": {}
}
```

When `route_action` is true, the service creates an action task against `action-move`.

## Verification

Safe parse-only test:

```text
text: 向左看
skill_id: look_left
route_action: false
```

Full chain text test:

```text
text: 向左看
created action: look_left
action status: complete
device_id: turbopi-01
claim latency: 0.097s
completion latency: 0.803s
controller: persistent_ros_controller
```

The full chain test moved the camera pan servo through `look_left`.

## Notes

- The browser page calls `http://127.0.0.1:8097` from the viewer's machine. Keep the ASR service running locally for online browser tests.
- If using Raspberry Pi edge recording, set the ASR endpoint in `config.json` to an address reachable from the Pi, for example the laptop IP and port `8097`.
- Keep recordings around 3-8 seconds. The ASR page has a 10 second recording cap to avoid very long llama.cpp audio processing.
