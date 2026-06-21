"""
FastAPI SSE endpoint helper.
Evan wires his Redis Pub/Sub to this; Utkarsh's frontend subscribes.

Add to Evan's FastAPI app:
    from arize.sse import create_sse_router
    app.include_router(create_sse_router(redis_client))
"""

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse


def create_sse_router(redis_client) -> APIRouter:
    router = APIRouter()

    @router.get("/events/{session_id}")
    async def event_stream(session_id: str):
        async def generate() -> AsyncGenerator[str, None]:
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(f"safe-agent:{session_id}")
            try:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = message["data"]
                        if isinstance(data, bytes):
                            data = data.decode()
                        yield f"data: {data}\n\n"
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                pass
            finally:
                await pubsub.unsubscribe(f"safe-agent:{session_id}")
                await pubsub.close()

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    return router


# Helper for Evan to publish events from anywhere in the gate/runtime
def publish_event(redis_client, session_id: str, event: dict) -> None:
    """Synchronous publish (use in sync gate code)."""
    channel = f"safe-agent:{session_id}"
    redis_client.publish(channel, json.dumps(event))


async def async_publish_event(redis_client, session_id: str, event: dict) -> None:
    """Async publish (use in async LangGraph nodes)."""
    channel = f"safe-agent:{session_id}"
    await redis_client.publish(channel, json.dumps(event))
