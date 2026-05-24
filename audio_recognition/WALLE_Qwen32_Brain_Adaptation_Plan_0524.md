# WALL-E qwen3-32b 大脑适配工程规划 0524

## 目标

将 `audio_recognition` 的机器人认知层切换为统一公网 Common API 中的 qwen3-32b tools 接口，并把 `WALL-E人格契约与能力清单_0524.md` 中的人格、工具、技能、安全约束落成可维护的工程结构。

目标链路：

```text
audio_recognition
-> ASR 文本 / 手动文本
-> ReAct agent
-> https://www.wangyutang.cn/common/api/llm/qwen3-32b/chat/completions
-> qwen3-32b native tool_calls
-> validator
-> safety_guard
-> observation / dispatcher
-> action_move / face / finish
```

核心原则：

- Common API 是唯一 LLM 对外入口，`audio_recognition` 不直接绑定 DashScope key。
- qwen3-32b 是当前机器人“大脑”，默认使用原生 `tool_calls`。
- 每个 ReAct turn 只执行一个 tool_call。
- 人格契约用于约束“怎么想、怎么说”，技能 registry 用于约束“能做什么、参数边界是什么”。
- 安全约束必须在模型之外再执行一次，不能只靠 prompt。

## 当前工程状态

已经具备：

- `pipeline.py` 已经是 transcript -> ReAct -> validator -> safety -> dispatcher 主链路。
- `react_agent.py` 支持 OpenAI/Qwen 风格原生 `tool_calls`。
- `tool_call_adapter.py` 能把 native `tool_calls` 归一化为内部 `ToolCall`。
- `tool_schema.py` 已从 YAML registry 生成工具 schema。
- `tool_validator.py` 已从 YAML registry 读取技能白名单和 duration 限制。
- `skills/registry.yaml` 已作为初步技能源。
- `safety_guard.py` 已有急停、否定词、动作次数、总时长、低置信度限制。
- `observation_executor.py` 已有 `camera_snapshot` / `get_robot_state` / `ask_confirmation` 的执行入口。

主要缺口：

- 默认 LLM 仍是 `qwen3.5-9b`。
- WALL-E 人格契约还没有外置为 prompt 文件。
- `skills/registry.yaml` 字段过薄，不足以承载 0524 文档中的完整技能契约。
- tool schema 与 0524 文档的参数命名不完全一致。
- safety guard 还没有消费 registry 的 `pre_conditions`。
- 观察类工具还没有完整的“近期 observation 复用 / 缺失则先观察 / 条件成立后再行动”机制。
- `say` / `emotion` / face 表达约束还没有工程化。
- 0524 md 当前存在乱码风险，不适合直接作为 prompt 原文注入。

## 分阶段规划

### P0：固定 qwen3-32b 大脑入口

目标：让当前 ReAct 主链路默认使用已验证的 Common API qwen3-32b tools 接口。

改动：

- 更新 `config.example.json`：
  - `react_agent.llm.endpoint = https://www.wangyutang.cn/common/api/llm/qwen3-32b/chat/completions`
  - `react_agent.llm.model = qwen3-32b`
- 更新 `react_agent.py` 默认值：
  - `DEFAULT_LLM_ENDPOINT`
  - `DEFAULT_LLM_MODEL`
- 保持环境变量覆盖：
  - `AUDIO_REACT_LLM_ENDPOINT`
  - `AUDIO_REACT_LLM_MODEL`
- 保留旧 qwen3.5-9b 作为显式配置可选项，不作为默认大脑。

验收：

- dry-run 输入 `前进`，LLM 返回 native `tool_calls`。
- dry-run 输入 `前进、向右转一下，记得后退，别忘了抬头看`，产生逐 turn 的单 tool_call 序列。
- envelope 中记录 `model=qwen3-32b` 和 Common API 原始返回。

### P1：外置 WALL-E system prompt

目标：把人格契约从硬编码 prompt 中拆出来，形成可维护 prompt 文件。

新增：

```text
prompts/walle_system_prompt.md
```

内容边界：

- WALL-E 身份定位。
- ReAct 单 turn 单 tool_call 约束。
- 观察后行动约束。
- 否定指令、急停指令处理原则。
- 说话风格和 `say` 限制。
- 错误处理原则。
- 不直接包含具体技能参数上限，避免和 registry 冲突。

改动：

- `react_agent.py` 新增 prompt 加载函数。
- prompt 路径支持配置：
  - `react_agent.prompt_path`
  - `AUDIO_REACT_SYSTEM_PROMPT`
- `_system_prompt()` 拼接：
  - 外置人格 prompt
  - registry 生成的工具/技能摘要
  - 当前协议版本和输出约束

验收：

- prompt 文件不存在时使用内置最小安全 prompt。
- prompt 文件存在时进入 LLM 请求 messages[0]。
- 测试确认 prompt 中包含 `WALL-E`、`react_v1_single_tool`、`one tool_call`。

### P2：清洗 0524 文档并拆分为工程源

目标：避免乱码文档直接污染 prompt，将其拆成工程可消费的源文件。

新增或调整：

```text
prompts/walle_system_prompt.md
docs/WALLE_PERSONA_CONTRACT_0524.clean.md
```

处理方式：

- 保留原始 `WALL-E人格契约与能力清单_0524.md` 不覆盖。
- 新建 clean 版，使用标准 UTF-8。
- 人格内容进 prompt。
- 工具/技能内容进 registry/schema。
- 安全规则进 safety guard 配置。

验收：

- clean 文档可正常显示中文。
- prompt 文件不含乱码。
- 旧文档只作为来源记录，不作为运行时输入。

### P3：升级技能 registry 为单一信息源

目标：让 registry 承载 0524 文档中的技能契约，而不只是 `id/route/tool/max_duration`。

建议 schema：

```yaml
version: 2
defaults:
  max_action_duration_ms: 1000
  max_turn_duration_ms: 800
  max_face_duration_ms: 5000
  max_sequence_actions: 3
  max_total_duration_ms: 10000
  min_confidence: 0.65
skills:
  - id: move_forward
    brief: Move a short step forward.
    category: action
    route: action
    tool: dispatch_action
    endpoint: /api/action/execute
    aliases: [前进, 向前走, 往前走, 朝前走]
    params:
      duration_ms: {type: int, default: 800, min: 200, max: 1000}
    pre_conditions:
      - obs.front_distance_estimate_cm > 15
    risk: medium
    cancellable: true
    estimated_ms: 800
    examples:
      - input: 前进
        args: {duration_ms: 800}
```

改动：

- `skill_registry.py`
  - 扩展 `SkillSpec` 字段。
  - 兼容 v1 registry。
  - 输出 params、risk、pre_conditions、examples。
- `tool_schema.py`
  - 使用 registry params 生成参数 schema。
  - tool description 使用 `brief/risk/pre_conditions` 摘要。
- `tool_validator.py`
  - 按 registry params 校验。
  - 不再手写 duration 逻辑。
- tests 补 registry v2 兼容。

验收：

- schema、validator、prompt 摘要都来自同一份 registry。
- 修改某个技能 duration 后，schema 和 validator 同步变化。
- 旧 v1 registry 测试仍通过。

### P4：对齐 0524 工具契约

目标：让工具参数与 0524 文档一致，减少模型理解偏差。

工具调整：

- `dispatch_action`
  - 保留 `skill_id`
  - 支持 `duration_ms`
  - 保留 `wait_until`
  - 保留 `confidence`
  - 保留 `text`
- `dispatch_face`
  - 增加 `intensity`
  - 保留 `duration_ms`
  - 保留 `text`
- `camera_snapshot`
  - 从 `reason` 改为兼容支持 `focus` + `purpose`
  - 兼容旧 `reason`
- `get_robot_state`
  - args 默认为空对象
- `ask_confirmation`
  - 从 `timeout_s` 迁移到 `timeout_ms`
  - 兼容旧 `timeout_s`
- `finish`
  - 统一 `message`
  - 兼容旧 `final`

验收：

- qwen3-32b 返回 0524 格式参数能被 validator 接收。
- 旧测试中的 `timeout_s/final/reason` 不立即失效。
- envelope 中保留归一化后的 args。

### P5：把 pre_conditions 接入 safety_guard

目标：安全规则不只靠 prompt，而是运行时强制执行。

新增能力：

- `safety_guard.py` 读取 registry defaults：
  - `max_sequence_actions`
  - `max_total_duration_ms`
  - `min_confidence`
- `safety_guard.py` 读取 skill pre_conditions。
- 新增 observation 查询工具：
  - 找最近一次相关 observation。
  - 判断 observation 是否过期。
  - 无 observation 时拒绝高风险动作并要求先观察。

首批 pre_conditions：

```text
move_forward requires obs.front_distance_estimate_cm > 15
long/high-risk action requires recent get_robot_state
battery_pct < 10 rejects action
battery_pct < 5 rejects camera_snapshot
```

验收：

- 无前方距离 observation 时，`move_forward` 被标记为需要观察，不能直接执行。
- `front_distance_estimate_cm <= 15` 时拒绝 `move_forward`。
- `emergency_stop` 永远最高优先级，绕过普通 pre_conditions。

### P6：Observation 闭环增强

目标：模型能先观察，再基于 observation 决策下一步。

当前已有：

- `camera_snapshot`
- `get_robot_state`
- `ask_confirmation`
- Observation 结果会写入 `messages`。

需要增强：

- `camera_snapshot` 返回 0524 固定 schema：
  - `has_person`
  - `person_count`
  - `obstacles`
  - `scene_caption`
  - `front_distance_estimate_cm`
  - `confidence`
- observation 添加 TTL：
  - camera 2s throttle
  - robot_state 5s reuse
- `ask_confirmation` 和真实 UI/语音确认链路衔接。

验收：

- 条件指令“如果前面没人就往前走”先触发 `camera_snapshot`。
- observation 返回后下一 turn 再决定是否 `dispatch_action`。
- camera 未配置时，模型应 `finish` 或 `ask_confirmation`，不能盲动。

### P7：人格输出和 say 约束工程化

目标：WALL-E 的“少说话、多动作/表情”不只靠 prompt。

新增：

- `speech_guard.py` 或 `persona_guard.py`

规则：

- `say/message/text` 不超过短 token 限制。
- 允许：
  - `WALL-E`
  - 伙伴名字
  - beep / boop / whirr / click / ohh / uh-oh / hmm
  - yes / no / stop / look / hello / thank you
- 禁止：
  - 长句解释
  - 自称 AI/语言模型
  - 技术术语式对话

落点：

- validator 归一化 `finish.message`
- dispatch_face / future TTS 调用前校验 `say`
- 超限时转为 face/emotion 或短拟声词

验收：

- 模型输出长 `finish.message` 会被截断或替换为安全短语。
- 工具 args 中长 `text/say` 不进入执行端。

### P8：qwen3-32b 实车前回归矩阵

目标：确保新大脑不会破坏现有可执行链路。

必测文本：

```text
不要动
前进
后退
前进、向右转一下，记得后退，别忘了抬头看
先往前走，再往后走，抬头看，不要往前走了，低头看
不要动、向右转一下，记得后退，别忘了抬头看
如果前面没有障碍物，就往前走
电量够不够
看一下前面
```

每条检查：

- 是否调用 qwen3-32b Common API。
- 是否原生 tool_calls。
- 是否每 turn 只执行一个工具。
- 是否正确处理否定片段。
- 是否正确进入 observation。
- 是否 envelope trace 可回放。
- dry_run 与真实 dispatch 是否解耦。

### P9：真实机器人验证

目标：在树莓派安全围栏下验证实车链路。

前置检查：

- ROS2 `/cmd_vel` 可用。
- action server health 正常。
- face server health 正常。
- Common API qwen3-32b health 正常。
- `dispatch_mode=local_first` 或当前真实执行模式明确。

实车命令：

```text
前进、后退
先往前走，再往后走，抬头看，不要往前走了，低头看
不要动、向右转一下，记得后退，别忘了抬头看
```

验收：

- 急停/不要动不会执行后续动作。
- 否定的“不要往前走了”不会生成第二个 forward。
- 每个动作完成后有 observation/result 写回。
- 实车执行结果与 dry_run envelope 结构一致。

## 不建议做的事情

- 不要把所有 skill 都暴露成独立 tool。保持少量工具入口，技能作为参数。
- 不要让 `audio_recognition` 直接使用 DashScope key。统一走 Common API。
- 不要把 0524 原始 md 直接塞进 prompt，先清洗编码。
- 不要让模型决定安全边界。模型可以建议，validator/safety 必须最终裁决。
- 不要恢复老 planner 作为主流程 fallback。LLM 失败时应该显式失败或 ask/finish。

## 推荐实施顺序

1. P0：切 qwen3-32b 默认大脑。
2. P1：外置 prompt。
3. P4：对齐工具参数，保持兼容。
4. P3：registry v2 扩展。
5. P5：pre_conditions 接入 safety。
6. P6：observation 闭环增强。
7. P7：人格 say 约束。
8. P8：回归矩阵。
9. P9：实车验证。

## 第一批最小可交付

最小但有价值的一批改动：

- 默认 LLM 切到：
  - `https://www.wangyutang.cn/common/api/llm/qwen3-32b/chat/completions`
  - `qwen3-32b`
- 新增 `prompts/walle_system_prompt.md`。
- `react_agent.py` 支持加载外部 prompt。
- `tool_schema.py` 支持 0524 的 `focus/purpose/timeout_ms/message/intensity`。
- `tool_validator.py` 对旧字段做兼容归一化。
- 新增 qwen3-32b dry-run 回归用例。

这批完成后，就可以先让 qwen3-32b 作为 WALL-E 大脑跑完整 ReAct dry-run，再进入 registry v2 和 safety pre_conditions 的深水区。
