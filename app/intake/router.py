from __future__ import annotations

from app.channels.base import InboundMessage
from app.channels.seller_router import SellerMessageRouter
from app.intake.flow import ListingFlow


class PipelineRouter:
    """Photo and review messages go to the photo router; everything after goes to the flow."""

    def __init__(self, base: SellerMessageRouter, flow: ListingFlow) -> None:
        self.base = base
        self.flow = flow

    def accepts(self, message: InboundMessage) -> bool:
        return self.base.accepts(message)

    async def route(self, message: InboundMessage) -> None:
        if not self.accepts(message):
            return
        if not message.attachments and message.text.strip().lower() == "connect ebay":
            await self.base.route(message)
            return
        if not message.attachments and await self.flow.handle(message):
            return
        await self.base.route(message)
        # A photo review (approve or reject) hands the item to the details step.
        await self.flow.start_details(
            handle=message.handle, chat_guid=message.chat_guid, key=message.guid
        )
