# 2026-05-24 qwen3-32b ReAct 实车验证问题记录

## 背景

目标是在 `audio_recognition` 中将 WALL-E 大脑切换为 Common API 的 `qwen3-32b` tools 接口，并验证以下实车指令能正确执行：

- `先前进再向上看`
- `左转，不要往上看`

目标链路：

```text
audio_recognition
-> qwen3-32b ReAct native tool_calls
-> validator
-> safety_guard
-> dispatcher local_first
-> action_move edge_ros_controller
-> ROS2 /cmd_vel 或云台舵机
```

## 问题 1：旧树莓派地址不可达

### 现象

最初按旧文档地址检查：

```text
192.168.137.2
```

结果：

```text
ping 192.168.137.2: 100% packet loss
ssh pi@192.168.137.2: timed out
http://192.168.137.2:8765/health: timed out
http://192.168.137.2:18765/health: timed out
```

### 根因

当前树莓派实际 IP 已变为：

```text
192.168.1.46
```

通过 SSH 别名确认：

```bash
ssh raspberrypi 'hostname; hostname -I'
```

输出：

```text
raspberrypi
192.168.1.46 172.17.0.1 240e:305:1b86:2400:f638:e200:c55:bfe6
```

### 解决办法

后续实车 action server 使用：

```text
http://192.168.1.46:8765
```

注意：`raspberrypi` 是 SSH config 别名，不是 HTTP/DNS 名称。本机 HTTP 访问应使用 IP。

## 问题 2：action controller 服务运行但外部端口拒绝连接

### 现象

树莓派可 ping，SSH 可登录，但本机访问 action controller 失败：

```text
http://192.168.1.46:8765/health -> Connection refused
http://192.168.1.46:18765/health -> Connection refused
```

树莓派上检查服务：

```bash
ssh raspberrypi 'systemctl status action-move-controller --no-pager'
```

服务是 active，但启动参数为：

```text
python3 /home/ubuntu/action_move/edge_ros_controller.py --host 127.0.0.1 --port 8765 --catalog /home/ubuntu/action_move/skill_catalog.json
```

树莓派本机检查：

```bash
ssh raspberrypi 'python3 - <<"PY"
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8765/health", timeout=3) as r:
    print(r.status, r.read().decode())
PY'
```

输出：

```json
{"status": "ok", "service": "TurboPi Action Move Edge ROS Controller", "last_action": "look_down", "last_executed_at": 1779555130.9287796}
```

### 根因

`action-move-controller.service` 将 `edge_ros_controller.py` 绑定到 `127.0.0.1:8765`，只允许树莓派本机访问，外部机器访问 `192.168.1.46:8765` 会被拒绝。

### 解决办法

经确认后，备份 systemd 服务文件，将监听地址改为 `0.0.0.0` 并重启服务：

```bash
ssh raspberrypi 'set -e; sudo cp /etc/systemd/system/action-move-controller.service /etc/systemd/system/action-move-controller.service.bak-$(date +%Y%m%d-%H%M%S); sudo python3 - <<"PY"
from pathlib import Path
path = Path("/etc/systemd/system/action-move-controller.service")
text = path.read_text()
old = "--host 127.0.0.1 --port 8765"
new = "--host 0.0.0.0 --port 8765"
if old not in text and new not in text:
    raise SystemExit("expected host argument not found")
if old in text:
    path.write_text(text.replace(old, new))
PY
sudo systemctl daemon-reload
sudo systemctl restart action-move-controller
systemctl is-active action-move-controller
'
```

重启后检查：

```bash
ssh raspberrypi 'systemctl status action-move-controller --no-pager; ss -ltnp | grep 8765 || true'
```

关键结果：

```text
Active: active (running)
python3 /home/ubuntu/action_move/edge_ros_controller.py --host 0.0.0.0 --port 8765 --catalog /home/ubuntu/action_move/skill_catalog.json
LISTEN 0 5 0.0.0.0:8765 0.0.0.0:* users:(("python3",pid=90883,fd=17))
```

本机访问成功：

```bash
python - <<'PY'
import urllib.request
with urllib.request.urlopen('http://192.168.1.46:8765/health', timeout=5) as r:
    print(r.status, r.read().decode())
PY
```

输出：

```json
{"status": "ok", "service": "TurboPi Action Move Edge ROS Controller", "last_action": "", "last_executed_at": 0.0}
```

## 问题 3：qwen3-32b Common API 偶发连接中断

### 现象

第一次真实 qwen3-32b dry-run 中，前两轮动作已经正确生成：

```text
先前进再向上看 -> move_forward -> look_up
```

但第三轮 finish 请求偶发失败：

```text
RemoteDisconnected('Remote end closed connection without response')
```

或：

```text
SSLEOFError: UNEXPECTED_EOF_WHILE_READING
```

### 根因

公网 Common API / HTTPS 链路存在偶发连接中断。不是 ReAct 规则或 action controller 问题，因为动作 tool_calls 已正确生成。

### 解决办法

将 `react_regression_check.py` 中 LLM 重试配置从固定 1 次改为可配置，默认 2 次：

```python
parser.add_argument("--llm-retries", type=int, default=2)
```

并在构造 LLM 配置时使用：

```python
"retries": args.llm_retries
```

复测后 dry-run 完整通过。

## 实车前安全预检

先发真实 `emergency_stop`，确认执行接口可用且机器人处于停止状态：

```bash
python - <<'PY'
import json, urllib.request
payload={"action":"emergency_stop","settings":{"stop_publish_times":5}}
req=urllib.request.Request('http://192.168.1.46:8765/execute', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'}, method='POST')
with urllib.request.urlopen(req, timeout=10) as r:
    print(r.status, r.read().decode())
with urllib.request.urlopen('http://192.168.1.46:8765/health', timeout=5) as r:
    print(r.status, r.read().decode())
PY
```

结果：

```json
{"ok": true, "skill_id": "emergency_stop", "name_zh": "急停", "elapsed_seconds": 0.092}
```

`/health` 显示：

```json
{"status": "ok", "service": "TurboPi Action Move Edge ROS Controller", "last_action": "emergency_stop"}
```

## qwen3-32b dry-run 验证结果

命令：

```bash
PYTHONPATH=/mnt/c/Users/Administrator/Desktop/Workspace/Project_Codex/wangyutang_platform \
python /mnt/c/Users/Administrator/Desktop/Workspace/Project_Codex/wangyutang_platform/audio_recognition/react_regression_check.py \
  --action-server http://192.168.1.46:8765 \
  --text '先前进再向上看' \
  --second-text '左转，不要往上看'
```

### `先前进再向上看`

结果：

```text
move_forward -> look_up -> finish
```

关键 tool_calls：

```json
[
  {"tool": "dispatch_action", "args": {"skill_id": "move_forward", "text": "前进"}},
  {"tool": "dispatch_action", "args": {"skill_id": "look_up", "text": "向上看"}},
  {"tool": "finish"}
]
```

### `左转，不要往上看`

结果：

```text
turn_left -> finish
```

关键点：否定片段 `不要往上看` 没有生成 `look_up`。

## 实车验证结果

命令：

```bash
PYTHONPATH=/mnt/c/Users/Administrator/Desktop/Workspace/Project_Codex/wangyutang_platform \
python /mnt/c/Users/Administrator/Desktop/Workspace/Project_Codex/wangyutang_platform/audio_recognition/react_regression_check.py \
  --action-server http://192.168.1.46:8765 \
  --real \
  --text '先前进再向上看' \
  --second-text '左转，不要往上看'
```

脚本行为：

1. 检查 `action_server_health`。
2. 执行 dry-run emergency preflight。
3. 执行真实 `pre_real_emergency_stop`。
4. 执行第一条真实指令。
5. 执行第二条真实指令。
6. 执行真实 `post_real_emergency_stop`。
7. 检查 `post_real_health`。

### `先前进再向上看` 实车结果

生成：

```text
move_forward -> look_up -> finish
```

执行结果：

```text
move_forward status=completed action_ok=true action_elapsed=0.294s
look_up      status=completed action_ok=true action_elapsed=0.352s
```

### `左转，不要往上看` 实车结果

生成：

```text
turn_left -> finish
```

执行结果：

```text
turn_left status=completed action_ok=true action_elapsed=0.345s
```

关键点：没有执行 `look_up`。

### 结束状态

最后执行 `post_real_emergency_stop` 成功：

```json
{"ok": true, "skill_id": "emergency_stop", "name_zh": "急停", "elapsed_seconds": 0.092}
```

最终 health：

```json
{"status": "ok", "service": "TurboPi Action Move Edge ROS Controller", "last_action": "emergency_stop"}
```

## 本次代码侧相关改动

- `react_agent.py`
  - 默认 LLM endpoint/model 切到 qwen3-32b Common API。
  - 支持加载外置 `prompts/walle_system_prompt.md`。
- `server.py`
  - 默认 LLM endpoint/model 切到 qwen3-32b Common API。
  - 注入默认 `prompt_path`。
- `config.example.json`
  - 示例配置切到 qwen3-32b。
  - 增加 `react_agent.prompt_path`。
- `prompts/walle_system_prompt.md`
  - 新增 WALL-E system prompt。
- `tool_schema.py`
  - 兼容 0524 参数：`focus` / `purpose` / `timeout_ms` / `message` / `intensity`。
- `tool_validator.py`
  - 归一化 `reason -> purpose`、`timeout_s <-> timeout_ms`、`final -> message`。
- `observation_executor.py`
  - `ask_confirmation` 同时记录 `timeout_ms` 和 `timeout_s`。
- `tool_call_adapter.py`
  - finish 优先兼容 `message`。
- `react_regression_check.py`
  - 默认 qwen3-32b Common API。
  - 使用真实 `skills/registry.yaml` 与 `action_move/skill_catalog.json`。
  - 增加第二条指令参数 `--second-text`。
  - 增加 `--llm-retries` 默认 2。

## 回归测试

本地单元测试：

```bash
PYTHONPATH=/mnt/c/Users/Administrator/Desktop/Workspace/Project_Codex/wangyutang_platform \
python -m unittest \
  audio_recognition.tests.test_react_pipeline \
  audio_recognition.tests.test_regression_suite \
  audio_recognition.tests.test_planner_modes \
  audio_recognition.tests.test_intermediate_store
```

结果：

```text
Ran 37 tests in 0.937s
OK
```

## 后续注意事项

- `192.168.137.2` 是旧地址；当前树莓派为 `192.168.1.46`。
- `raspberrypi` 是 SSH 别名，不保证 HTTP 可解析；HTTP 调 action controller 用 `192.168.1.46`。
- `action-move-controller.service` 现在监听 `0.0.0.0:8765`，局域网可访问。若网络环境不可信，需要额外防火墙或只允许可信主机访问。
- 实车动作验证前仍应先执行 `emergency_stop` 并确认现场安全。
- Common API qwen3-32b 偶发 HTTPS 连接中断，回归脚本默认 2 次重试。
