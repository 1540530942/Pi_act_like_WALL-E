# Pi_act_like_WALL-E `audio_recognition` 分支 ReAct 化整改方案

## 1. 文档目的

本文用于指导 `Pi_act_like_WALL-E` 项目中 `audio_recognition` 分支的架构整改。

当前项目已经具备基础语音识别、意图路由、动作分发、页面展示、历史记录等能力，但整体仍存在以下问题：

```text
链路载体不统一
阶段边界不清
边云职责重复
Plan / Dispatch 耦合
Replay 能力不足
Safety Guard 不完整
简单动作与复杂任务缺少统一决策框架
Agent 决策与真实硬件执行边界不清
```

本次整改目标是将项目重构为：

```text
统一 ReAct 决策框架
统一 DecisionEnvelope 链路载体
统一 Tool Call 结构化输出
统一 Safety Guard 安全审查
统一 Edge Dispatcher 真实执行
统一 Envelope Store / Replay 历史回放
统一 Cloud Dashboard 状态展示
```

一句话目标：

> 所有指令统一进入 ReAct Agent，但 ReAct 只能生成结构化工具调用；真实硬件执行必须经过 Tool Validator、Safety Guard 和 Edge Dispatcher。

---

## 2. 总体结论

### 2.1 是否可以统一使用 ReAct

可以。

简单指令也可以统一交给 ReAct，例如：

```text
前进
右转
停止
笑一笑
眨眼
```

这些指令在 ReAct 模式下会退化为一轮决策：

```text
理解用户意图 -> 生成一个 tool_call -> Safety Guard 审查 -> Dispatcher 执行 -> 完成
```

复杂指令则使用多轮 ReAct：

```text
观察 -> 判断 -> 执行 -> 再观察 -> 修正
```

例如：

```text
看看前面有没有障碍，安全的话往前走一点，然后右转
```

可以变成：

```text
camera_snapshot -> 判断前方安全 -> move_forward -> turn_right
```

### 2.2 关键边界

统一 ReAct 可以作为“决策外壳”，但不能让 Agent 直接控制硬件。

禁止：

```text
ReAct Agent -> GPIO / ROS2 / 电机
```

必须：

```text
ReAct Agent
  -> structured tool_calls
  -> Tool Validator
  -> Safety Guard
  -> Edge Dispatcher
  -> GPIO / ROS2 / 电机 / 表情系统
```

### 2.3 推荐最终形态

```text
用户语音 / 文本 / 远程命令
  -> Capture
  -> ASR / Text Input
  -> DecisionEnvelope
  -> ReAct Agent
  -> Tool Calls
  -> Tool Validator
  -> Safety Guard
  -> Edge Dispatcher
  -> Observation
  -> Envelope Store
  -> Cloud Dashboard
  -> Replay / Diff
```

总结为：

```text
ReAct 负责想
Tool Validator 负责校验格式
Safety Guard 负责审
Dispatcher 负责做
Envelope 负责记
Replay 负责复现
Cloud 负责看
Edge 负责控
```

---

## 3. 当前问题整理

### 3.1 架构层问题

#### 3.1.1 缺少贯穿全链路的决策对象

当前项目中，音频、ASR 结果、Plan 结果、Dispatch 结果、错误信息、时间戳等分散在多个 dict、event、result、case 中。

问题表现：

```text
阶段间依赖松散
字段容易丢失
历史记录难以重放
Replay 难以从 audio/text/plan 任一阶段恢复
排查问题时无法看到完整链路
```

整改方向：

```text
一次交互生成一个 DecisionEnvelope
每个阶段只追加字段，不替换前序结果
所有结果都挂在 envelope_id 下
```

#### 3.1.2 边云职责重复

当前 Edge 侧会做 ASR 后的规划或 dry-run，Cloud 收到结果后又重新规划和分发。

更准确的问题是：

```text
边云重复 Plan
存在不一致风险
当前不是严格意义上的双执行，因为 Edge 一般 route_action=False
```

整改方向：

```text
统一 ReAct 决策入口
统一 envelope 记录
明确 dispatch_mode
默认 local_first
```

#### 3.1.3 控制路径绕公网

当前链路中，本地动作可能走：

```text
Edge audio_recognition
  -> Cloud audio service
  -> Cloud action queue
  -> Pi action poller
  -> ROS2 / 电机
```

问题：

```text
本地“前进”“停止”等动作延迟变高
断网后控制能力下降
急停依赖公网会有安全风险
```

整改方向：

```text
local_first 作为默认执行模式
emergency_stop 必须本地最高优先级
Cloud 只做远程入口、状态展示、历史审计、复杂规划辅助
```

#### 3.1.4 Pipeline 不显式

当前 `pipeline.py` 更像若干函数组合，而不是明确阶段链。

整改方向：

```text
CaptureStage
TranscribeStage
ReactAgentStage
ToolValidateStage
SafetyStage
DispatchStage
StoreStage
```

每个阶段统一接口：

```python
def run(self, envelope: DecisionEnvelope) -> DecisionEnvelope:
    ...
```

---

### 3.2 流程层问题

#### 3.2.1 录音固定时长

当前 recorder 默认固定录音 4 秒。

问题：

```text
用户说不完会被截断
用户说完了还要等待
交互不像自然语音助手
```

整改方向：

```text
第一阶段保留固定录音
第二阶段加入 VAD
第三阶段支持 wake word + VAD + 录音反馈
```

#### 3.2.2 单任务路由无法表达复杂指令

当前 `PlannedTask` 基本是：

```text
skill_id + route + confidence
```

这只能表达单任务。

无法自然支持：

```text
先前进，再右转
笑着前进
看前方，如果安全就前进
先看左边，再眨眼，然后右转
```

整改方向：

```text
单 PlannedTask -> 多 TaskStep
plan -> tool_calls[] -> tasks[]
```

#### 3.2.3 Replay 能力不足

当前 replay 主要基于已经识别出的 text 重新路由。

问题：

```text
不能从 audio 重跑 ASR
不能从 tool_calls 重跑 safety
不能从 tasks 重跑 dispatch dry-run
不能做 old/new envelope diff
```

整改方向：

```text
replay --from audio
replay --from text
replay --from tool_calls
replay --from tasks
```

---

### 3.3 代码层问题

#### 3.3.1 `voice_intents.py` 不易维护

当前大量中文别名使用 `\uXXXX` 转义。

问题：

```text
人工不可读
新增指令困难
测试和业务配置混在代码中
```

整改方向：

```text
迁移到 config/skills.yaml
迁移到 config/aliases.yaml
```

#### 3.3.2 RuleBasedTaskPlanner 固定 confidence=1.0

问题：

```text
min_confidence 配置形同虚设
规则命中没有强弱差异
无法触发低置信度二次确认
```

整改方向：

```text
规则 Planner 也输出 confidence
模糊匹配降低 confidence
精确匹配提高 confidence
低于阈值进入 ask_confirmation
```

#### 3.3.3 子串匹配过宽

当前类似：

```python
if normalized_alias in normalized:
    ...
```

问题示例：

```text
不要前进 -> 可能命中 move_forward
别往前走 -> 可能命中 move_forward
```

整改方向：

```text
先做否定词检测
再做 emergency 词检测
再做意图匹配
最后进入 Safety Guard 复核
```

#### 3.3.4 Token 鉴权 fail-open

当前 token 未配置时，接口可能直接放行。

整改方向：

```text
开发环境 allow_empty_token=true
生产环境 allow_empty_token=false
启动时校验 token
公网接口必须鉴权
```

#### 3.3.5 `server.py` 职责过重

当前 `server.py` 同时包含：

```text
FastAPI 路由
鉴权
存储
ASR 代理
Action 代理
Camera 代理
Replay
Dashboard
Settings
```

整改方向：

```text
api/
services/
core/
storage/
```

#### 3.3.6 ASR 长超时和无重试

当前 ASR 可能 180 秒超时，且无 retry/backoff。

整改方向：

```text
短超时 + 重试
异步后台 job
可取消
结果写入 envelope
失败快速返回可观测错误
```

#### 3.3.7 音频 base64 进 JSON

问题：

```text
体积变大
序列化成本高
日志污染
接口不适合大音频
```

整改方向：

```text
音频文件单独存储
envelope 里只存 audio_ref
接口使用 multipart/form-data 或文件引用
```

#### 3.3.8 print 充当日志

整改方向：

```text
使用 logging / structlog
统一 trace_id / envelope_id
日志分级
写入 JSONL
Dashboard 可查看关键事件
```

---

## 4. 整改核心设计

### 4.1 DecisionEnvelope

#### 4.1.1 设计原则

```text
一次交互 = 一个 envelope
每个阶段只追加字段
所有中间产物都可追踪
所有错误都记录
所有工具调用都可回放
所有执行结果都可 diff
```

#### 4.1.2 推荐结构

```python
from pydantic import BaseModel, Field
from typing import Any, Literal


class ToolCall(BaseModel):
    call_id: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["pending", "validated", "rejected", "executed", "failed"] = "pending"
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class TaskStep(BaseModel):
    task_id: str
    skill_id: str
    route: Literal["action", "face", "system"]
    order: int
    duration_ms: int | None = None
    depends_on: list[str] = Field(default_factory=list)
    wait_until: Literal["accepted", "completed"] = "completed"
    status: Literal["pending", "running", "completed", "failed", "cancelled", "rejected"] = "pending"
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class DecisionEnvelope(BaseModel):
    envelope_id: str
    device_id: str = "turbopi-01"
    source: str = "audio"

    t_created: float
    t_capture: float | None = None
    t_transcribe: float | None = None
    t_agent_start: float | None = None
    t_agent_end: float | None = None
    t_validate: float | None = None
    t_safety: float | None = None
    t_dispatch_start: float | None = None
    t_dispatch_end: float | None = None

    audio_ref: str | None = None
    audio_meta: dict[str, Any] = Field(default_factory=dict)

    transcript: str = ""
    asr_meta: dict[str, Any] = Field(default_factory=dict)

    agent_mode: Literal["react"] = "react"
    reasoning_summary: str = ""
    agent_steps: list[dict[str, Any]] = Field(default_factory=list)

    tool_calls: list[ToolCall] = Field(default_factory=list)
    validated_tool_calls: list[ToolCall] = Field(default_factory=list)

    tasks: list[TaskStep] = Field(default_factory=list)

    safety_result: dict[str, Any] = Field(default_factory=dict)
    needs_confirmation: bool = False

    dispatch_results: list[dict[str, Any]] = Field(default_factory=list)
    observations: list[dict[str, Any]] = Field(default_factory=list)

    errors: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)
```

---

### 4.2 ReAct Agent

#### 4.2.1 ReAct 的定位

ReAct Agent 是统一决策层。

它负责：

```text
理解用户指令
必要时调用观察工具
将自然语言拆解成 tool_calls
生成 reasoning_summary
输出 final response
```

它不负责：

```text
绕过 Safety
直接控制硬件
直接调用 ROS2/GPIO
执行无限循环
自由写代码
访问任意系统命令
```

#### 4.2.2 Agent 输入

```json
{
  "envelope_id": "env_001",
  "transcript": "先往前走，然后右转",
  "robot_state": {
    "moving": false,
    "last_action": "none",
    "battery": "normal",
    "emergency_stopped": false
  },
  "available_tools": [
    "camera_snapshot",
    "get_robot_state",
    "dispatch_action",
    "dispatch_face",
    "emergency_stop",
    "ask_confirmation",
    "finish"
  ]
}
```

#### 4.2.3 Agent 输出格式

Agent 只能输出严格 JSON：

```json
{
  "reasoning_summary": "用户要求先前进再右转，拆解为两个串行动作。",
  "tool_calls": [
    {
      "tool": "dispatch_action",
      "args": {
        "skill_id": "move_forward",
        "duration_ms": 800,
        "wait_until": "completed"
      }
    },
    {
      "tool": "dispatch_action",
      "args": {
        "skill_id": "turn_right",
        "duration_ms": 600,
        "wait_until": "completed"
      }
    }
  ],
  "final": "已生成顺序执行计划。"
}
```

注意：

```text
只保存 reasoning_summary
不保存完整内部思维链
```

---

### 4.3 Tool 白名单

#### 4.3.1 第一阶段开放工具

```text
camera_snapshot
get_robot_state
dispatch_action
dispatch_face
emergency_stop
ask_confirmation
finish
```

#### 4.3.2 `dispatch_action`

用于动作类技能。

允许技能：

```text
move_forward
move_backward
move_left
move_right
turn_left
turn_right
look_left
look_right
look_up
look_down
reset_pose
```

参数示例：

```json
{
  "skill_id": "move_forward",
  "duration_ms": 800,
  "speed": "safe",
  "wait_until": "completed"
}
```

参数约束：

```text
duration_ms <= 1000
speed 只能是 slow / safe
wait_until 只能是 accepted / completed
连续 movement 动作 <= 3
```

#### 4.3.3 `dispatch_face`

允许技能：

```text
face_neutral
face_happy
face_joy
face_sad
face_angry
face_speak
face_mouth_open
face_blink
face_reset
```

参数示例：

```json
{
  "skill_id": "face_happy",
  "duration_ms": 3000
}
```

#### 4.3.4 `camera_snapshot`

用于观察环境。

返回：

```json
{
  "image_ref": "camera/latest.jpg",
  "summary": "前方未发现明显障碍物",
  "front_clear": true
}
```

第一阶段可以返回固定摘要或调用已有 camera 服务。

后续接入多模态模型。

#### 4.3.5 `get_robot_state`

返回机器人状态：

```json
{
  "moving": false,
  "last_action": "move_forward",
  "battery": "normal",
  "network": "online",
  "emergency_stopped": false
}
```

#### 4.3.6 `emergency_stop`

最高优先级工具。

要求：

```text
本地立即执行
不等待 Cloud
不进入普通队列
可打断当前动作
执行后写入 envelope
```

#### 4.3.7 `ask_confirmation`

用于低置信度或高风险动作。

示例：

```json
{
  "tool": "ask_confirmation",
  "args": {
    "message": "我理解你是要往前走一点，是否确认？"
  }
}
```

#### 4.3.8 `finish`

结束 Agent 流程。

示例：

```json
{
  "tool": "finish",
  "args": {
    "message": "任务完成"
  }
}
```

---

### 4.4 Tool Validator

#### 4.4.1 职责

Tool Validator 负责检查 Agent 输出是否符合系统契约。

检查项：

```text
tool 是否在白名单
args 是否符合 schema
skill_id 是否存在
route 是否允许
duration_ms 是否越界
是否存在未知字段
是否存在危险工具
是否存在自由代码执行意图
```

#### 4.4.2 校验失败示例

Agent 输出：

```json
{
  "tool": "dispatch_action",
  "args": {
    "skill_id": "jump",
    "duration_ms": 3000
  }
}
```

Validator 输出：

```json
{
  "valid": false,
  "reason": "unsupported_skill_id",
  "detail": "jump is not in allowed skill list"
}
```

---

### 4.5 Safety Guard

#### 4.5.1 职责

Safety Guard 独立于 ReAct Agent。

即使 Agent 输出“可以执行”，Safety Guard 也可以拒绝。

#### 4.5.2 安全检查项

```text
技能白名单
参数限幅
否定词检测
急停词检测
低置信度检测
连续移动次数限制
总执行时长限制
前方障碍检测
当前是否处于 emergency_stopped
是否需要用户确认
```

#### 4.5.3 否定词检测

必须识别：

```text
不要
别
不许
不用
停止
停一下
别动
不要动
不要前进
别往前走
```

示例：

```text
用户：不要前进
```

即使 Agent 误输出：

```json
{
  "tool": "dispatch_action",
  "args": {
    "skill_id": "move_forward"
  }
}
```

Safety Guard 也必须拒绝：

```json
{
  "allowed": false,
  "reason": "negative_instruction_detected"
}
```

#### 4.5.4 急停检测

急停词：

```text
急停
停止
停下
别动
不要动
刹车
```

结果：

```json
{
  "priority": "highest",
  "tool": "emergency_stop",
  "bypass_normal_queue": true,
  "interrupt_current_action": true
}
```

#### 4.5.5 动作限幅

建议第一阶段限制：

```text
前进 / 后退 duration_ms <= 1000
左移 / 右移 duration_ms <= 1000
左转 / 右转 duration_ms <= 800
连续 movement 动作 <= 3
总执行时长 <= 10000
```

---

### 4.6 Dispatcher

#### 4.6.1 定位

Dispatcher 是唯一真实硬件执行者。

ReAct Agent 不能直接执行硬件动作。

#### 4.6.2 职责

```text
串行执行 tasks[]
处理 depends_on
处理 wait_until
处理 timeout
处理 emergency_stop
处理取消
记录每一步执行结果
上传状态
写入 envelope.dispatch_results
```

#### 4.6.3 多步任务执行

用户：

```text
先往前走，然后右转
```

任务：

```json
[
  {
    "task_id": "step_1",
    "skill_id": "move_forward",
    "order": 1,
    "duration_ms": 800
  },
  {
    "task_id": "step_2",
    "skill_id": "turn_right",
    "order": 2,
    "duration_ms": 600,
    "depends_on": ["step_1"]
  }
]
```

执行：

```text
step_1 move_forward -> completed
step_2 turn_right -> completed
```

不能并发下发两个动作。

#### 4.6.4 Dispatcher 伪代码

```python
def dispatch_envelope(envelope: DecisionEnvelope) -> DecisionEnvelope:
    for task in sorted(envelope.tasks, key=lambda x: x.order):
        if emergency_stopped():
            task.status = "cancelled"
            task.error = "emergency_stopped"
            break

        safety = safety_check_task(task, envelope)
        if not safety.allowed:
            task.status = "rejected"
            task.error = safety.reason
            envelope.dispatch_results.append({
                "task_id": task.task_id,
                "status": "rejected",
                "reason": safety.reason,
            })
            break

        task.status = "running"
        result = execute_task(task)

        task.status = result.status
        task.result = result.data
        task.error = result.error

        envelope.dispatch_results.append({
            "task_id": task.task_id,
            "skill_id": task.skill_id,
            "status": result.status,
            "error": result.error,
        })

        if result.status != "completed":
            break

    return envelope
```

---

## 5. 边云职责整改

### 5.1 Edge 侧职责

Edge 负责真实机器人控制。

```text
Capture
ASR
ReAct Agent
Tool Validator
Safety Guard
Local Dispatcher
Emergency Stop
Envelope 本地存储
执行状态上传 Cloud
```

### 5.2 Cloud 侧职责

Cloud 负责状态、可视化、历史和远程入口。

```text
Dashboard
History
Replay
Remote Command
任务审计
配置下发
复杂任务辅助规划
状态汇聚
```

### 5.3 执行模式

新增配置：

```yaml
dispatch_mode: local_first
```

可选：

```text
local_first
cloud_queue
dry_run
```

说明：

| 模式 | 说明 |
|---|---|
| `local_first` | Edge 本地直接执行，推荐默认 |
| `cloud_queue` | 通过 Cloud 队列下发，适合远程控制 |
| `dry_run` | 只生成 envelope，不真实执行，用于测试和 replay |

---

## 6. Replay 整改

### 6.1 目标

Replay 要成为一等公民。

支持从不同阶段重新执行链路。

### 6.2 支持模式

```bash
replay --from audio --case-id xxx
replay --from text --case-id xxx
replay --from tool_calls --case-id xxx
replay --from tasks --case-id xxx
```

### 6.3 各模式说明

| 模式 | 说明 |
|---|---|
| `audio` | 从音频重新跑 ASR + ReAct + Safety + dry-run |
| `text` | 从 transcript 重新跑 ReAct + Safety + dry-run |
| `tool_calls` | 从已有 tool_calls 重新跑 Validator + Safety + dry-run |
| `tasks` | 从已有 tasks 重新跑 Dispatch dry-run |

### 6.4 Replay 输出

```json
{
  "old_envelope_id": "env_001",
  "new_envelope_id": "env_replay_001",
  "diff": {
    "transcript_changed": false,
    "tool_calls_changed": false,
    "tasks_changed": false,
    "safety_changed": false
  }
}
```

---

## 7. 文件结构整改

### 7.1 新增文件

```text
audio_recognition/
  envelope.py
  react_agent.py
  react_tools.py
  tool_validator.py
  safety_guard.py
  dispatcher.py
  replay.py
  pipeline_stages.py
  envelope_store.py
  structured_logging.py
```

### 7.2 新增配置目录

```text
audio_recognition/config/
  skills.yaml
  aliases.yaml
  safety.yaml
  react_tools.yaml
  dispatch.yaml
```

### 7.3 新增测试目录

```text
audio_recognition/tests/cases/
  simple_commands.yaml
  sequence_commands.yaml
  negative_commands.yaml
  emergency_commands.yaml
  react_observe_commands.yaml
```

### 7.4 拆分 `server.py`

建议拆成：

```text
audio_recognition/api/
  app.py
  routes_health.py
  routes_dashboard.py
  routes_audio.py
  routes_replay.py
  routes_settings.py
  routes_remote_command.py
  routes_envelopes.py

audio_recognition/services/
  asr_service.py
  envelope_service.py
  dashboard_service.py
  storage_service.py
  remote_command_service.py
```

---

## 8. 配置设计

### 8.1 `config/skills.yaml`

```yaml
actions:
  move_forward:
    route: action
    aliases:
      - 前进
      - 向前走
      - 往前走
    default_duration_ms: 800
    max_duration_ms: 1000

  move_backward:
    route: action
    aliases:
      - 后退
      - 向后退
      - 往后走
    default_duration_ms: 800
    max_duration_ms: 1000

  turn_right:
    route: action
    aliases:
      - 右转
      - 向右转
      - 往右转
    default_duration_ms: 600
    max_duration_ms: 800

  turn_left:
    route: action
    aliases:
      - 左转
      - 向左转
      - 往左转
    default_duration_ms: 600
    max_duration_ms: 800

faces:
  face_happy:
    route: face
    aliases:
      - 笑一笑
      - 微笑
      - 开心一点
    default_duration_ms: 3000

  face_blink:
    route: face
    aliases:
      - 眨眼
      - 眨眨眼
    default_duration_ms: 1000
```

### 8.2 `config/safety.yaml`

```yaml
min_confidence: 0.65

movement:
  max_single_duration_ms: 1000
  max_turn_duration_ms: 800
  max_sequence_actions: 3
  max_total_duration_ms: 10000

negative_words:
  - 不要
  - 别
  - 不许
  - 不用
  - 停止
  - 停一下
  - 别动
  - 不要动

emergency_words:
  - 急停
  - 停止
  - 停下
  - 刹车
  - 别动
  - 不要动

confirmation:
  enabled: true
  low_confidence_threshold: 0.65
```

### 8.3 `config/react_tools.yaml`

```yaml
tools:
  camera_snapshot:
    enabled: true
    requires_safety: false

  get_robot_state:
    enabled: true
    requires_safety: false

  dispatch_action:
    enabled: true
    requires_safety: true

  dispatch_face:
    enabled: true
    requires_safety: true

  emergency_stop:
    enabled: true
    priority: highest
    requires_safety: false

  ask_confirmation:
    enabled: true
    requires_safety: false

  finish:
    enabled: true
    requires_safety: false
```

### 8.4 `config/dispatch.yaml`

```yaml
dispatch_mode: local_first

local_first:
  enabled: true
  action_server: "http://127.0.0.1:8094"
  face_server: "http://127.0.0.1:8096"

cloud_queue:
  enabled: true
  action_server: "https://www.wangyutang.cn/action"
  face_server: "https://www.wangyutang.cn/face"

dry_run:
  enabled: true
```

---

## 9. 测试用例设计

### 9.1 简单指令

```yaml
- input: 前进
  expected_tool_calls:
    - tool: dispatch_action
      skill_id: move_forward
  expected_safety_allowed: true

- input: 右转
  expected_tool_calls:
    - tool: dispatch_action
      skill_id: turn_right
  expected_safety_allowed: true

- input: 笑一笑
  expected_tool_calls:
    - tool: dispatch_face
      skill_id: face_happy
  expected_safety_allowed: true
```

### 9.2 多步指令

```yaml
- input: 先往前走，然后右转
  expected_tool_calls:
    - tool: dispatch_action
      skill_id: move_forward
    - tool: dispatch_action
      skill_id: turn_right
  expected_order: sequential
  expected_safety_allowed: true
```

### 9.3 否定指令

```yaml
- input: 不要前进
  expected_safety_allowed: false
  expected_reason: negative_instruction_detected

- input: 别往前走
  expected_safety_allowed: false
  expected_reason: negative_instruction_detected
```

### 9.4 急停指令

```yaml
- input: 停止
  expected_tool_calls:
    - tool: emergency_stop
  expected_priority: highest

- input: 别动
  expected_tool_calls:
    - tool: emergency_stop
  expected_priority: highest
```

### 9.5 感知指令

```yaml
- input: 看看前面有没有障碍，安全的话前进
  expected_tool_calls:
    - tool: camera_snapshot
    - tool: dispatch_action
      skill_id: move_forward
  expected_condition: front_clear
```

---

## 10. 分阶段落地计划

### 10.1 第一阶段：统一 Envelope

目标：

```text
所有请求都生成 DecisionEnvelope
```

任务：

```text
1. 新增 envelope.py
2. 新增 envelope_id
3. 所有 result/event/case 关联 envelope_id
4. intermediate_store 改为 envelope_store
5. Dashboard 可以展示 envelope
```

验收：

```text
一条指令生成一个 envelope
envelope 包含 transcript / tool_calls / safety / dispatch_results
可以通过 envelope_id 查询完整链路
```

### 10.2 第二阶段：统一 ReAct Agent

目标：

```text
所有指令统一进入 ReAct Agent
```

任务：

```text
1. 新增 react_agent.py
2. 定义严格 JSON 输出
3. 简单指令输出单个 tool_call
4. 多步指令输出多个 tool_calls
5. 感知指令支持 camera_snapshot
```

验收：

```text
前进 -> dispatch_action(move_forward)
先前进再右转 -> 两个顺序 tool_call
看看前面安全再前进 -> camera_snapshot + dispatch_action
```

### 10.3 第三阶段：Tool Validator

目标：

```text
Agent 输出必须结构化、可校验
```

任务：

```text
1. 新增 tool_validator.py
2. 加工具白名单
3. 加 skill_id 白名单
4. 加参数 schema
5. 加未知工具拒绝
```

验收：

```text
jump -> rejected
duration_ms=99999 -> rejected or clipped
未知 tool -> rejected
```

### 10.4 第四阶段：Safety Guard

目标：

```text
所有真实执行前必须经过安全审查
```

任务：

```text
1. 新增 safety_guard.py
2. 否定词检测
3. 急停词检测
4. 动作限幅
5. 连续动作限制
6. 低置信度二次确认
```

验收：

```text
不要前进 -> 不执行 move_forward
别动 -> emergency_stop
duration_ms > 1000 -> 修正或拒绝
未知 skill_id -> 拒绝
```

### 10.5 第五阶段：Dispatcher

目标：

```text
Dispatcher 成为唯一真实硬件执行者
```

任务：

```text
1. 新增 dispatcher.py
2. 支持 tasks[] 串行执行
3. 支持 depends_on
4. 支持 wait_until completed
5. 支持 timeout
6. 支持 emergency_stop 打断
```

验收：

```text
先前进再右转 -> 串行执行
前进过程中急停 -> 当前动作中断，后续任务取消
执行结果写入 envelope.dispatch_results
```

### 10.6 第六阶段：Replay

目标：

```text
历史链路可回放、可 diff
```

任务：

```text
1. 新增 replay.py
2. 支持 from audio/text/tool_calls/tasks
3. replay 默认 dry_run
4. 输出 old/new envelope diff
```

验收：

```text
replay --from text 可重新生成 tool_calls
replay --from audio 可重跑 ASR + ReAct
replay 结果可 diff
```

### 10.7 第七阶段：体验优化

目标：

```text
提高交互自然度
```

任务：

```text
1. 固定 4 秒录音改 VAD
2. 增加录音反馈
3. 增加低置信度二次确认
4. 增加撤销上一条指令
5. 增加空闲行为
```

验收：

```text
用户说完自动停止录音
低置信度会询问确认
支持“取消刚才的动作”
无指令时有空闲表情或轻微动作
```

---

## 11. 不建议第一阶段做的内容

| 内容 | 原因 |
|---|---|
| 复杂事件总线 | 当前串行 ReAct + Dispatcher 足够 |
| 长期记忆 | 不是当前最核心问题 |
| 多模态深度融合 | 第一阶段用 camera_snapshot 摘要即可 |
| 完整云端 Agent 编排 | 本地机器人应先保证 local-first |
| 自由代码执行工具 | 风险过高，不应开放给 Agent |
| Agent 直接调用 ROS2/GPIO | 必须禁止 |
| 全栈异步化 | 先处理 ASR 长阻塞即可 |

---

## 12. Codex 执行建议

### 12.1 第一批任务

```text
请在 audio_recognition 分支中新增 DecisionEnvelope 体系：
1. 新建 audio_recognition/envelope.py
2. 定义 DecisionEnvelope、ToolCall、TaskStep 三个 Pydantic 模型
3. 所有 envelope 必须包含 envelope_id、device_id、source、t_created
4. 保持兼容当前 API，不要删除现有接口
5. 新增单元测试，验证 envelope 可序列化和反序列化
```

### 12.2 第二批任务

```text
请新增 ReAct Agent 外壳：
1. 新建 react_agent.py
2. 输入 transcript 和 robot_state
3. 输出严格 JSON，包含 reasoning_summary、tool_calls、final
4. 第一版可以使用规则实现，不接大模型
5. 支持“前进”“右转”“笑一笑”“先前进再右转”
6. 新增测试用例
```

### 12.3 第三批任务

```text
请新增 Tool Validator：
1. 新建 tool_validator.py
2. 校验 tool 是否在白名单
3. 校验 dispatch_action 的 skill_id 是否合法
4. 校验 duration_ms 是否超限
5. 校验失败时写入 envelope.errors
6. 新增测试：jump、duration_ms=99999 必须拒绝
```

### 12.4 第四批任务

```text
请新增 Safety Guard：
1. 新建 safety_guard.py
2. 支持否定词检测
3. 支持急停词检测
4. 支持 movement duration 限幅
5. 支持低置信度确认标记
6. “不要前进”不得执行 move_forward
7. “别动”“停止”必须转为 emergency_stop
```

### 12.5 第五批任务

```text
请新增 Dispatcher：
1. 新建 dispatcher.py
2. 从 envelope.tasks 串行执行任务
3. 支持 depends_on 和 wait_until
4. 支持 dry_run
5. 支持 emergency_stop 打断
6. 不允许 Agent 直接调用硬件
7. 执行结果写入 envelope.dispatch_results
```

### 12.6 第六批任务

```text
请改造 replay：
1. 新建 replay.py
2. 支持 --from audio/text/tool_calls/tasks
3. replay 默认 dry_run
4. 输出新旧 envelope diff
5. 保持现有 /api/intermediate/cases/{case_id}/replay 兼容
```

---

## 13. 最终验收标准

完成整改后，系统应满足：

```text
1. 任意指令都会生成 DecisionEnvelope
2. 简单指令和复杂指令都统一经过 ReAct Agent
3. Agent 只输出 tool_calls，不直接控制硬件
4. tool_calls 必须经过 Tool Validator
5. 真实动作必须经过 Safety Guard
6. Dispatcher 是唯一真实硬件执行者
7. 多步任务按顺序串行执行
8. emergency_stop 本地最高优先级执行
9. Replay 支持 audio/text/tool_calls/tasks
10. Cloud Dashboard 能查看完整 envelope
```

---

## 14. 示例链路

### 14.1 示例一：前进

```text
用户：前进
```

链路：

```text
ASR -> transcript="前进"
ReAct -> dispatch_action(move_forward, 800ms)
Validator -> passed
Safety -> allowed
Dispatcher -> move_forward completed
Store -> envelope saved
Dashboard -> show result
```

### 14.2 示例二：先前进再右转

```text
用户：先往前走，然后右转
```

链路：

```text
ASR -> transcript
ReAct -> tool_calls[move_forward, turn_right]
Validator -> passed
Safety -> allowed
Dispatcher:
  step_1 move_forward completed
  step_2 turn_right completed
Store -> envelope saved
Dashboard -> show sequence
```

### 14.3 示例三：不要前进

```text
用户：不要前进
```

链路：

```text
ASR -> transcript
ReAct -> 可能误判为 move_forward
Validator -> passed
Safety -> negative_instruction_detected
Dispatcher -> not executed
Store -> envelope saved
Dashboard -> show rejected
```

### 14.4 示例四：停止

```text
用户：停止
```

链路：

```text
ASR -> transcript
Safety / Agent -> emergency_stop
Dispatcher -> interrupt current action
Store -> envelope saved
Dashboard -> show emergency_stop
```

### 14.5 示例五：看前方安全再前进

```text
用户：看看前面有没有障碍，安全的话前进
```

链路：

```text
ASR -> transcript
ReAct -> camera_snapshot
Observation -> front_clear=true
ReAct -> dispatch_action(move_forward)
Safety -> allowed
Dispatcher -> move_forward completed
Store -> envelope saved
```

---

## 15. 总结

本次整改不是单纯增加功能，而是重构项目的核心控制范式。

整改前：

```text
语音 -> 文本 -> 单一 skill_id -> action/face 分发 -> 简单记录
```

整改后：

```text
语音/文本/远程命令
  -> DecisionEnvelope
  -> ReAct Agent
  -> Tool Calls
  -> Tool Validator
  -> Safety Guard
  -> Edge Dispatcher
  -> Observation
  -> Envelope Store
  -> Replay / Cloud Dashboard
```

最终系统应具备：

```text
统一决策
统一记录
统一审查
统一执行
统一回放
统一展示
```

核心原则：

> ReAct 可以统一所有指令，但它只能做受控决策外壳；真实机器人控制必须由 Safety Guard 和 Edge Dispatcher 接管。
