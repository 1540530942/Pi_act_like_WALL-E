# WALL·E ReAct 原型演进路线（无灰度实施版）

## 一、关键决策

| 项 | 决策 | 含义 |
|---|---|---|
| A. 协议方向 | A1 严格 1 tool_call / turn | 每轮只允许一个工具调用或 finish，形成标准 ReAct 循环 |
| B. VLM 选型 | B1 云端 VLM | 使用 Qwen-VL / GPT-4o / Doubao-vision 等 API |
| C. 延迟基线 | C1 接受 3–5s | 原型期优先清晰可调试，不做 batch 优化 |
| D. 老 planner | E1 P1 内下线 | 技能 yaml 化完成后，老 planner 主流程零引用 |

---

## 二、前置约束

1. **普通指令默认走 ReAct 循环**：每 turn 只允许 1 个 `tool_call` 或 `finish`。
2. **急停 / 停止 / 别动等安全指令走硬规则旁路**：不等待 LLM，直接触发 `emergency_stop`，同时写入 envelope。
3. **trace 优先**：每个 turn 都必须写入 envelope，能够独立回看。
4. **观察类指令走云端 VLM**：原型期接受 3–5s 端到端延迟。
5. **配置驱动**：技能、别名、参数、阈值、安全规则最终从 yaml 派生。
6. **协议一致性优先**：prompt、schema、validator、测试必须保持同一套 ReAct 单步协议。

---

## 三、总体架构原则

### 3.1 ReAct 单步协议

每轮 ReAct 只能返回以下三种结构之一。

#### 1. 工具调用

```json
{
  "type": "tool_call",
  "tool_call": {
    "name": "camera_snapshot",
    "arguments": {}
  }
}
```

#### 2. 结束循环

```json
{
  "type": "finish",
  "final": "已完成"
}
```

#### 3. 错误结果

```json
{
  "type": "error",
  "error": {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "LLM output is invalid"
  }
}
```

不允许一次输出多个工具调用：

```json
{
  "tool_calls": [
    {"name": "move_forward"},
    {"name": "turn_right"}
  ]
}
```

### 3.2 工具路径拆分

ReAct 工具分为两类。

| 类型 | 示例 | 处理方式 |
|---|---|---|
| 动作类工具 | `dispatch_action`, `dispatch_face`, `emergency_stop` | 生成 TaskStep，进入 dispatcher |
| 观察类工具 | `camera_snapshot`, `get_robot_state`, `ask_confirmation` | 生成 Observation，写回 messages，进入下一轮 ReAct |

核心原则：

```text
动作类工具负责“做事情”
观察类工具负责“获取信息”
LLM 根据 observation 决定下一步
```

### 3.3 action path 与 observation path

系统必须明确区分两条路径：

```text
action path:
tool_call → task → dispatcher → hardware → tool_result → messages → next turn

observation path:
tool_call → observation_executor → observation → messages → next turn
```

其中：

- 动作类工具面向真实硬件执行；
- 观察类工具面向状态、视觉、用户确认等信息获取；
- 两类结果都必须进入 envelope；
- LLM 只能基于上一轮 observation / tool_result 决定下一步。

---

## 四、P0 路线：协议对齐 + 观察闭环 + Edge envelope

P0 目标：让系统真正具备“先观察、再决策、再行动”的能力。

预计周期：约 2.5 周。

---

### P0-1 协议锁定为 A1：严格 1 tool_call / turn

周期：约 1 周。

#### 要做

1. 修改测试口径，先让测试符合 A1 协议。
2. 修改 prompt，强约束：

```text
你必须且只能输出一个 tool_call 或 finish。
不允许一次输出多个 tool_calls。
不允许输出 markdown、解释文字、代码块。
不允许输出 mock / dry_run / simulation 字段。
```

3. 增加 `protocol_version` 字段：

```json
{
  "protocol_version": "react_v1_single_tool"
}
```

4. 删除旧的多 `tool_calls` 批量规划协议。
5. 删除或改写违反单步协议的测试用例。
6. 建立统一 schema 校验逻辑：
   - 只接受 `type=tool_call`、`type=finish`、`type=error`；
   - `tool_call` 与 `finish` 不能同时出现；
   - `tool_call.name` 必须在 allowed tools 内；
   - `arguments` 必须符合对应工具 schema；
   - 不允许出现 `mock`、`dry_run`、`simulation` 等字段。

#### 测试改写要求

旧测试中如果存在一次返回多个 `tool_calls` 的 mock，例如：

```text
一次返回 move_forward、move_backward、look_up、look_down
```

必须改成多轮 ReAct：

```text
turn 1 → move_forward
turn 2 → move_backward
turn 3 → look_up
turn 4 → look_down
turn 5 → finish
```

#### 验收

- `run_turn` 行为、prompt、schema、测试完全一致。
- 多 tool_call 输入被明确拒绝，并写入 envelope.errors。
- 单步工具调用能稳定进入后续执行链。
- 旧的批量 tool_calls 协议在主流程中完全下线。

---

### P0-2 观察类工具落地

周期：约 2 周。

核心目标：

```text
不是简单“加 endpoint + 加 prompt”，
而是打通 observation path。
```

需要新增：

```text
observation_executor
```

它负责执行观察类工具，并将结果写入：

```text
messages
react_turns
envelope.observations
```

#### observation_executor 职责

1. 接收观察类 `tool_call`。
2. 判断工具类型。
3. 调用对应 endpoint 或本地能力。
4. 校验返回 schema。
5. 生成结构化 observation。
6. 将 observation 写入 envelope。
7. 将 observation 追加到 ReAct messages，供下一轮 LLM 决策。

---

### P0-2a get_robot_state

周期：约 0.5 天。

#### 要做

实现 endpoint，返回机器人基础状态：

```json
{
  "battery_pct": 82,
  "orientation_deg": 90,
  "last_action": "move_forward",
  "ts": 1710000000
}
```

加入 agent prompt allowed tools：

```text
get_robot_state
```

#### 验收

用户说：

```text
电量够吗？
```

LLM 能够调用：

```json
{
  "type": "tool_call",
  "tool_call": {
    "name": "get_robot_state",
    "arguments": {}
  }
}
```

系统返回结构化 observation，LLM 再根据电量回答或继续决策。

---

### P0-2b ask_confirmation

周期：约 2 天。

#### 要做

实现确认工具：

```json
{
  "question": "我理解你是想让我往前走，对吗？",
  "timeout_s": 10
}
```

返回确认结果：

```json
{
  "confirmed": true,
  "answer": "yes",
  "timeout": false
}
```

或超时降级：

```json
{
  "confirmed": false,
  "answer": null,
  "timeout": true
}
```

#### 前端最小 UI

实现一个最小 yes/no 确认框：

```text
问题文本：LLM 生成或系统生成的确认问题
按钮：是 / 否
超时：默认 10 秒
超时结果：视为否定
```

#### 注意

`ask_confirmation` 会等待用户回答，容易阻塞主流程。

原型阶段可以先做同步最小版：

```text
P0 先做同步最小版，仅用于单设备原型验证；
P1 异步化时改成 pending / continue 模式。
```

#### 验收

低置信度 ASR 或高风险动作时：

```text
LLM 调用 ask_confirmation
用户点击 yes / no
结果进入 observation
LLM 根据 observation 继续或 finish
```

---

### P0-2c camera_snapshot

周期：约 1 周。

#### 要做

1. 选定云端 VLM provider：

```text
优先：Qwen-VL 或 GPT-4o
备选：Doubao-vision
```

2. 实现 endpoint：

```text
拍照 → 上传图片 → 调用 VLM → 返回结构化 JSON
```

3. 固定返回 schema：

```yaml
has_person: bool
person_count: int
obstacles:
  - string
scene_caption: string
confidence: float
```

示例返回：

```json
{
  "has_person": true,
  "person_count": 1,
  "obstacles": ["person", "chair"],
  "scene_caption": "前方有一名人员，左侧空间相对空旷。",
  "confidence": 0.86
}
```

4. VLM prompt 必须约束严格 JSON：

```text
只输出 JSON，不输出 markdown、解释文字或代码块。
字段必须包含 has_person、person_count、obstacles、scene_caption、confidence。
```

5. 加入 agent prompt allowed tools：

```text
camera_snapshot
```

#### fallback 策略

如果 VLM 返回非 JSON 或 schema 不合法，统一降级为：

```json
{
  "has_person": false,
  "person_count": 0,
  "obstacles": [],
  "scene_caption": "视觉结果不可用",
  "confidence": 0.0,
  "error": "VLM_SCHEMA_INVALID"
}
```

#### 验收

用户说：

```text
看前面有人就左拐。
```

期望 ReAct 过程：

```text
turn 1: camera_snapshot
turn 2: 根据 observation 判断 has_person=true
turn 3: dispatch_action(turn_left)
turn 4: finish
```

端到端延迟控制在 3–5s 左右。

---

### P0-3 Edge envelope 打通

周期：约 3 天，可与 P0-2 并行。

#### 要做

1. `edge_audio_listener` 在录音 / 转写阶段即构建 envelope。
2. 填入：

```yaml
audio_ref: 音频文件引用
asr_meta: ASR 元信息
t_capture: 录音时间戳
t_transcribe: 转写时间戳
source_chain: 边云流转链路
```

3. Cloud `route_transcript` 直接接收 Edge 上传的 envelope，不再重新构建。
4. `transcribe_audio_path` 只负责 ASR，不再调用 `plan_transcript`。
5. Edge 构建 envelope 后交给统一 ReAct 决策链。

#### source_chain 示例

```json
[
  {
    "node": "edge_audio_listener",
    "stage": "capture",
    "ts": 1710000000
  },
  {
    "node": "edge_audio_listener",
    "stage": "asr",
    "ts": 1710000002
  },
  {
    "node": "cloud_route_transcript",
    "stage": "react_decision",
    "ts": 1710000003
  }
]
```

#### 验收

- 边端生成完整 envelope。
- Cloud 能校验 Edge envelope schema。
- replay `from=audio` 能走通。
- Edge 到 Cloud 的 envelope 字段不丢失。
- 老 planner 不再夹在 ASR 与 ReAct 之间。

---

## 五、P1 路线：技能 yaml 化 + 老 planner 下线 + 异步化

P1 目标：让系统从“能跑”升级为“可扩展、可维护”。

预计周期：约 3 周。

---

### P1-1 技能 yaml schema 定义

周期：约 1 天。

#### 要做

新增：

```text
schemas/skill_contract.schema.json
```

必填字段：

```yaml
id: string
brief: string
category: action | face | observation | system
route: action | face | observation | system
endpoint: string
params: object
risk: low | medium | high
```

可选字段：

```yaml
pre_conditions: object
cancellable: bool
estimated_ms: int
aliases:
  - string
examples:
  - string
```

#### schema 设计原则

1. yaml 是技能单一信息源。
2. `params` 供 validator 使用。
3. `pre_conditions` 和 `risk` 供 safety_guard 使用。
4. `route` 和 `endpoint` 供 dispatcher 使用。
5. `aliases` 供 voice_intents 使用。
6. `examples` 供测试和 few-shot 使用。

#### 验收

任意技能 yaml 必须通过 schema 校验。

---

### P1-2 单技能试点

周期：约 1 天。

#### 要做

先选择最简单的动作技能：

```text
reset_pose
```

转成 yaml：

```yaml
id: reset_pose
brief: 恢复默认姿态
category: action
route: action
endpoint: /action/reset_pose
params: {}
risk: low
estimated_ms: 1000
aliases:
  - 复位
  - 回到默认姿态
examples:
  - 回到默认姿态
  - 复位一下
```

新增：

```text
skill_registry.py
```

功能：

```text
启动时加载所有 yaml
校验 schema
生成 registry
与旧硬编码能力做一致性校验
```

#### 验收

`reset_pose` 通过 yaml 和旧硬编码两条路径运行结果一致。

---

### P1-3 动作类批量迁移

周期：约 3 天。

#### 要做

将动作类技能迁移到 yaml：

```text
move_forward
move_backward
turn_left
turn_right
look_up
look_down
look_left
look_right
reset_pose
emergency_stop
```

如果实际项目中还有其他动作技能，以当前 skill catalog 为准。

#### 验收

- 行为与旧硬编码完全一致。
- 修改 yaml 参数后，对应 validator / prompt 行为可变化。
- 所有动作类技能均能从 registry 加载。
- 不再依赖分散的硬编码动作枚举。

---

### P1-4 表情类批量迁移

周期：约 2 天。

#### 要做

将表情类技能迁移到 yaml，例如：

```text
face_happy
face_sad
face_angry
face_surprised
face_blink
face_idle
face_sleep
face_wink
```

以当前仓库实际表情技能为准。

#### 验收

- 表情行为与旧硬编码完全一致。
- LLM prompt 中 allowed face skills 可从 registry 自动生成。
- 表情技能不再依赖分散硬编码枚举。

---

### P1-5 上层模块改读 registry

周期：约 1 周。

按依赖顺序逐项切换。

#### 1. react_agent prompt 改读 registry

从 registry 自动生成 allowed tools / allowed skills。

验收：

```text
新增 yaml 技能后，prompt 自动出现该技能。
```

#### 2. tool_validator 参数 / 上限改读 registry

从 yaml 的 `params`、`risk`、`pre_conditions` 生成校验规则。

验收：

```text
修改 yaml 参数上限后，validator 行为立即变化。
```

#### 3. safety_guard 前置条件改读 registry

从 yaml 中读取：

```yaml
pre_conditions
risk
cancellable
```

验收：

```text
高风险动作可以自动触发 ask_confirmation。
```

#### 4. dispatcher 按 route + endpoint 选发

从 yaml 中读取：

```yaml
route
endpoint
```

验收：

```text
新增同类型动作技能时，不需要改 dispatcher 主逻辑。
```

#### 5. voice_intents 别名表改读 registry

从 yaml 中读取：

```yaml
aliases
```

验收：

```text
增加新别名只改 yaml。
```

#### 6. 测试 fixture 从 examples 派生

从 yaml 中读取：

```yaml
examples
```

验收：

```text
新增技能样例可自动进入测试样本。
```

---

### P1-6 老 planner 下线

周期：约 2 天。

#### 要做

1. `transcribe_audio_path` 不再调用 `plan_transcript`。
2. 主流程统一调用：

```text
decide_transcript / decide_envelope
```

3. 标记 deprecated：

```text
LlmTaskPlanner
RuleBasedTaskPlanner
plan_transcript
```

4. 删除 `config.example.json` 中老 `planner` 配置。
5. 保留 legacy 代码作为短期参考，但主流程零引用。

#### 验收

执行：

```bash
grep -R "plan_transcript" audio_recognition/
```

要求：

```text
主流程零命中
仅允许 legacy / tests / deprecated 目录命中
```

---

### P1-7 ReAct 与 dispatcher 异步化

周期：约 3 天。

#### 要做

1. `react_agent` 中：

```text
requests.post → httpx.AsyncClient
```

2. dispatcher 中：

```text
_post_json / _fetch_json → async
```

3. FastAPI 路由改为：

```python
async def
```

4. ask_confirmation 改造成 pending / continue 模式。

#### pending / continue 模式说明

同步版确认流程：

```text
LLM → ask_confirmation → 等用户回答 → 继续
```

异步版确认流程：

```text
LLM → ask_confirmation → 返回 pending
用户回答 → continue_react_turn → 继续
```

#### 验收

- 并发压测下 FastAPI 不再被 ReAct 循环阻塞。
- 多个语音请求不会互相卡死。
- ask_confirmation 等待用户时不会阻塞整个服务。

---

### P1-8 词表 / 阈值配置化

周期：约 2 天。

#### 要做

1. `voice_intents` 别名迁移到：

```text
config/intents.yaml
```

2. `safety_guard` 中的否定词、急停词、阈值迁移到：

```text
config/safety.yaml
```

示例：

```yaml
emergency_words:
  - 停
  - 停止
  - 急停
  - 别动

negative_words:
  - 不要
  - 别
  - 不用
  - 取消

limits:
  max_duration_s: 5
  max_turn_deg: 90
```

3. 否定词从裸子串匹配改为窗口距离判定。

错误示例：

```text
我不要怕，前进吧
```

不应被误判为否定前进。

正确示例：

```text
不要前进
别往前走
取消前进
```

应拦截 `move_forward`。

#### 验收

- “我不要怕，前进吧”不再误触发否定。
- “不要往前走了”不会生成或执行 `move_forward`。
- 新增口令只需改 yaml + fixture。

---

## 六、错误处理与日志要求

### 6.1 错误分类

所有失败都必须写入 envelope.errors，至少包含：

```yaml
stage: string
code: string
message: string
raw_response: optional
ts: number
```

推荐错误码：

```text
MISSING_LLM_CONFIG
LLM_CALL_FAILED
INVALID_JSON
SCHEMA_VALIDATION_FAILED
TOOL_NOT_ALLOWED
TOOL_ARGUMENT_INVALID
SAFETY_REJECTED
OBSERVATION_FAILED
VLM_SCHEMA_INVALID
DISPATCH_FAILED
CONFIRMATION_TIMEOUT
```

### 6.2 trace 字段

每个 ReAct turn 至少记录：

```yaml
turn_id: int
input_messages_ref: string
thought: string
tool_call: object
observation: object
latency_ms: int
error: object | null
```

### 6.3 latency 记录

至少记录：

```yaml
t_capture: number
t_transcribe: number
t_react_start: number
t_llm_done: number
t_tool_start: number
t_tool_done: number
t_react_finish: number
```

---

## 七、暂缓项

以下内容不进入本期：

```text
Batch 模式 / 双模式分流
多模态端到端 / VLA
垂域 Agent 拆分
长期记忆 / 自主行为
Reflexion 失败反思
反射层独立进程
完整 VAD 链路
```

说明：

```text
VAD 可以后续做，但不作为本期阻塞项。
原型期重点是 ReAct 协议、观察闭环、技能契约。
```

---

## 八、原型期完成验收

### 8.1 基础动作

用户说：

```text
前进然后右转
```

系统应通过多轮 ReAct 跑通：

```text
turn 1: dispatch_action(move_forward)
turn 2: dispatch_action(turn_right)
turn 3: finish
```

### 8.2 视觉观察

用户说：

```text
看前面有人就左拐
```

系统应跑通：

```text
turn 1: camera_snapshot
turn 2: 根据 has_person=true 判断
turn 3: dispatch_action(turn_left)
turn 4: finish
```

### 8.3 状态查询

用户说：

```text
电量够不够走到客厅
```

系统应跑通：

```text
turn 1: get_robot_state
turn 2: 根据 battery_pct 判断是否继续
turn 3: 必要时 ask_confirmation 或 finish
```

### 8.4 低置信度确认

ASR 低置信度时：

```text
turn 1: ask_confirmation
turn 2: 用户回答 yes / no
turn 3: 根据回答继续或 finish
```

### 8.5 envelope 完整性

任意指令都应产出完整 envelope，至少包含：

```yaml
protocol_version: react_v1_single_tool
audio_ref: string
asr_meta: object
source_chain: list
react_turns:
  - thought: string
    tool_call: object
    observation: object
    latency_ms: int
errors: list
final_response: string
```

### 8.6 技能扩展

新增同类型动作技能时：

```text
加 yaml + 实现 endpoint
不改 react_agent / validator / dispatcher 主业务代码
```

注意：

```text
新增工具类型、观察类型或安全策略时，允许少量核心代码接入。
```

### 8.7 老 planner 下线

要求：

```text
旧 plan_transcript 主流程零引用
老 planner 只保留在 legacy / deprecated / tests 中
```

---

## 九、总工期

```text
P0：约 2.5 周
P1：约 3 周
----------------
合计：约 4.5–5.5 周
```

---

## 十、推荐执行顺序

```text
1. 先改测试，统一 A1 单步协议
2. 增加 protocol_version 与 schema 校验
3. 删除旧多 tool_calls 主流程协议
4. 新增 observation_executor
5. 落地 get_robot_state
6. 落地 ask_confirmation
7. 落地 camera_snapshot + 云端 VLM
8. Edge envelope 去掉老 planner 残留
9. 定义 skill yaml schema
10. reset_pose 单技能试点
11. 动作 / 表情技能批量迁移
12. prompt / validator / safety / dispatcher 改读 registry
13. 老 planner 主流程下线
14. ReAct 与 dispatcher 异步化
15. 词表与阈值配置化
```

---

## 十一、一句话总结

协议锁定 A1，视觉走云端 VLM，延迟接受 3–5s，技能 yaml 化完成后下线老 planner。

本期最关键的不是“多加几个工具”，而是把 ReAct 的两条路径分清楚：

```text
action path：tool_call → task → dispatcher → hardware
observation path：tool_call → observation → messages → next ReAct turn
```

这两条路径打通后，WALL·E 才能真正做到：

```text
先看见 → 再理解 → 再行动
```
