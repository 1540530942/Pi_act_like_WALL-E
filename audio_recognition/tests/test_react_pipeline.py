from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import Mock

from audio_recognition.dispatcher import dispatch_envelope
from audio_recognition.envelope import DecisionEnvelope, ToolCall
from audio_recognition.envelope_store import load_envelope, save_envelope
from audio_recognition.pipeline import decide_transcript, route_transcript
from audio_recognition.replay import replay_envelope
from audio_recognition.safety_guard import run_safety_guard
from audio_recognition.tool_validator import validate_tool_calls


BASE_DIR = Path(__file__).resolve().parents[1]
CATALOG_PATH = str(Path(__file__).with_name("skill_catalog.fixture.json").resolve())
ROUTER_CONFIG = {"skill_catalog": CATALOG_PATH}


class ReactPipelineTest(unittest.TestCase):
    def test_simple_command_generates_envelope_tool_task_and_dry_run(self) -> None:
        envelope = decide_transcript(
            base_dir=BASE_DIR,
            text="前进",
            router_config=ROUTER_CONFIG,
            cloud_config={},
            dispatch_mode="dry_run",
            source="unit",
        )
        self.assertEqual(envelope.tool_calls[0].tool, "dispatch_action")
        self.assertEqual(envelope.tasks[0].skill_id, "move_forward")
        self.assertEqual(envelope.dispatch_results[0]["status"], "dry_run")
        self.assertTrue(envelope.safety_result["allowed"])

    def test_sequence_command_generates_ordered_tasks(self) -> None:
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

    def test_emergency_stop_is_highest_priority(self) -> None:
        envelope = decide_transcript(
            base_dir=BASE_DIR,
            text="停止",
            router_config=ROUTER_CONFIG,
            cloud_config={},
            dispatch_mode="dry_run",
            source="unit",
        )
        self.assertEqual(envelope.tasks[0].skill_id, "emergency_stop")
        self.assertEqual(envelope.safety_result["priority"], "highest")

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
            replay = replay_envelope(
                data_dir=data_dir,
                envelope_id=envelope.envelope_id,
                base_dir=BASE_DIR,
                router_config=ROUTER_CONFIG,
                replay_from="text",
            )
            self.assertFalse(replay["diff"]["transcript_changed"])
            self.assertEqual(replay["new_envelope"]["dispatch_results"][0]["status"], "dry_run")

    def test_llm_react_agent_generates_sequence_without_rule_fallback(self) -> None:
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "text": (
                '{"reasoning_summary":"按顺序执行，忽略被否定的前进",'
                '"tool_calls":['
                '{"tool":"dispatch_action","args":{"skill_id":"move_forward","order":1,"duration_ms":800,"text":"先往前走"}},'
                '{"tool":"dispatch_action","args":{"skill_id":"move_backward","order":2,"duration_ms":800,"text":"再往后走"}},'
                '{"tool":"dispatch_action","args":{"skill_id":"look_up","order":3,"duration_ms":600,"text":"抬头看"}},'
                '{"tool":"dispatch_action","args":{"skill_id":"look_down","order":4,"duration_ms":600,"text":"低头看"}}'
                '],"final":"ok"}'
            )
        }
        config = {
            **ROUTER_CONFIG,
            "react_agent": {"mode": "llm", "llm": {"endpoint": "http://llm.local", "model": "qwen3.5-9b"}},
        }
        with patch("audio_recognition.react_agent.requests.post", return_value=response) as post:
            envelope = decide_transcript(
                base_dir=BASE_DIR,
                text="先往前走，再往后走，抬头看，不要往前走了，低头看",
                router_config=config,
                cloud_config={},
                dispatch_mode="dry_run",
                source="unit",
            )
        post.assert_called_once()
        self.assertEqual([task.skill_id for task in envelope.tasks], ["move_forward", "move_backward", "look_up", "look_down"])
        self.assertTrue(envelope.safety_result["allowed"])


if __name__ == "__main__":
    unittest.main()
