# 2026-05-24 两条目标指令 ReAct 可观测上下文记录

## 说明

本文记录两条实车验证指令的完整可观测上下文：

- system prompt
- user message
- qwen3-32b 返回的 native/tool_call 归一化结果
- validator/safety 结果
- tool result / dispatch result
- final response

不包含模型隐藏思维链。工程中也明确要求：

```text
reasoning_summary: short Chinese summary, no hidden chain-of-thought
No Thinking Process
```

因此这里记录的是可审计的 ReAct 消息流和执行轨迹，而不是模型私有推理 token。

## 运行配置

```json
{
  "base_dir": "C:/Users/Administrator/Desktop/Workspace/Project_Codex/wangyutang_platform/audio_recognition",
  "skill_registry": "skills/registry.yaml",
  "skill_catalog": "../action_move/skill_catalog.json",
  "react_agent": {
    "mode": "llm",
    "max_steps": 8,
    "prompt_path": "prompts/walle_system_prompt.md",
    "llm": {
      "endpoint": "https://www.wangyutang.cn/common/api/llm/qwen3-32b/chat/completions",
      "model": "qwen3-32b",
      "timeout_seconds": 140,
      "verify_ssl": false,
      "retries": 2
    }
  },
  "cloud_config": {
    "local_action_server": "http://192.168.1.46:8765",
    "local_settings": {
      "unit_distance_cm": 1,
      "sensitivity": 2.0,
      "stop_publish_times": 5,
      "capture_after_move": false,
      "capture_after_servo": false
    }
  },
  "dispatch_mode": "local_first"
}
```

## System prompt

```text
You are WALL-E, the robot's embodied control brain.

Speak and act like WALL-E: brief, curious, careful, and action-oriented. Prefer short sounds or short Chinese responses over long explanations.

Rules:
- Use native tool_calls whenever available.
- One ReAct turn must produce at most one tool_call.
- Execute only positive requested actions. Negated fragments such as 不要, 别, 不许, 不用 must not create that action.
- Emergency stop phrases such as 急停, 停止, 停下, 别动, 不要动 must use emergency_stop immediately.
- If an instruction depends on current camera or robot state, observe first, then decide in the next turn.
- Do not guess safety-critical state. If required evidence is missing, use camera_snapshot, get_robot_state, ask_confirmation, or finish safely.
- Keep tool_call.args.text to the minimal source fragment for the current step.
- Keep finish.message short. Do not claim to be an AI model or explain implementation details.

Runtime protocol:
- Prefer native OpenAI-style tool_calls. If native tool calling is unavailable, output only compact JSON.
- protocol_version=react_v1_single_tool. No Thinking Process. One ReAct turn equals one tool_call.
- After a completed/dry_run tool result, choose the next unfinished positive command; output finish when done.
- Negated fragments such as 不要/别/不许/不用 do not create that action and do not cancel previous completed actions.
- 停止/急停/别动/不要动 -> emergency_stop.
- 往前走=move_forward; 往后走=move_backward; 抬头看=look_up; 低头看=look_down.
- tool_call.args.text must be the minimal source fragment for only this step.
- Observation tools must be used before action when current state or camera evidence is required.
Allowed: {"dispatch_action": ["look_down", "look_left", "look_right", "look_up", "move_backward", "move_forward", "move_left", "move_right", "reset_pose", "turn_left", "turn_right"], "dispatch_face": ["face_angry", "face_blink", "face_happy", "face_joy", "face_mouth_open", "face_neutral", "face_reset", "face_sad", "face_speak"], "camera_snapshot": ["camera_snapshot"], "get_robot_state": ["get_robot_state"], "ask_confirmation": ["ask_confirmation"], "emergency_stop": ["emergency_stop"], "finish": ["finish"]}.
Schema: {"protocol_version": "react_v1_single_tool", "reasoning_summary": "short Chinese summary, no hidden chain-of-thought", "tool_call": {"tool": "dispatch_action | dispatch_face | emergency_stop | finish", "args": {"skill_id": "one allowed skill id, omitted for finish", "duration_ms": 800, "wait_until": "completed", "confidence": 0.9, "text": "exact minimal source fragment for this one step"}}, "final": "only for finish"}.
```

## 可用 tools 摘要

### dispatch_action

允许的动作技能：

```text
look_down, look_left, look_right, look_up,
move_backward, move_forward, move_left, move_right,
reset_pose, turn_left, turn_right
```

核心参数：

```json
{
  "skill_id": "enum",
  "duration_ms": "integer",
  "order": "integer",
  "wait_until": "accepted|completed",
  "confidence": "0..1",
  "text": "minimal source fragment"
}
```

### finish

核心参数：

```json
{
  "message": "string",
  "final": "string"
}
```

## 预检：action server health

真实动作前，action controller 状态：

```json
{
  "status": "ok",
  "service": "TurboPi Action Move Edge ROS Controller",
  "last_action": "emergency_stop",
  "last_executed_at": 1779558226.9989865
}
```

## 预检：emergency_stop dry-run

用户输入：

```text
不要动、向右转一下
```

preflight 直接绕过 LLM，生成 emergency_stop：

```json
{
  "tool": "emergency_stop",
  "args": {
    "skill_id": "emergency_stop",
    "order": 0,
    "wait_until": "accepted",
    "confidence": 1.0,
    "text": "不要动、向右转一下"
  }
}
```

validator/safety：

```json
{
  "allowed": true,
  "reason": "emergency_stop_detected",
  "checks": [],
  "priority": "highest"
}
```

## 预检：真实 emergency_stop

真实动作前发送：

```json
{
  "action": "emergency_stop",
  "settings": {
    "stop_publish_times": 5
  }
}
```

执行结果：

```json
{
  "ok": true,
  "skill_id": "emergency_stop",
  "name_zh": "急停",
  "elapsed_seconds": 0.092,
  "output": "[INFO] 急停 -> emergency_stop\n[INFO] transport=persistent_ros_controller\n[INFO] unit_distance_cm=5.0 turn_angle_deg=5.0 sensitivity=1.0\n[INFO] elapsed_seconds=0.092"
}
```

---

# 指令一：先前进再向上看

## User message

```json
{
  "role": "user",
  "content": "/no_think\n用户原始指令: 先前进再向上看"
}
```

## Turn 1

### qwen3-32b assistant tool_call

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_*",
      "type": "function",
      "function": {
        "name": "dispatch_action",
        "arguments": {
          "skill_id": "move_forward",
          "duration_ms": 800,
          "wait_until": "completed",
          "confidence": 0.9,
          "text": "前进",
          "order": 1
        }
      }
    }
  ]
}
```

### 内部 ToolCall

```json
{
  "tool": "dispatch_action",
  "args": {
    "skill_id": "move_forward",
    "duration_ms": 800,
    "wait_until": "completed",
    "confidence": 0.9,
    "text": "前进",
    "order": 1
  },
  "status": "pending",
  "error": ""
}
```

### validator 输出 TaskStep

```json
{
  "order": 1,
  "skill_id": "move_forward",
  "route": "action",
  "duration_ms": 800,
  "wait_until": "completed",
  "status": "pending"
}
```

### safety_guard

```json
{
  "allowed": true,
  "reason": "",
  "checks": []
}
```

### dispatcher local_first 请求

```json
{
  "url": "http://192.168.1.46:8765/execute",
  "payload": {
    "action": "move_forward",
    "settings": {
      "unit_distance_cm": 1.0,
      "sensitivity": 2.0,
      "stop_publish_times": 5,
      "requested_duration_ms": 800
    }
  }
}
```

### 实车执行结果

```json
{
  "skill_id": "move_forward",
  "status": "completed",
  "error": "",
  "action_task": {
    "ok": true,
    "skill_id": "move_forward",
    "name_zh": "向前走",
    "elapsed_seconds": 0.294,
    "output": "[INFO] 向前走 -> move_forward\n[INFO] transport=persistent_ros_controller\n[INFO] unit_distance_cm=1.0 turn_angle_deg=5.0 sensitivity=2.0\n[INFO] duration_ms=180\n[INFO] elapsed_seconds=0.294",
    "health": {
      "status": "ok",
      "service": "TurboPi Action Move Edge ROS Controller",
      "last_action": "move_forward",
      "last_executed_at": 1779558322.9785967
    }
  }
}
```

### tool result message 回写给 LLM

```json
{
  "role": "tool",
  "tool_call_id": "call_*",
  "name": "dispatch_action",
  "content": {
    "task_id": "task_*",
    "skill_id": "move_forward",
    "status": "completed",
    "result": {
      "action_task": {
        "ok": true,
        "skill_id": "move_forward",
        "name_zh": "向前走",
        "elapsed_seconds": 0.294,
        "health": {
          "status": "ok",
          "last_action": "move_forward"
        }
      },
      "face_task": null,
      "action_error": "",
      "face_error": ""
    },
    "error": ""
  }
}
```

## Turn 2

### qwen3-32b assistant tool_call

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_*",
      "type": "function",
      "function": {
        "name": "dispatch_action",
        "arguments": {
          "skill_id": "look_up",
          "duration_ms": 800,
          "wait_until": "completed",
          "confidence": 0.9,
          "text": "向上看",
          "order": 2
        }
      }
    }
  ]
}
```

### 内部 ToolCall

```json
{
  "tool": "dispatch_action",
  "args": {
    "skill_id": "look_up",
    "duration_ms": 800,
    "wait_until": "completed",
    "confidence": 0.9,
    "text": "向上看",
    "order": 2
  },
  "status": "pending",
  "error": ""
}
```

### validator 输出 TaskStep

```json
{
  "order": 2,
  "skill_id": "look_up",
  "route": "action",
  "duration_ms": 800,
  "wait_until": "completed",
  "status": "pending"
}
```

### safety_guard

```json
{
  "allowed": true,
  "reason": "",
  "checks": []
}
```

### dispatcher local_first 请求

```json
{
  "url": "http://192.168.1.46:8765/execute",
  "payload": {
    "action": "look_up",
    "settings": {
      "unit_distance_cm": 1.0,
      "sensitivity": 2.0,
      "stop_publish_times": 5,
      "requested_duration_ms": 800
    }
  }
}
```

### 实车执行结果

```json
{
  "skill_id": "look_up",
  "status": "completed",
  "error": "",
  "action_task": {
    "ok": true,
    "skill_id": "look_up",
    "name_zh": "向上看",
    "elapsed_seconds": 0.352,
    "output": "[INFO] 向上看 -> look_up\n[INFO] transport=persistent_ros_controller\n[INFO] unit_distance_cm=1.0 turn_angle_deg=5.0 sensitivity=2.0\n[INFO] elapsed_seconds=0.352",
    "health": {
      "status": "ok",
      "service": "TurboPi Action Move Edge ROS Controller",
      "last_action": "look_up",
      "last_executed_at": 1779558328.6085808
    }
  }
}
```

### tool result message 回写给 LLM

```json
{
  "role": "tool",
  "tool_call_id": "call_*",
  "name": "dispatch_action",
  "content": {
    "task_id": "task_*",
    "skill_id": "look_up",
    "status": "completed",
    "result": {
      "action_task": {
        "ok": true,
        "skill_id": "look_up",
        "name_zh": "向上看",
        "elapsed_seconds": 0.352,
        "health": {
          "status": "ok",
          "last_action": "look_up"
        }
      },
      "face_task": null,
      "action_error": "",
      "face_error": ""
    },
    "error": ""
  }
}
```

## Turn 3

### qwen3-32b finish

```json
{
  "tool": "finish",
  "args": {
    "final": "done",
    "order": 3,
    "wait_until": "completed",
    "confidence": 0.9
  }
}
```

### final_response

```text
done
```

## 指令一最终 envelope 摘要

```json
{
  "transcript": "先前进再向上看",
  "tool_calls": [
    {"tool": "dispatch_action", "skill_id": "move_forward", "text": "前进"},
    {"tool": "dispatch_action", "skill_id": "look_up", "text": "向上看"},
    {"tool": "finish"}
  ],
  "tasks": [
    {"order": 1, "skill_id": "move_forward", "status": "completed"},
    {"order": 2, "skill_id": "look_up", "status": "completed"}
  ],
  "dispatch_results": [
    {"skill_id": "move_forward", "status": "completed", "action_ok": true, "action_elapsed": 0.294},
    {"skill_id": "look_up", "status": "completed", "action_ok": true, "action_elapsed": 0.352}
  ],
  "safety_result": {"allowed": true, "reason": "", "checks": []},
  "final_response": "done",
  "errors": []
}
```

---

# 指令二：左转，不要往上看

## User message

```json
{
  "role": "user",
  "content": "/no_think\n用户原始指令: 左转，不要往上看"
}
```

## Turn 1

### qwen3-32b assistant tool_call

```json
{
  "role": "assistant",
  "content": null,
  "tool_calls": [
    {
      "id": "call_*",
      "type": "function",
      "function": {
        "name": "dispatch_action",
        "arguments": {
          "skill_id": "turn_left",
          "duration_ms": 800,
          "wait_until": "completed",
          "confidence": 0.9,
          "text": "左转",
          "order": 1
        }
      }
    }
  ]
}
```

### 内部 ToolCall

```json
{
  "tool": "dispatch_action",
  "args": {
    "skill_id": "turn_left",
    "duration_ms": 800,
    "wait_until": "completed",
    "confidence": 0.9,
    "text": "左转",
    "order": 1
  },
  "status": "pending",
  "error": ""
}
```

关键审计点：原始输入包含 `不要往上看`，但本轮 `args.text` 只包含最小正向片段 `左转`，没有生成 `look_up`。

### validator 输出 TaskStep

```json
{
  "order": 1,
  "skill_id": "turn_left",
  "route": "action",
  "duration_ms": 800,
  "wait_until": "completed",
  "status": "pending"
}
```

### safety_guard

```json
{
  "allowed": true,
  "reason": "",
  "checks": []
}
```

说明：`safety_guard` 的否定词检查基于本轮 `tool_call.args.text`。由于 qwen3-32b 正确只抽取了正向片段 `左转`，所以不会误杀本轮动作；被否定的 `不要往上看` 没有形成 tool_call。

### dispatcher local_first 请求

```json
{
  "url": "http://192.168.1.46:8765/execute",
  "payload": {
    "action": "turn_left",
    "settings": {
      "unit_distance_cm": 1.0,
      "sensitivity": 2.0,
      "stop_publish_times": 5,
      "requested_duration_ms": 800
    }
  }
}
```

### 实车执行结果

```json
{
  "skill_id": "turn_left",
  "status": "completed",
  "error": "",
  "action_task": {
    "ok": true,
    "skill_id": "turn_left",
    "name_zh": "向左转",
    "elapsed_seconds": 0.345,
    "output": "[INFO] 向左转 -> turn_left\n[INFO] transport=persistent_ros_controller\n[INFO] unit_distance_cm=1.0 turn_angle_deg=5.0 sensitivity=2.0\n[INFO] duration_ms=225\n[INFO] elapsed_seconds=0.345",
    "health": {
      "status": "ok",
      "service": "TurboPi Action Move Edge ROS Controller",
      "last_action": "turn_left",
      "last_executed_at": 1779558334.6595297
    }
  }
}
```

### tool result message 回写给 LLM

```json
{
  "role": "tool",
  "tool_call_id": "call_*",
  "name": "dispatch_action",
  "content": {
    "task_id": "task_*",
    "skill_id": "turn_left",
    "status": "completed",
    "result": {
      "action_task": {
        "ok": true,
        "skill_id": "turn_left",
        "name_zh": "向左转",
        "elapsed_seconds": 0.345,
        "health": {
          "status": "ok",
          "last_action": "turn_left"
        }
      },
      "face_task": null,
      "action_error": "",
      "face_error": ""
    },
    "error": ""
  }
}
```

## Turn 2

### qwen3-32b finish

```json
{
  "tool": "finish",
  "args": {
    "final": "done",
    "order": 2,
    "wait_until": "completed",
    "confidence": 0.9
  }
}
```

### final_response

```text
done
```

## 指令二最终 envelope 摘要

```json
{
  "transcript": "左转，不要往上看",
  "tool_calls": [
    {"tool": "dispatch_action", "skill_id": "turn_left", "text": "左转"},
    {"tool": "finish"}
  ],
  "tasks": [
    {"order": 1, "skill_id": "turn_left", "status": "completed"}
  ],
  "dispatch_results": [
    {"skill_id": "turn_left", "status": "completed", "action_ok": true, "action_elapsed": 0.345}
  ],
  "safety_result": {"allowed": true, "reason": "", "checks": []},
  "final_response": "done",
  "errors": []
}
```

## 否定片段处理审计

原始输入：

```text
左转，不要往上看
```

可执行正向片段：

```text
左转
```

否定片段：

```text
不要往上看
```

最终 tool_calls：

```text
turn_left -> finish
```

未出现：

```text
look_up
```

因此结论是：模型层遵守了 prompt 中“否定片段不生成动作”的约束；运行时 validator/safety/dispatcher 只收到 `turn_left`，实车也只执行了 `turn_left`。

---

# 结束 emergency_stop

真实动作验证结束后发送：

```json
{
  "action": "emergency_stop",
  "settings": {
    "stop_publish_times": 5
  }
}
```

执行结果：

```json
{
  "ok": true,
  "skill_id": "emergency_stop",
  "name_zh": "急停",
  "elapsed_seconds": 0.092,
  "output": "[INFO] 急停 -> emergency_stop\n[INFO] transport=persistent_ros_controller\n[INFO] unit_distance_cm=5.0 turn_angle_deg=5.0 sensitivity=1.0\n[INFO] elapsed_seconds=0.092"
}
```

最终 health：

```json
{
  "status": "ok",
  "service": "TurboPi Action Move Edge ROS Controller",
  "last_action": "emergency_stop",
  "last_executed_at": 1779558336.261232
}
```

## 总结

两条指令的可观测 ReAct 上下文均符合预期：

```text
先前进再向上看
-> move_forward
-> tool result completed
-> look_up
-> tool result completed
-> finish
```

```text
左转，不要往上看
-> turn_left
-> tool result completed
-> finish
```

实车执行结果：

```text
move_forward completed action_ok=true
look_up completed action_ok=true
turn_left completed action_ok=true
post_real_emergency_stop completed action_ok=true
```
