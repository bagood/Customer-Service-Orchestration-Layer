import json

from redis.exceptions import WatchError
from app.model import Conversation


class BindingMismatch(Exception):
    pass


class Conversations:
    def __init__(self, redis):
        self.redis = redis

    async def read(self, session, customer):
        key = f"csol:conversation:{session}"
        raw = await self.redis.get(key)
        if raw is None:
            initial = json.dumps(Conversation(customer).dump())
            await self.redis.set(key, initial, nx=True)
            raw = await self.redis.get(key)
        conversation = Conversation(**json.loads(raw))
        if conversation.customer != customer:
            raise BindingMismatch
        return conversation

    async def replace(self, session, previous, updated):
        """Compare the whole snapshot, including any in-flight reservation."""
        key = f"csol:conversation:{session}"
        async with self.redis.pipeline() as pipe:
            try:
                await pipe.watch(key)
                raw = await pipe.get(key)
                if raw is None or json.loads(raw) != previous.dump():
                    return False
                pipe.multi()
                pipe.set(key, json.dumps(updated.dump()))
                await pipe.execute()
                return True
            except WatchError:
                return False
