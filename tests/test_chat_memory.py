from datetime import datetime, timedelta, timezone

import pytest

from app.chat_memory import ChatMemory


class FakeCollection:
    def __init__(self):
        self.indexes = []
        self.document = None

    async def create_index(self, field, **options):
        self.indexes.append((field, options))

    async def find_one(self, query, projection=None):
        if self.document and self.document["conversation_id"] == query["conversation_id"]:
            return self.document
        return None

    async def update_one(self, query, update, upsert=False):
        self.document = {"conversation_id": query["conversation_id"], **update["$set"]}


@pytest.mark.asyncio
async def test_memory_expires_after_thirty_days_and_keeps_only_ten_messages():
    collection = FakeCollection()
    memory = ChatMemory(collection)
    messages = [{"role": "user", "content": f"message-{i}"} for i in range(13)]

    await memory.initialize()
    await memory.save("7c9e6679-7425-40de-944b-e07fc1f90ae7", messages)

    assert collection.indexes == [("expires_at", {"expireAfterSeconds": 0})]
    assert [item["content"] for item in collection.document["messages"]] == [f"message-{i}" for i in range(3, 13)]
    assert collection.document["expires_at"] > datetime.now(timezone.utc)
    assert collection.document["expires_at"] <= datetime.now(timezone.utc) + timedelta(days=30, seconds=2)


@pytest.mark.asyncio
async def test_memory_load_returns_empty_for_a_new_conversation():
    memory = ChatMemory(FakeCollection())
    assert await memory.load("7c9e6679-7425-40de-944b-e07fc1f90ae7") == []


@pytest.mark.asyncio
async def test_memory_is_scoped_to_its_conversation_id():
    memory = ChatMemory(FakeCollection())
    await memory.save("7c9e6679-7425-40de-944b-e07fc1f90ae7", [{"role": "user", "content": "one"}])

    assert await memory.load("7c9e6679-7425-40de-944b-e07fc1f90ae7") == [{"role": "user", "content": "one"}]
    assert await memory.load("b42adbef-e6b5-40c2-b8db-c4ec9ce2a4bc") == []
