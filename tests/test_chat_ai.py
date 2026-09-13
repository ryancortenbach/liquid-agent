from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.channels.chat_ai import ChatIntent, ChatInterpretation, OpenAIChatInterpreter


def test_openai_chat_interpreter_uses_structured_output_without_remote_storage() -> None:
    calls: list[dict] = []

    class FakeResponses:
        async def parse(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                output_parsed=ChatInterpretation(
                    intent=ChatIntent.STATUS,
                    normalized_text="status",
                )
            )

    client = SimpleNamespace(responses=FakeResponses())
    interpreter = OpenAIChatInterpreter("unused", client=client)
    result = asyncio.run(
        interpreter.interpret(
            handle="+14155550123",
            text="What is happening with that thing?",
            context={"conversation_status": "researching", "recent_messages": []},
        )
    )

    assert result.intent == ChatIntent.STATUS
    assert calls[0]["model"] == "gpt-5.4-mini"
    assert calls[0]["store"] is False
    assert calls[0]["text_format"] is ChatInterpretation
    assert calls[0]["safety_identifier"] != "+14155550123"


def test_openai_chat_failure_preserves_the_original_message() -> None:
    class FailingResponses:
        async def parse(self, **_kwargs):
            raise RuntimeError("temporary failure")

    interpreter = OpenAIChatInterpreter(
        "unused",
        client=SimpleNamespace(responses=FailingResponses()),
    )
    result = asyncio.run(
        interpreter.interpret(
            handle="seller",
            text="floor should be 200",
            context={"conversation_status": "awaiting_confirmation"},
        )
    )

    assert result.intent == ChatIntent.PASS_THROUGH
    assert result.normalized_text == "floor should be 200"
