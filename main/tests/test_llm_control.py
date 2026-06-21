"""LLM 到 Live2D 控制协议测试。"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.integrations.llm_client import (
    DeepSeekLlmClient,
    LlmContext,
    normalize_action_plan_for_user_text,
    parse_live2d_control_plan,
)


class LlmControlPlanTest(unittest.TestCase):
    """验证 LLM JSON 输出会被白名单和范围裁剪。"""

    def test_parse_plan_keeps_allowed_expression_and_motion(self) -> None:
        content = """
        {
          "text": "主人，我会继续帮你测试。",
          "emotion": "happy",
          "expression": "heart",
          "motion": "scene1",
          "actions": [{"name": "gaming", "mode": "hold"}],
          "speech": {"voice": "female_zh", "rate": 1.1, "pitch": 1.2},
          "parameters": {"ParamAngleX": 8, "ParamMouthForm": 0.4}
        }
        """

        plan = parse_live2d_control_plan(content, expressions=["heart"], motions=["scene1"])

        self.assertEqual(plan.expression, "heart")
        self.assertEqual(plan.motion, "scene1")
        self.assertEqual(plan.actions[0].name, "gaming")
        self.assertEqual(plan.actions[0].mode, "hold")
        self.assertEqual(plan.speech.voice, "female_zh")
        self.assertEqual(plan.parameters["ParamAngleX"], 8)

    def test_parse_plan_rejects_unknown_controls(self) -> None:
        content = """
        {
          "text": "测试",
          "emotion": "happy",
          "expression": "not_allowed",
          "motion": "not_allowed",
          "speech": {"rate": 99, "pitch": 99},
          "parameters": {"DangerParam": 100, "ParamMouthOpenY": 9}
        }
        """

        plan = parse_live2d_control_plan(content, expressions=["blush"], motions=["captain"])

        self.assertEqual(plan.expression, "blush")
        self.assertEqual(plan.motion, "captain")
        self.assertNotIn("DangerParam", plan.parameters)
        self.assertEqual(plan.parameters["ParamMouthOpenY"], 1.0)
        self.assertLessEqual(plan.speech.rate, 1.25)
        self.assertLessEqual(plan.speech.pitch, 1.45)

    def test_parse_plan_sanitizes_action_controls(self) -> None:
        content = """
        {
          "text": "我会拿起麦克风唱歌。",
          "emotion": "happy",
          "expression": "heart",
          "motion": "scene1",
          "actions": [
            {"name": "microphone", "mode": "hold", "duration_ms": 999999},
            {"name": "gaming", "mode": "off"},
            {"name": "danger", "mode": "hold"}
          ],
          "speech": {"rate": 1.0, "pitch": 1.1},
          "parameters": {}
        }
        """

        plan = parse_live2d_control_plan(content, expressions=["heart"], motions=["scene1"])

        self.assertEqual([action.name for action in plan.actions], ["microphone", "gaming"])
        self.assertEqual(plan.actions[0].mode, "hold")
        self.assertEqual(plan.actions[0].duration_ms, 10000)
        self.assertEqual(plan.actions[1].mode, "off")

    def test_parse_plan_keeps_scheduled_actions(self) -> None:
        content = """
        {
          "text": "我先举起双手，五秒后拿起游戏机。",
          "emotion": "happy",
          "expression": "gaming",
          "motion": "scene1",
          "actions": [
            {"name": "right_hand_up", "mode": "hold"},
            {"name": "left_hand_up", "mode": "hold", "delay_ms": 0},
            {"name": "gaming", "mode": "hold", "delay_ms": 5000}
          ],
          "speech": {"rate": 1.0, "pitch": 1.1},
          "parameters": {}
        }
        """

        plan = parse_live2d_control_plan(content, expressions=["gaming"], motions=["scene1"])

        self.assertEqual([action.name for action in plan.actions], ["right_hand_up", "left_hand_up", "gaming"])
        self.assertEqual(plan.actions[0].delay_ms, 0)
        self.assertEqual(plan.actions[1].delay_ms, 0)
        self.assertEqual(plan.actions[2].delay_ms, 5000)

    def test_user_text_repairs_missing_scheduled_actions(self) -> None:
        content = """
        {
          "text": "好的，我举起双手，五秒后拿起游戏机。",
          "emotion": "happy",
          "expression": "gaming",
          "motion": "scene1",
          "actions": [],
          "speech": {"rate": 1.0, "pitch": 1.1},
          "parameters": {}
        }
        """

        plan = parse_live2d_control_plan(content, expressions=["gaming"], motions=["scene1"])
        plan = normalize_action_plan_for_user_text("举起双手，五秒后拿起游戏机", plan)

        self.assertEqual([action.name for action in plan.actions], ["right_hand_up", "left_hand_up", "gaming"])
        self.assertEqual(plan.actions[2].mode, "hold")
        self.assertEqual(plan.actions[2].delay_ms, 5000)

    def test_user_text_keeps_no_props_request(self) -> None:
        content = """
        {
          "text": "好的，我举起两只手，不拿东西。",
          "emotion": "happy",
          "expression": "heart",
          "motion": "scene1",
          "actions": [{"name": "gaming", "mode": "hold"}],
          "speech": {"rate": 1.0, "pitch": 1.1},
          "parameters": {}
        }
        """

        plan = parse_live2d_control_plan(content, expressions=["heart"], motions=["scene1"])
        plan = normalize_action_plan_for_user_text("只要你举起两只手，不要拿东西", plan)

        self.assertEqual([action.name for action in plan.actions], ["right_hand_up", "left_hand_up"])

    def test_client_falls_back_when_llm_returns_plain_text(self) -> None:
        client = FakeDeepSeekClient("主人，我现在可以继续陪你聊天，也会尽量保持动作稳定。")

        plan = client.generate_live2d_control(self._context(expressions=["question"]))

        self.assertEqual(plan.text, "主人，我现在可以继续陪你聊天，也会尽量保持动作稳定。")
        self.assertEqual(plan.emotion, "thinking")
        self.assertEqual(plan.expression, "question")
        self.assertEqual(plan.motion, "scene1")
        self.assertEqual(plan.actions, [])

    def test_client_fallback_extracts_text_from_broken_json(self) -> None:
        client = FakeDeepSeekClient('{"text": "主人，我收到了你的消息。", "emotion": "happy",')

        plan = client.generate_live2d_control(self._context(expressions=["question"]))

        self.assertEqual(plan.text, "主人，我收到了你的消息。")
        self.assertEqual(plan.parameters["ParamMouthForm"], 0.15)

    def test_client_repairs_non_standard_reply_before_fallback(self) -> None:
        client = FakeDeepSeekClient(
            [
                "主人，我想先直接回答你。",
                """
                {
                  "text": "主人，我已经把回复整理成标准控制计划啦。",
                  "emotion": "happy",
                  "expression": "heart",
                  "motion": "scene1",
                  "actions": [],
                  "speech": {"rate": 1.0, "pitch": 1.1},
                  "parameters": {"ParamMouthForm": 0.2}
                }
                """,
            ]
        )

        plan = client.generate_live2d_control(self._context(expressions=["heart"]))

        self.assertEqual(plan.text, "主人，我已经把回复整理成标准控制计划啦。")
        self.assertEqual(plan.emotion, "happy")
        self.assertEqual(client.call_count, 2)

    def test_chat_request_includes_time_memory_and_web_context(self) -> None:
        client = FakeDeepSeekClient("{}")

        request = client._build_request(
            LlmContext(
                user_prompt="今日江宁天气如何",
                expressions=["heart"],
                motions=["scene1"],
                memory_context=[{"time": "2026-05-17T17:28:00+08:00", "relative_time": "12 分钟前"}],
                runtime_context={"current_time": "2026-05-17T17:40:00+08:00", "internet_enabled": True},
                web_context={"enabled": True, "facts": [{"summary": "南京市江宁区当前多云，22°C"}], "errors": []},
            )
        )
        user_content = json.loads(request["messages"][1]["content"])

        self.assertEqual(user_content["当前运行上下文"]["current_time"], "2026-05-17T17:40:00+08:00")
        self.assertEqual(user_content["近期记忆"][0]["relative_time"], "12 分钟前")
        self.assertEqual(user_content["联网事实"]["facts"][0]["summary"], "南京市江宁区当前多云，22°C")
        self.assertIn("联网事实", request["messages"][0]["content"])

    @staticmethod
    def _context(expressions: list[str]) -> LlmContext:
        return LlmContext(user_prompt="你好", expressions=expressions, motions=["scene1"])


class FakeDeepSeekClient(DeepSeekLlmClient):
    """避免真实网络调用，只模拟 OpenAI 兼容响应。"""

    def __init__(self, content) -> None:  # type: ignore[no-untyped-def]
        super().__init__(api_key="test-key")
        self.contents = content if isinstance(content, list) else [content]
        self.call_count = 0

    def _post_chat_completion(self, payload):  # type: ignore[no-untyped-def]
        index = min(self.call_count, len(self.contents) - 1)
        self.call_count += 1
        return {"choices": [{"message": {"content": self.contents[index]}}]}


if __name__ == "__main__":
    unittest.main()
