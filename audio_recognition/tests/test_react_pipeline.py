from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from audio_recognition.dispatcher import dispatch_envelope
from audio_recognition.envelope import DecisionEnvelope, ToolCall
from audio_recognition.envelope_store import load_envelope, save_envelope
from audio_recognition.pipeline import decide_transcript, route_transcript
from audio_recognition.replay import replay_envelope
from audio_recognition.tool_validator import validate_tool_calls


BASE_DIR = Path(__file__).resolve().parents[1]
CATALOG_PATH = str(Path(__file__).with_name("skill_catalog.fixture.json").resolve())
ROUTER_CONFIG = {
    "skill_catalog": CATALOG_PATH,
    "react_agent": {"mode": "llm", "llm": {"endpoint": "http://llm.local", "model": "qwen3.5-9b"}},
}


def llm_response(payload: dict) -> Mock:
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"text": json.dumps(payload, ensure_ascii=False)}
    return response


def action_response(skill_id: str, *, text: str = "", order: int = 1, duration_ms: int = 800) -> Mock:
    return llm_response(
        {
            "protocol_version": "react_v1_single_tool",
            "reasoning_summary": f"dispatch {skill_id}",
            "tool_call": {
                "tool": "dispatch_action",
                "args": {
                    "skill_id": skill_id,
                    "order": order,
                    "duration_ms": duration_ms,
                    "wait_until": "completed",
                    "confidence": 0.9,
                    "text": text or skill_id,
                },
            },
        }
    )


def observation_response(tool: str, *, order: int = 1) -> Mock:
    return llm_response(
        {
            "protocol_version": "react_v1_single_tool",
            "tool_call": {"tool": tool, "args": {"order": order}},
        }
    )


def multi_tool_response() -> Mock:
    return llm_response(
        {
            "protocol_version": "react_v1_single_tool",
            "tool_calls": [
                {"tool": "dispatch_action", "args": {"skill_id": "move_forward"}},
                {"tool": "dispatch_action", "args": {"skill_id": "turn_right"}},
            ],
        }
    )


def finish_response(order: int = 2) -> Mock:
    return llm_response(
        {
            "protocol_version": "react_v1_single_tool",
            "type": "finish",
            "final": "done",
            "tool_call": {"tool": "finish", "args": {"order": order}},
        }
    )


class ReactPipelineTest(unittest.TestCase):
    def test_simple_command_generates_envelope_tool_task_and_dry_run(self) -> None:
        with patch("audio_recognition.react_agent.requests.post", side_effect=[action_response("move_forward", text="前进"), finish_response()]):
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="前进",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        self.assertEqual(envelope.protocol_version, "react_v1_single_tool")
        self.assertEqual(envelope.tool_calls[0].tool, "dispatch_action")
        self.assertEqual(envelope.tasks[0].skill_id, "move_forward")
        self.assertEqual(envelope.dispatch_results[0]["status"], "dry_run")
        self.assertTrue(envelope.safety_result["allowed"])

    def test_sequence_command_generates_ordered_tasks(self) -> None:
        with patch(
            "audio_recognition.react_agent.requests.post",
            side_effect=[
                action_response("move_forward", text="前进", order=1),
                action_response("turn_right", text="然后右转", order=2),
                finish_response(3),
            ],
        ):
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="前进，然后右转",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        self.assertEqual([task.skill_id for task in envelope.tasks], ["move_forward", "turn_right"])
        self.assertEqual([task.order for task in envelope.tasks], [1, 2])

    def test_negative_instruction_is_rejected_by_safety(self) -> None:
        with patch("audio_recognition.react_agent.requests.post", side_effect=[action_response("move_forward", text="不要前进")]):
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="不要前进",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        self.assertEqual(envelope.safety_result["reason"], "negative_instruction_detected")
        self.assertEqual(envelope.tasks[0].status, "rejected")

    def test_emergency_stop_preflight_bypasses_llm(self) -> None:
        with patch("audio_recognition.react_agent.requests.post") as post:
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="不要动",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        post.assert_not_called()
        self.assertEqual(envelope.tasks[0].skill_id, "emergency_stop")
        self.assertEqual(envelope.safety_result["priority"], "highest")
        self.assertTrue(envelope.react_turns[0]["preflight"])

    def test_validator_rejects_unknown_tool_and_clips_duration(self) -> None:
        envelope = DecisionEnvelope(
            transcript="test",
            tool_calls=[
                ToolCall(tool="dispatch_action", args={"skill_id": "move_forward", "duration_ms": 99999}),
                ToolCall(tool="dispatch_action", args={"skill_id": "jump"}),
            ],
        )
        envelope = validate_tool_calls(envelope)
        self.assertEqual(envelope.validated_tool_calls[0].status, "validated")
        self.assertEqual(envelope.validated_tool_calls[0].args["duration_ms"], 1000)
        self.assertEqual(envelope.validated_tool_calls[1].status, "rejected")

    def test_cloud_dispatch_uses_executor_once(self) -> None:
        with patch("audio_recognition.react_agent.requests.post", side_effect=[action_response("move_forward", text="前进"), finish_response()]):
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="前进",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        envelope.dispatch_results = []
        with patch("audio_recognition.executors.create_action_task", return_value={"task": {"id": "task-1"}}) as create_action_task:
            envelope = dispatch_envelope(envelope, cloud_config={"action_enabled": True, "action_server": "http://action.local"}, source="unit", dispatch_mode="cloud_queue")
        create_action_task.assert_called_once()
        self.assertEqual(envelope.dispatch_results[0]["status"], "completed")

    def test_local_first_dispatch_posts_to_edge_controller(self) -> None:
        with patch("audio_recognition.react_agent.requests.post", side_effect=[action_response("move_forward", text="前进"), finish_response()]):
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="前进",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        envelope.dispatch_results = []
        with patch("audio_recognition.dispatcher._post_json", return_value={"ok": True, "skill_id": "move_forward"}) as post_json:
            envelope = dispatch_envelope(
                envelope,
                cloud_config={"local_action_server": "http://127.0.0.1:8765", "local_settings": {"unit_distance_cm": 1}},
                source="unit",
                dispatch_mode="local_first",
            )
        post_json.assert_called_once()
        self.assertTrue(post_json.call_args.args[0].endswith("/execute"))
        self.assertEqual(envelope.dispatch_results[0]["status"], "completed")

    def test_route_transcript_keeps_legacy_shape_with_envelope(self) -> None:
        with patch("audio_recognition.react_agent.requests.post", side_effect=[action_response("move_forward", text="前进"), finish_response()]):
            routed = route_transcript(
                base_dir=BASE_DIR,
                text="前进",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                route_action=False,
                source="unit",
            )
        self.assertEqual(routed["skill_id"], "move_forward")
        self.assertEqual(routed["plan"]["route"], "action")
        self.assertEqual(routed["envelope"]["tasks"][0]["skill_id"], "move_forward")

    def test_envelope_store_and_replay_from_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            with patch("audio_recognition.react_agent.requests.post", side_effect=[action_response("move_forward", text="前进"), finish_response()]):
                envelope = decide_transcript(
                    base_dir=BASE_DIR,
                    text="前进",
                    router_config=ROUTER_CONFIG,
                    cloud_config={},
                    dispatch_mode="dry_run",
                    source="unit",
                )
            save_envelope(data_dir, envelope)
            self.assertEqual(load_envelope(data_dir, envelope.envelope_id).transcript, "前进")
            with patch("audio_recognition.react_agent.requests.post", side_effect=[action_response("move_forward", text="前进"), finish_response()]):
                replay = replay_envelope(
                    data_dir=data_dir,
                    envelope_id=envelope.envelope_id,
                    base_dir=BASE_DIR,
                    router_config=ROUTER_CONFIG,
                    replay_from="text",
                )
            self.assertFalse(replay["diff"]["transcript_changed"])
            self.assertEqual(replay["new_envelope"]["dispatch_results"][0]["status"], "dry_run")

    def test_observation_tool_writes_observation_and_continues(self) -> None:
        with patch(
            "audio_recognition.react_agent.requests.post",
            side_effect=[observation_response("get_robot_state"), finish_response(2)],
        ), patch("audio_recognition.observation_executor._get_json", return_value={"status": "ok", "battery_pct": 82}):
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="电量够吗",
                router_config=ROUTER_CONFIG,
                cloud_config={"local_action_server": "http://127.0.0.1:8765"},
                dispatch_mode="dry_run",
                source="unit",
            )
        self.assertEqual(envelope.observations[0]["tool"], "get_robot_state")
        self.assertEqual(envelope.observations[0]["data"]["battery_pct"], 82)
        self.assertEqual(envelope.final_response, "done")

    def test_observation_failure_is_recorded_and_loop_can_finish(self) -> None:
        with patch(
            "audio_recognition.react_agent.requests.post",
            side_effect=[observation_response("camera_snapshot"), finish_response(2)],
        ):
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="\u770b\u4e00\u4e0b\u524d\u9762",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        self.assertEqual(envelope.observations[0]["tool"], "camera_snapshot")
        self.assertEqual(envelope.observations[0]["status"], "failed")
        self.assertIn("camera_server is required", envelope.observations[0]["error"])
        self.assertEqual(envelope.final_response, "done")

    def test_ask_confirmation_records_pending_observation(self) -> None:
        response = llm_response(
            {
                "protocol_version": "react_v1_single_tool",
                "tool_call": {
                    "tool": "ask_confirmation",
                    "args": {"question": "\u8981\u524d\u8fdb\u5417\uff1f", "timeout_s": 10},
                },
            }
        )
        with patch("audio_recognition.react_agent.requests.post", side_effect=[response, finish_response(2)]):
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="\u597d\u50cf\u662f\u524d\u8fdb",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        self.assertEqual(envelope.observations[0]["tool"], "ask_confirmation")
        self.assertEqual(envelope.observations[0]["status"], "pending")
        self.assertEqual(envelope.observations[0]["data"]["question"], "\u8981\u524d\u8fdb\u5417\uff1f")

    def test_multiple_tool_calls_are_rejected_by_single_tool_protocol(self) -> None:
        with patch("audio_recognition.react_agent.requests.post", return_value=multi_tool_response()):
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="\u524d\u8fdb\u7136\u540e\u53f3\u8f6c",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        self.assertEqual(envelope.tasks, [])
        self.assertEqual(envelope.dispatch_results, [])
        self.assertIn("exactly one tool_call", envelope.errors[0]["message"])

    def test_llm_react_agent_generates_sequence_without_rule_fallback(self) -> None:
        with patch(
            "audio_recognition.react_agent.requests.post",
            side_effect=[
                action_response("move_forward", text="先往前走", order=1),
                action_response("move_backward", text="再往后走", order=2),
                action_response("look_up", text="抬头看", order=3),
                action_response("look_down", text="低头看", order=4),
                finish_response(5),
            ],
        ) as post:
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="先往前走，再往后走，抬头看，不要往前走了，低头看",
                router_config=ROUTER_CONFIG,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        self.assertEqual(post.call_count, 5)
        self.assertEqual([task.skill_id for task in envelope.tasks], ["move_forward", "move_backward", "look_up", "look_down"])
        self.assertTrue(envelope.safety_result["allowed"])


if __name__ == "__main__":
    unittest.main()
