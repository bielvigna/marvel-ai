from datetime import datetime, timedelta, timezone
from typing import Any


MAX_MEMORY_MESSAGES = 10
MEMORY_TTL_DAYS = 30


class ChatMemory:
    def __init__(self, collection: Any):
        self.collection = collection

    async def initialize(self) -> None:
        await self.collection.create_index("expires_at", expireAfterSeconds=0)

    async def load(self, conversation_id: str) -> list[dict[str, str]]:
        document = await self.collection.find_one(
            {"conversation_id": conversation_id}, {"_id": 0, "messages": 1}
        )
        if not document:
            return []
        return self._valid_messages(document.get("messages", []))

    async def save(self, conversation_id: str, messages: list[dict[str, str]]) -> None:
        valid_messages = self._valid_messages(messages)[-MAX_MEMORY_MESSAGES:]
        expires_at = datetime.now(timezone.utc) + timedelta(days=MEMORY_TTL_DAYS)
        await self.collection.update_one(
            {"conversation_id": conversation_id},
            {
                "$set": {"messages": valid_messages, "expires_at": expires_at},
                "$setOnInsert": {"conversation_id": conversation_id},
            },
            upsert=True,
        )

    @staticmethod
    def _valid_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
        valid = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            role = message.get("role")
            content = message.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                valid.append({"role": role, "content": content[:2000]})
        return valid[-MAX_MEMORY_MESSAGES:]
