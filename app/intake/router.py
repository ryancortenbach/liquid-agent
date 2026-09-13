from __future__ import annotations

from dataclasses import replace

from app.channels.base import InboundMessage
from app.channels.chat_ai import ChatIntent, ChatInterpreter
from app.channels.seller_router import SellerMessageRouter
from app.intake.flow import ListingFlow
from app.intake.item_guard import extract_separate_item_requests, separate_items_reply

DIRECT_TEXT = {
    "approve",
    "approved",
    "reject",
    "yes",
    "no",
    "go",
    "publish",
    "cancel",
    "status",
    "connect ebay",
    "connect email",
}
ACKNOWLEDGEMENT_WORDS = {
    "approve",
    "approved",
    "yes",
    "use it",
    "looks good",
    "go",
    "publish",
    "list it",
    "post it",
    "do it",
    "go ahead",
    "ok go",
    "yes go",
    "ship it",
}
INTENT_TEXT = {
    ChatIntent.STATUS: "status",
    ChatIntent.HELP: "help",
    ChatIntent.RESUME: "resume",
    ChatIntent.BACK: "back",
    ChatIntent.START_OVER: "start over",
    ChatIntent.CONNECT_EBAY: "connect ebay",
    ChatIntent.CONNECT_EMAIL: "connect email",
    ChatIntent.APPROVE: "approve",
    ChatIntent.REJECT: "reject",
    ChatIntent.PUBLISH: "go",
    ChatIntent.CANCEL: "cancel",
}


class PipelineRouter:
    """Photo and review messages go to the photo router; everything after goes to the flow."""

    def __init__(
        self,
        base: SellerMessageRouter,
        flow: ListingFlow,
        chat_interpreter: ChatInterpreter | None = None,
    ) -> None:
        self.base = base
        self.flow = flow
        self.chat_interpreter = chat_interpreter

    def accepts(self, message: InboundMessage) -> bool:
        return self.base.accepts(message)

    async def acknowledge(self, message: InboundMessage) -> bool:
        """Confirm seller actions before serialized or slow work begins."""
        if message.attachments or message.text.strip().lower() not in ACKNOWLEDGEMENT_WORDS:
            return False
        status = self.base.chat_context(message.handle).get("conversation_status")
        responses = {
            "awaiting_identity": "You bet. I'm cleaning up the photos now.",
            "awaiting_photo_review": "You bet. I'll use those photos.",
            "awaiting_details": "Got it. I'm on it.",
            "researching": "I'm on it. I'll send it as soon as it's ready.",
            "publishing": "I'm on it. I'll send the link as soon as it's ready.",
        }
        if status == "awaiting_confirmation":
            response = (
                "You bet. I'm building the mock listing now."
                if self.base.ebay_demo_mode
                else "You bet. I'm posting it now."
            )
        else:
            response = responses.get(status)
        if response is None:
            return False
        await self.base.adapter.send_text(
            message.chat_guid,
            response,
            f"{message.guid}:ack",
        )
        return True

    async def route(self, message: InboundMessage) -> None:
        if not self.accepts(message):
            return
        if await self.base.ensure_ebay_onboarding(message):
            return
        self.base.remember_turn(message, role="user", text=message.text)
        if not message.attachments and await self.base.handle_control(message):
            return
        separate_items = extract_separate_item_requests(message.text)
        if not message.attachments and separate_items:
            reply = separate_items_reply(separate_items)
            await self.base.adapter.send_text(
                message.chat_guid,
                reply,
                f"{message.guid}:separate-items",
            )
            self.base.remember_turn(
                message,
                role="assistant",
                text=reply,
                intent="separate_items",
            )
            return
        if (
            self.chat_interpreter is not None
            and not message.attachments
            and message.text.strip()
            and message.text.strip().lower() not in DIRECT_TEXT
        ):
            context = self.base.chat_context(message.handle)
            interpretation = await self.chat_interpreter.interpret(
                handle=message.handle,
                text=message.text,
                context=context,
            )
            if interpretation.intent == ChatIntent.REPLY and interpretation.reply.strip():
                reply = interpretation.reply.strip()
                await self.base.adapter.send_text(
                    message.chat_guid,
                    reply,
                    f"{message.guid}:ai-reply",
                )
                self.base.remember_turn(
                    message,
                    role="assistant",
                    text=reply,
                    intent=interpretation.intent.value,
                )
                return
            normalized = INTENT_TEXT.get(
                interpretation.intent,
                interpretation.normalized_text.strip() or message.text,
            )
            if (
                interpretation.intent == ChatIntent.APPROVE
                and context.get("conversation_status") == "awaiting_identity"
            ):
                normalized = "yes"
            if (
                interpretation.intent == ChatIntent.PUBLISH
                and context.get("conversation_status") != "awaiting_confirmation"
            ):
                normalized = interpretation.normalized_text.strip() or message.text
            message = replace(message, text=normalized)
        if not message.attachments and await self.base.handle_control(message):
            return
        if not message.attachments and message.text.strip().lower() in {
            "connect ebay",
            "connect email",
            "status",
        }:
            await self.base.route(message)
            return
        if not message.attachments and await self.flow.handle(message):
            return
        await self.base.route(message)
        # A photo review (approve or reject) hands the item to the details step.
        await self.flow.start_details(
            handle=message.handle, chat_guid=message.chat_guid, key=message.guid
        )
