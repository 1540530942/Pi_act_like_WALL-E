# Start Recording Fix 2026-05-15

记录本次故障：页面选择“开始录音”后，说的话没有执行。

## 现象

- 页面可以触发 `manual_recording_enabled=true`。
- 云端能看到 `recording`、`WAV captured`、`model_asr` 事件。
- 结果一直是 `noise_or_unrecognized_audio`，没有生成动作任务。

## 结论

页面、云端设置、树莓派录音进程、ASR HTTP 调用都不是完全断开的。断点在 ASR 没有从 WonderEchoPro 的 WAV 中识别出有效中文文本。

2026-05-15 检查最近的树莓派录音：

```text
command_1778779809176.wav dur=4.0 rate=16000 ch=1 rms=173 max=736
command_1778779802937.wav dur=4.0 rate=16000 ch=1 rms=207 max=1342
command_1778779741279.wav dur=4.0 rate=16000 ch=1 rms=251 max=1447
```

WAV 格式正确，但是音量很轻。qwen3-asr 对这类低音量录音容易返回空文本。

## 已做修复

在 `recorder.py` 里增加了录音后的 WAV 音量归一化：

- `normalize_target_rms`: 目标 RMS。
- `normalize_max_gain`: 最大放大量，避免过度放大。

树莓派 `/home/pi/audio_recognition/config.json` 已加入：

```json
"normalize_target_rms": 1800,
"normalize_max_gain": 12
```

修复后测试，录音可从 RMS 约 `170` 提升到约 `1800`：

```text
command_1778780099511.wav dur=4.0 rms=1801 max=8080
```

## 已重启的树莓派监听进程

```bash
python3 /home/pi/audio_recognition/edge_audio_listener.py \
  --config /home/pi/audio_recognition/config.json \
  --record-loop \
  --record-loop-gap 1.5 \
  --max-background-jobs 2
```

最新确认 PID：

```text
42498
```

## 后半链路验证

按之前约定，如果我不在 WonderEchoPro 旁边，就用 mock “前进”继续验证。

mock 文本测试：

```python
import requests
s = requests.Session()
s.trust_env = False
r = s.post(
    "https://www.wangyutang.cn/audio/api/recognize-text",
    json={"device_id": "mock-audio", "text": "\u524d\u8fdb", "route_action": True},
    timeout=15,
)
print(r.status_code, r.text)
```

结果：

- 云端正确解析 `前进` -> `move_forward`。
- 创建任务 `1778780178072-521771`。
- 树莓派动作服务完成任务。
- 领取延迟约 `0.04s`，执行约 `0.9s`。

这说明 `中文文本 -> 动作任务 -> 树莓派执行 -> 完成回报` 链路是通的。

## 如果再出现“开始录音后没执行”

先看云端 dashboard：

```powershell
curl.exe -sS --noproxy "*" https://www.wangyutang.cn/audio/api/dashboard
```

判断：

- 没有 `recording`：页面开始录音没有成功打开云端开关。
- 有 `WAV captured`，但 `text` 为空：录音/ASR 问题。
- 有中文文本，但 `skill_id` 为空：意图匹配词表问题。
- 有 `skill_id`，但 action 没完成：动作服务或树莓派 action poller 问题。

树莓派检查录音音量：

```bash
python3 - <<'PY'
from pathlib import Path
import wave, audioop
for p in sorted(Path('/tmp/audio_recognition').glob('command_*.wav'), key=lambda x:x.stat().st_mtime, reverse=True)[:5]:
    with wave.open(str(p), 'rb') as w:
        frames = w.readframes(w.getnframes())
        print(p.name, 'rms=', audioop.rms(frames, w.getsampwidth()), 'max=', audioop.max(frames, w.getsampwidth()))
PY
```

如果没有人在 WonderEchoPro 旁边说话，ASR 返回空文本是正常的。实际测试时需要对着 WonderEchoPro 清楚说“前进 / 后退 / 向左转 / 向右转”。
