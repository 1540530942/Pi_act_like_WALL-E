# 语音控制监控运维记录

本文记录 WonderEchoPro 语音控制链路的部署方式、开关语义、排查经验和常见故障。目标目录：

```text
C:\Users\Administrator\Desktop\Workspace\Project_Codex\wangyutang_platform\audio_recognition
```

## 当前架构

```text
WonderEchoPro / USB 麦克风
  -> 树莓派 edge_audio_listener.py
  -> Windows ASR API 8097
  -> Windows llama/qwen3-asr 8096
  -> 腾讯云 https://www.wangyutang.cn/audio
  -> 腾讯云 https://www.wangyutang.cn/action
  -> 树莓派 edge_action_poller.py
  -> TurboPi / ROS2 / 小车运动
```

重要结论：

- `语音控制监控` 页面已经部署到腾讯云：`https://www.wangyutang.cn/audio/`
- ASR API 还没有部署到腾讯云，目前跑在 Windows 本机。
- 树莓派通过 `http://192.168.137.1:8097/v1/audio/transcriptions` 调用 Windows ASR。
- 树莓派登录信息：`pi` / `raspberrypi`。
- 树莓派当前 IP：`192.168.137.148`。
- Windows 热点网关：`192.168.137.1`。

## 开关语义

云端设置接口：

```text
GET  /api/settings
POST /api/settings
POST /api/manual-recording/start
POST /api/manual-recording/stop
```

设置项：

```json
{
  "voice_wakeup_enabled": false,
  "manual_recording_enabled": false
}
```

语义：

- `voice_wakeup_enabled=true`：常态自动监听开启。WonderEchoPro 持续采集、送 ASR、识别动作。
- `voice_wakeup_enabled=false`：常态自动监听关闭。
- `manual_recording_enabled=true`：页面点击 `开始录音` 后临时开启语音链路。
- `manual_recording_enabled=false`：页面点击 `停止录音` 后停止临时采集。
- 两个都为 `false` 时，树莓派监听进程仍运行，但处于待命状态，不录音、不调用 ASR。

用户说“监听开启/关闭”时，指的是常态自动监听开关。关闭常态监听时，仍然可以通过页面 `开始录音 / 停止录音` 临时触发语音链路。

## 页面功能

公网入口：

```text
https://www.wangyutang.cn/audio/
```

页面包含：

- WonderEchoPro 常态监听开关。
- `开始录音`：开启 `manual_recording_enabled`，让树莓派开始采集 WonderEchoPro。
- `停止录音`：关闭 `manual_recording_enabled`。
- `清零任务`：调用 action_move 清空任务队列。
- 摄像头窗口：打开/关上摄像头连续上传任务。
- 最新识别文本、匹配动作、动作执行结果、流水线事件。

## Windows ASR 启动

路径：

```text
C:\Users\Administrator\Desktop\Workspace\Project_Codex\Project_ASR\online_api
```

端口：

```text
8096  llama-server / qwen3-asr 模型服务
8097  FastAPI ASR 包装服务
```

启动命令：

```powershell
cd C:\Users\Administrator\Desktop\Workspace\Project_Codex\Project_ASR\online_api
.\start_llama_server.ps1
.\start_api.ps1
```

健康检查：

```powershell
curl.exe -sS --noproxy "*" http://127.0.0.1:8097/health
```

正常结果应包含：

```json
{
  "status": "ok",
  "backend_ok": true,
  "backend": "http://127.0.0.1:8096",
  "model": "qwen3-asr"
}
```

如果 `8097` 返回 `degraded`，并且错误里有 `127.0.0.1:8096 refused`，说明 ASR 包装层还在，但模型服务 `8096` 停了，需要重新运行 `start_llama_server.ps1`。

## 树莓派配置

树莓派配置文件：

```text
/home/pi/audio_recognition/config.json
```

关键配置：

```json
{
  "cloud": {
    "audio_server": "https://www.wangyutang.cn/audio",
    "action_server": "https://www.wangyutang.cn/action",
    "action_enabled": true
  },
  "model_provider": {
    "endpoint": "http://192.168.137.1:8097/v1/audio/transcriptions"
  }
}
```

检查树莓派能否访问 ASR：

```bash
curl -sS --max-time 10 http://192.168.137.1:8097/health
```

监听进程：

```bash
ps -ef | grep edge_audio_listener.py | grep -v grep
tail -80 /tmp/audio-listener.log
```

重启监听进程：

```bash
cd /home/pi/audio_recognition
python3 -m py_compile edge_audio_listener.py
for pid in $(pgrep -f '^python3 .*[e]dge_audio_listener.py' || true); do kill -TERM "$pid" || true; done
sleep 1
: > /tmp/audio-listener.log
nohup python3 /home/pi/audio_recognition/edge_audio_listener.py \
  --config /home/pi/audio_recognition/config.json \
  --record-loop \
  --record-loop-gap 1.5 \
  --max-background-jobs 2 \
  > /tmp/audio-listener.log 2>&1 < /dev/null &
echo $! > /tmp/audio-listener.pid
```

## 云端部署记录

腾讯云页面服务是 `audio-recognition` 容器，源码挂载在：

```text
/root/control_platform/audio_recognition
```

云端容器检查：

```bash
docker ps --format '{{.Names}} {{.Image}} {{.Ports}}' | grep -Ei 'audio|action|camera'
curl -fsS http://127.0.0.1:8095/api/health
curl -fsS http://127.0.0.1:8095/api/dashboard
```

热更新方式：

```powershell
tar --exclude='audio_recognition/data' `
    --exclude='audio_recognition/__pycache__' `
    --exclude='audio_recognition/*.log' `
    --exclude='audio_recognition/*.err.log' `
    -cf $env:TEMP\voice-monitor-update.tar audio_recognition

scp -i "$HOME\.ssh\codex_tencent_lighthouse" `
    $env:TEMP\voice-monitor-update.tar `
    tencent:/root/voice-monitor-update.tar

ssh -i "$HOME\.ssh\codex_tencent_lighthouse" tencent `
    "cd /root/control_platform && tar -xf /root/voice-monitor-update.tar && docker restart audio-recognition"
```

完整发布脚本 `scripts/deploy_tencent.ps1` 依赖本机 Docker Desktop。若 Docker daemon 未启动，会报：

```text
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
```

这种情况下可使用上面的热更新方式。

## 常见故障

### 1. 说话没有响应

先查云端开关：

```powershell
curl.exe -sS https://www.wangyutang.cn/audio/api/dashboard
```

看：

```json
"settings": {
  "voice_wakeup_enabled": false,
  "manual_recording_enabled": false
}
```

如果两个都是 `false`，直接对 WonderEchoPro 说话不会触发采集。需要：

- 打开常态监听开关；或
- 点击页面 `开始录音`。

### 2. 有音频但都是 noise_or_unrecognized_audio

说明链路在采集，但 ASR 没识别出有效文本。可能原因：

- 离 WonderEchoPro 太远。
- 环境噪声大。
- 说话不在 4 秒采集窗口内。
- 音量太小。
- ASR 模型对当前音频质量识别差。

可查看：

```bash
tail -80 /tmp/audio-listener.log
```

如果能看到 `captured_audio: true`，说明采集链路有工作。

### 3. ASR 500 或 degraded

树莓派日志可能出现：

```text
500 Server Error: Internal Server Error for url: http://192.168.137.1:8097/v1/audio/transcriptions
```

本机检查：

```powershell
curl.exe -sS --noproxy "*" http://127.0.0.1:8097/health
```

如果是 `degraded`，通常是 `8096` 模型服务没开。运行：

```powershell
cd C:\Users\Administrator\Desktop\Workspace\Project_Codex\Project_ASR\online_api
.\start_llama_server.ps1
```

### 4. 腾讯云页面可以打开，但手机手动录音不可用

最初页面的浏览器录音逻辑会尝试访问：

```text
http://127.0.0.1:8097
```

手机浏览器里的 `127.0.0.1` 是手机自己，不是 Windows，所以不可用。

现在页面 `开始录音 / 停止录音` 已改为控制树莓派 WonderEchoPro 采集链路，不再依赖手机浏览器直连 Windows ASR。

### 5. 云端 events.json 被写坏导致 500

之前由于异步 ASR 多线程并发写 `events.json`，出现：

```text
json.decoder.JSONDecodeError: Extra data
```

已修复：

- 后端写 JSON 加锁。
- 使用临时文件原子替换。
- JSON 损坏时尽量容错。
- 树莓派上传事件失败不再导致监听进程退出。

### 6. ASR 任务过多

连续录音会比 ASR 处理更快，导致积压。已加入：

```text
--max-background-jobs 2
```

超过并发数会跳过该段 ASR，避免把服务打爆。

## 验证流程

1. 检查 ASR：

```powershell
curl.exe -sS --noproxy "*" http://127.0.0.1:8097/health
```

2. 检查云端：

```powershell
curl.exe -sS https://www.wangyutang.cn/audio/api/dashboard
```

3. 检查树莓派：

```bash
ps -ef | grep edge_audio_listener.py | grep -v grep
tail -80 /tmp/audio-listener.log
curl -sS --max-time 10 http://192.168.137.1:8097/health
```

4. 打开页面：

```text
https://www.wangyutang.cn/audio/
```

5. 选择一种方式：

- 打开 WonderEchoPro 常态监听开关；或
- 点击 `开始录音`。

6. 对 WonderEchoPro 清楚说：

```text
前进
向左转
向右转
后退
```

7. 观察：

- 最新识别内容是否出现文本。
- `skill_id` 是否匹配为 `move_forward` / `turn_left` 等。
- 动作任务是否进入 `complete`。
- 小车是否播报“您的指令 XXX 已经完成了”。

## 当前保留问题

- ASR API 尚未部署到腾讯云，仍依赖 Windows 本机 `8096/8097`。
- 如果 Windows 休眠、ASR 进程退出或热点 IP 变化，树莓派会无法识别。
- 后续如需完全云端化，需要评估腾讯云机器 CPU/内存/GPU 是否能运行 Qwen3-ASR 和 llama.cpp。
