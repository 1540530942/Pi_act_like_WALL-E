# 2026-05-24 qwen3-32b WALL-E 实车数据链路流程图

## 总览

```mermaid
flowchart TD
    A[用户语音 / 手动文本] --> B{输入来源}
    B -->|语音| C[ASR: Common API /asr/transcribe]
    B -->|手动文本| D[原始文本 transcript]
    C --> D

    D --> E[DecisionEnvelope 初始化]
    E --> F{急停预检?}
    F -->|命中 不要动/急停/停止| G[直接生成 emergency_stop ToolCall]
    F -->|未命中| H[ReAct Agent]

    H --> I[System Prompt]
    H --> J[Skill Registry / Tool Schema]
    I --> K[qwen3-32b Common API]
    J --> K

    K --> L[native tool_calls]
    L --> M[tool_call_adapter 归一化]
    M --> N[ToolCall]

    G --> O[tool_validator]
    N --> O
    O --> P{工具/技能/参数合法?}
    P -->|否| Q[记录 validator error]
    P -->|是| R[TaskStep]

    R --> S[safety_guard]
    S --> T{安全允许?}
    T -->|否| U[Task rejected / 需要确认]
    T -->|是| V{tool 类型}

    V -->|observation| W[observation_executor]
    W --> X[observation 写入 envelope]
    X --> Y[tool result message 回写 ReAct]
    Y --> H

    V -->|finish| Z[final_response]

    V -->|dispatch_action / emergency_stop| AA[dispatcher]
    AA --> AB{dispatch_mode}
    AB -->|dry_run| AC[不发实车动作, 记录 dry_run]
    AB -->|local_first| AD[POST action controller /execute]
    AB -->|cloud_queue| AE[POST cloud action task]

    AD --> AF[action_move edge_ros_controller]
    AF --> AG{skill_id}
    AG -->|move_forward / turn_left 等| AH[ROS2 /cmd_vel]
    AG -->|look_up / look_down 等| AI[云台舵机 topic]
    AG -->|emergency_stop| AJ[零速度 Twist / stop]

    AH --> AK[TurboPi 实车动作]
    AI --> AK
    AJ --> AK

    AK --> AL[执行结果 + health]
    AL --> AM[dispatch_result]
    AM --> AN[observation 记录]
    AN --> AO[tool result message 回写 ReAct]
    AO --> H

    Z --> AP[Envelope 完成]
    AC --> AP
    Q --> AP
    U --> AP

    AP --> AQ[envelope.raw / react_turns / observations / dispatch_results]
    AQ --> AR[problem_md 验证记录]
```

## 实车链路细节

```mermaid
flowchart LR
    A[audio_recognition pipeline] --> B[dispatch_task local_first]
    B --> C[HTTP POST http://192.168.1.46:8765/execute]
    C --> D[action_move edge_ros_controller]
    D --> E[turbopi Docker container]
    E --> F[ROS2 Humble]
    F --> G1[/cmd_vel]
    F --> G2[/ros_robot_controller/pwm_servo/set_state]
    G1 --> H1[底盘移动/转向]
    G2 --> H2[摄像头云台]
    H1 --> I[执行结果]
    H2 --> I
    I --> J[GET /health]
    J --> K[写入 dispatch_results / observations]
```

## 两条已验证指令的数据路径

### 1. `先前进再向上看`

```mermaid
sequenceDiagram
    participant User as 用户
    participant Pipeline as audio_recognition.pipeline
    participant Agent as ReAct Agent
    participant LLM as qwen3-32b Common API
    participant Validator as tool_validator
    participant Safety as safety_guard
    participant Dispatcher as dispatcher local_first
    participant Controller as 192.168.1.46:8765 edge_ros_controller
    participant Robot as TurboPi / ROS2

    User->>Pipeline: 先前进再向上看
    Pipeline->>Agent: messages(system + user)
    Agent->>LLM: chat/completions tools
    LLM-->>Agent: tool_call dispatch_action(move_forward, text=前进)
    Agent->>Validator: ToolCall move_forward
    Validator-->>Agent: TaskStep move_forward
    Agent->>Safety: safety check
    Safety-->>Agent: allowed=true
    Agent->>Dispatcher: dispatch move_forward
    Dispatcher->>Controller: POST /execute action=move_forward
    Controller->>Robot: ROS2 /cmd_vel
    Robot-->>Controller: completed
    Controller-->>Dispatcher: ok=true, last_action=move_forward
    Dispatcher-->>Agent: tool result completed

    Agent->>LLM: messages + tool result
    LLM-->>Agent: tool_call dispatch_action(look_up, text=向上看)
    Agent->>Validator: ToolCall look_up
    Validator-->>Agent: TaskStep look_up
    Agent->>Safety: safety check
    Safety-->>Agent: allowed=true
    Agent->>Dispatcher: dispatch look_up
    Dispatcher->>Controller: POST /execute action=look_up
    Controller->>Robot: servo look_up
    Robot-->>Controller: completed
    Controller-->>Dispatcher: ok=true, last_action=look_up
    Dispatcher-->>Agent: tool result completed

    Agent->>LLM: messages + tool result
    LLM-->>Agent: finish(done)
    Agent-->>Pipeline: final_response=done
```

结果：

```text
move_forward completed action_ok=true
look_up completed action_ok=true
finish done
```

### 2. `左转，不要往上看`

```mermaid
sequenceDiagram
    participant User as 用户
    participant Pipeline as audio_recognition.pipeline
    participant Agent as ReAct Agent
    participant LLM as qwen3-32b Common API
    participant Validator as tool_validator
    participant Safety as safety_guard
    participant Dispatcher as dispatcher local_first
    participant Controller as 192.168.1.46:8765 edge_ros_controller
    participant Robot as TurboPi / ROS2

    User->>Pipeline: 左转，不要往上看
    Pipeline->>Agent: messages(system + user)
    Agent->>LLM: chat/completions tools
    LLM-->>Agent: tool_call dispatch_action(turn_left, text=左转)
    Note over LLM,Agent: 否定片段“不要往上看”未生成 look_up
    Agent->>Validator: ToolCall turn_left
    Validator-->>Agent: TaskStep turn_left
    Agent->>Safety: safety check
    Safety-->>Agent: allowed=true
    Agent->>Dispatcher: dispatch turn_left
    Dispatcher->>Controller: POST /execute action=turn_left
    Controller->>Robot: ROS2 /cmd_vel angular.z
    Robot-->>Controller: completed
    Controller-->>Dispatcher: ok=true, last_action=turn_left
    Dispatcher-->>Agent: tool result completed

    Agent->>LLM: messages + tool result
    LLM-->>Agent: finish(done)
    Agent-->>Pipeline: final_response=done
```

结果：

```text
turn_left completed action_ok=true
finish done
look_up 未生成、未验证、未派发、未执行
```

## 关键运行时状态

```mermaid
flowchart TD
    A[DecisionEnvelope] --> B[tool_calls]
    A --> C[validated_tool_calls]
    A --> D[tasks]
    A --> E[safety_result]
    A --> F[dispatch_results]
    A --> G[observations]
    A --> H[react_turns]
    A --> I[react_messages]
    A --> J[errors]

    B --> B1[qwen3-32b 原始/归一化工具调用]
    C --> C1[validator 接收或拒绝后的工具调用]
    D --> D1[可执行 TaskStep]
    E --> E1[allowed / rejected / emergency priority]
    F --> F1[dry_run 或实车执行结果]
    G --> G1[observation 或动作执行后 health]
    H --> H1[每轮 assistant_tool_call + tool_result]
    I --> I1[system/user/assistant/tool message 流]
    J --> J1[LLM/API/validator/dispatch 错误]
```

## 真实服务拓扑

```mermaid
flowchart TD
    A[本机 / WSL Claude Code] -->|SSH alias| B[raspberrypi]
    B -->|IP| C[192.168.1.46]
    C --> D[systemd action-move-controller.service]
    D --> E[docker exec -u ubuntu turbopi]
    E --> F[edge_ros_controller.py]
    F -->|listen| G[0.0.0.0:8765]
    A -->|HTTP /health, /execute| G
    F --> H[ROS2 in turbopi container]
    H --> I[/cmd_vel]
    H --> J[servo topic]
```

## 修复后的关键链路

```text
Claude Code / WSL
-> http://192.168.1.46:8765/execute
-> action-move-controller.service
-> docker exec -u ubuntu turbopi
-> edge_ros_controller.py --host 0.0.0.0 --port 8765
-> ROS2 publisher
-> TurboPi 实车
```

## 文件关联

```text
audio_recognition/react_agent.py           qwen3-32b ReAct agent、system prompt、tool_calls 调用
audio_recognition/pipeline.py              多 turn ReAct 主链路
audio_recognition/tool_schema.py           tools schema 生成
audio_recognition/tool_call_adapter.py     native tool_calls 归一化
audio_recognition/tool_validator.py        工具、技能、参数校验
audio_recognition/safety_guard.py          急停、否定片段、动作数量、置信度等安全约束
audio_recognition/dispatcher.py            dry_run / cloud_queue / local_first 派发
audio_recognition/observation_executor.py  camera/state/confirmation 观察类工具
audio_recognition/react_regression_check.py qwen3-32b dry-run 和实车验证脚本
action_move/edge_ros_controller.py         树莓派实车动作 HTTP 控制器
action_move/skill_catalog.json             实车动作技能目录
audio_recognition/skills/registry.yaml     ReAct 暴露给模型的技能白名单
```
