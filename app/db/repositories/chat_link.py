from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ChatLink


class ChatLinkRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_chat_links(self) -> Sequence[ChatLink]:
        result = await self.db.execute(select(ChatLink).order_by(ChatLink.priority.desc()))
        return result.scalars().all()
