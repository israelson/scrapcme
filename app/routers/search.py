import json
import uuid
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.models import SearchConfig
from app.services.search_engine import start_search, stream_events, get_session

router = APIRouter()


@router.post("/start")
async def search_start(config: SearchConfig):
    session_id = str(uuid.uuid4())
    start_search(session_id, config)
    return {"session_id": session_id, "ok": True}


@router.get("/stream/{session_id}")
async def search_stream(session_id: str):
    async def generator():
        async for event_type, data in stream_events(session_id):
            if event_type == "keepalive":
                yield ": keepalive\n\n"
            else:
                payload = json.dumps(data, ensure_ascii=False)
                yield f"event: {event_type}\ndata: {payload}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status/{session_id}")
async def search_status(session_id: str):
    session = get_session(session_id)
    if not session:
        return {"error": "session not found"}
    return {
        "running": session.running,
        "done": session.done,
        "progress": session.progress,
        "logs": session.logs[-100:],
        "results": [r.model_dump() for r in session.results],
        "sumario": [s.model_dump() for s in session.sumario],
        "error": session.error,
    }
