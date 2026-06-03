import json
import uuid
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from app.models import SearchConfig
from app.services.search_engine import start_search, stream_events, get_session
from app.sources.lens import LENS_QUERIES
from app.sources.epo import EPO_QUERIES
from app.sources.inpi import INPI_QUERIES, create_inpi_session, login_inpi, _do_search, _parse_results

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


@router.get("/queries")
async def get_queries():
    """Retorna as queries padrão de todas as fontes para edição no frontend."""
    return {
        "lens": LENS_QUERIES,
        "epo": EPO_QUERIES,
        "inpi": INPI_QUERIES,
    }


@router.get("/test/inpi")
async def test_inpi(q: str = "ESTERILIZ*"):
    """
    Testa uma query no INPI pePI e retorna diagnóstico completo:
    status HTTP, URL final, total encontrado, registros parseados e trecho do HTML.
    """
    session = create_inpi_session()
    logged_in = login_inpi(session)
    if not logged_in:
        return {"ok": False, "etapa": "login", "erro": "Falha ao iniciar sessão no INPI pePI"}

    query = {"id": "TEST", "desc": "Teste manual", "str": q}
    resp = _do_search(session, query, 1)

    if resp is None:
        return {"ok": False, "etapa": "request", "erro": "Requisição não retornou resposta (timeout ou erro de rede)"}

    results, total, has_next = _parse_results(resp.text, query)

    # Extrai trecho relevante do HTML para diagnóstico
    html_snippet = resp.text[:1500].replace("\n", " ").replace("\r", "")

    return {
        "ok": True,
        "status_http": resp.status_code,
        "url_final": str(resp.url),
        "total_encontrado_na_base": total,
        "registros_parseados": len(results),
        "has_next_page": has_next,
        "primeiros_resultados": [
            {"numero": r.numero, "titulo": r.titulo, "depositante": r.depositante}
            for r in results[:5]
        ],
        "html_snippet": html_snippet,
    }
