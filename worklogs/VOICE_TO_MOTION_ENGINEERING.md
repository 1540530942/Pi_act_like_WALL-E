# Voice To Motion Engineering

Date: 2026-05-14

## Goal

Store the WonderEchoPro voice-control implementation in this folder:

```text
audio_recognition/
```

The runtime chain is:

```text
user speech
-> WonderEchoPro wakeup or browser microphone
-> real WAV recording
-> Project_ASR/online_api /v1/audio/transcriptions
-> Chinese text
-> safe voice intent allow-list
-> action_move /api/tasks
-> Raspberry Pi action poller
-> ROS2 /cmd_vel
-> TurboPi movement
```

## Implemented Files

```text
voice_intents.py          Shared safe text-to-action resolver.
server.py                 Uses voice_intents.py for browser/cloud text routing.
edge_audio_listener.py    Uses voice_intents.py for WonderEchoPro edge routing.
```

## Supported Voice Commands

Base movement:

```text
前进 / 向前走 / 小车前进          -> move_forward
后退 / 往后走 / 倒退              -> move_backward
左移 / 向左平移 / 往左走          -> move_left
右移 / 向右平移 / 往右走          -> move_right
左转 / 原地左转 / 向左转          -> turn_left
右转 / 原地右转 / 向右转          -> turn_right
停止 / 停下 / 停车 / 急停 / 刹车  -> emergency_stop
```

Camera and pose commands remain enabled:

```text
向左看 / 左看      -> look_left
向右看 / 右看      -> look_right
向上看 / 上看      -> look_up
向下看 / 下看      -> look_down
复位 / 回正 / 重置 -> reset_pose
```

The resolver intentionally does not allow `remote_shutdown`.

## Local ASR API

On the Windows ASR host:

```powershell
cd C:\Users\Administrator\Desktop\Workspace\Project_Codex\Project_ASR\online_api
powershell -ExecutionPolicy Bypass -File .\start_llama_server.ps1
powershell -ExecutionPolicy Bypass -File .\start_api.ps1
```

Expected endpoints:

```text
http://127.0.0.1:8096/v1/models
http://127.0.0.1:8097/health
http://127.0.0.1:8097/v1/audio/transcriptions
```

If the wrapper process runs in an environment with HTTP proxy variables, set:

```text
NO_PROXY=127.0.0.1,localhost
no_proxy=127.0.0.1,localhost
```

## Raspberry Pi Edge Config

Copy and edit:

```bash
cd /home/pi/audio_recognition
cp config.example.json config.json
```

Set `model_provider.endpoint` to an address reachable from the Raspberry Pi. If the ASR wrapper runs on the Windows laptop, do not use `127.0.0.1`; use the laptop LAN IP:

```json
"endpoint": "http://<windows-lan-ip>:8097/v1/audio/transcriptions"
```

Set action routing to the action_move service:

```json
"cloud": {
  "audio_server": "https://www.wangyutang.cn/audio",
  "action_server": "https://www.wangyutang.cn/action",
  "action_enabled": true
}
```

## Manual Tests

Text-only route test against the audio service:

```bash
curl -X POST https://www.wangyutang.cn/audio/api/recognize-text \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"manual","text":"前进","route_action":true}'
```

Pi one-shot real audio test:

```bash
python3 edge_audio_listener.py --config config.json --once
```

Continuous WonderEchoPro wakeup mode:

```bash
python3 edge_audio_listener.py --config config.json
```

## Safety

- Only actions in `voice_intents.ALLOWED_VOICE_SKILL_IDS` can be triggered.
- `remote_shutdown` is excluded even if the action catalog contains it.
- `action_move` handles motion through bounded `/cmd_vel` bursts and publishes stop after movement.
- `emergency_stop` maps from common stop words and cancels queued motion tasks on the action service.
