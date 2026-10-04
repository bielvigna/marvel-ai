import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from .agent import create_marvel_agent, normalize_spoiler_level
from .chat_memory import ChatMemory
from .comic_vine import ComicVineClient, ComicVineError
from .config import get_settings
from .schemas import Character, CharacterPage, ChatRequest, ChatResponse

logger = logging.getLogger(__name__)


async def create_chat_memory(settings):
    if not settings.mongodb_uri:
        return None, None
    from pymongo import AsyncMongoClient
    from pymongo.errors import PyMongoError

    client = AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
    try:
        database = client.get_default_database(default="marvel_battlefield")
        memory = ChatMemory(database["chat_memory"])
        await memory.initialize()
        return client, memory
    except PyMongoError:
        await client.close()
        raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = get_settings()
    app.state.mongo_client = None
    app.state.chat_memory = None
    from pymongo.errors import PyMongoError

    try:
        app.state.mongo_client, app.state.chat_memory = await create_chat_memory(app.state.settings)
    except PyMongoError:
        logger.warning("Mongo chat memory is unavailable; continuing without persisted history.")
    try:
        yield
    finally:
        if app.state.mongo_client is not None:
            await app.state.mongo_client.close()


app = FastAPI(title="Marvel Battlefield API", version="1.0.0", lifespan=lifespan)


def comic_vine_client() -> ComicVineClient:
    settings = get_settings()
    return ComicVineClient(settings.comic_vine_api_key)


def error_response(error: ComicVineError) -> HTTPException:
    return HTTPException(status_code=error.status_code, detail={"code": error.code, "message": error.message})


@app.get("/health")
def health():
    settings = get_settings()
    return {"status": "ok", "comic_vine_configured": bool(settings.comic_vine_api_key),
            "ai_configured": bool(settings.ai_api_key and settings.ai_model)}


@app.get("/api/characters", response_model=CharacterPage)
def characters(q: str = Query(default="", max_length=120), limit: int = Query(default=20, ge=1, le=50),
               offset: int = Query(default=0, ge=0), include_relations: bool = False):
    client = comic_vine_client()
    try:
        return client.search_characters(q.strip(), limit, offset, include_relations=include_relations)
    except ComicVineError as exc:
        raise error_response(exc) from exc
    finally:
        client.close()


@app.get("/api/characters/{character_id}", response_model=Character)
def character(character_id: int):
    client = comic_vine_client()
    try:
        return client.get_character(character_id)
    except ComicVineError as exc:
        raise error_response(exc) from exc
    finally:
        client.close()


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, http_request: Request):
    settings = get_settings()
    client = comic_vine_client()
    try:
        level = normalize_spoiler_level(request.spoiler_level)
        agent = create_marvel_agent(settings, client, level, request.language)
    except RuntimeError as exc:
        client.close()
        if str(exc) == "AI_NOT_CONFIGURED":
            raise HTTPException(status_code=503, detail={"code": "ai_not_configured", "message": "The AI service is not configured."}) from exc
        raise HTTPException(status_code=503, detail={"code": "ai_provider_unsupported", "message": "The configured AI provider is not supported."}) from exc

    conversation_id = str(request.conversation_id) if request.conversation_id else None
    memory = getattr(http_request.app.state, "chat_memory", None)
    from pymongo.errors import PyMongoError

    memory_available = memory is not None and conversation_id is not None
    messages = []
    if memory_available:
        try:
            messages = await memory.load(conversation_id)
        except PyMongoError:
            logger.warning("Mongo chat memory read failed; using request history for this turn.")
            memory_available = False
    if not memory_available:
        for item in request.history[-10:]:
            if item.role in {"user", "assistant"}:
                messages.append({"role": item.role, "content": item.content[:2000]})
    messages.append({"role": "user", "content": request.message.strip()})
    try:
        result = await agent.ainvoke({"messages": messages})
        final_message = result["messages"][-1]
        answer = final_message.content
        if isinstance(answer, list):
            answer = "\n".join(str(block.get("text", "")) for block in answer if isinstance(block, dict))
        sources = []
        for message in result["messages"]:
            if getattr(message, "type", "") == "tool":
                try:
                    tool_data = json.loads(message.content)
                    url = tool_data.get("source_url")
                    if url and url not in sources:
                        sources.append(url)
                    result_data = tool_data.get("result")
                    if isinstance(result_data, dict):
                        detail_url = result_data.get("api_detail_url")
                        if detail_url and detail_url not in sources: sources.append(detail_url)
                    for item in tool_data.get("results", []):
                        if isinstance(item, dict) and item.get("api_detail_url") and item["api_detail_url"] not in sources:
                            sources.append(item["api_detail_url"])
                except (TypeError, ValueError):
                    continue
        if memory_available:
            try:
                await memory.save(conversation_id, messages + [{
                    "role": "assistant", "content": str(answer)[:2000]
                }])
            except PyMongoError:
                logger.warning("Mongo chat memory write failed; returning the answer without persistence.")
        return ChatResponse(answer=str(answer), sources=sources)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"code": "ai_request_failed", "message": "The AI could not complete the request."}) from exc
    finally:
        client.close()


@app.exception_handler(HTTPException)
async def structured_http_error(request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "request_failed", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": detail})
