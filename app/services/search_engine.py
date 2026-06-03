import asyncio
import threading
from datetime import datetime
from typing import Callable

from app.models import SearchConfig, SearchSession, SumarioItem
from app.sources.lens import LENS_QUERIES, search_lens
from app.sources.epo import EPO_QUERIES, search_epo
from app.sources.inpi import INPI_QUERIES, create_inpi_session, login_inpi, search_inpi

# In-memory session store
sessions: dict[str, SearchSession] = {}

# SSE event queues per session
event_queues: dict[str, asyncio.Queue] = {}


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _run_in_thread(session_id: str, config: SearchConfig, loop: asyncio.AbstractEventLoop):
    session = sessions[session_id]
    queue = event_queues[session_id]

    def emit(event_type: str, data: dict):
        session.logs.append({"ts": _ts(), "event": event_type, **data})
        asyncio.run_coroutine_threadsafe(queue.put((event_type, data)), loop)

    def log(msg: str, level: str = "info"):
        entry = {"ts": _ts(), "msg": msg, "level": level}
        session.logs.append(entry)
        asyncio.run_coroutine_threadsafe(queue.put(("log", entry)), loop)

    # Usar queries customizadas se fornecidas, senão usar os padrões
    active_lens  = config.lens_queries  if config.lens_queries  else LENS_QUERIES
    active_epo   = config.epo_queries   if config.epo_queries   else EPO_QUERIES
    active_inpi  = config.inpi_queries  if config.inpi_queries  else INPI_QUERIES

    total_queries = (
        (len(active_lens) if config.use_lens and config.lens_token else 0)
        + (len(active_epo) if config.use_epo and config.epo_key else 0)
        + (len(active_inpi) if config.use_inpi else 0)
    )
    completed_queries = 0

    def update_progress(label: str):
        nonlocal completed_queries
        completed_queries += 1
        pct = int((completed_queries / max(total_queries, 1)) * 100)
        session.progress = pct
        asyncio.run_coroutine_threadsafe(
            queue.put(("progress", {"pct": pct, "label": label})), loop
        )

    try:
        # --- Lens.org ---
        if config.use_lens and config.lens_token:
            log("=== Iniciando Lens.org ===")
            for query in active_lens:
                log(f"→ {query['id']}: {query['desc']}")
                try:
                    results, total = search_lens(config.lens_token, query)
                    for r in results:
                        session.results.append(r)
                        emit("result", r.model_dump())
                    session.sumario.append(SumarioItem(
                        query_id=query["id"],
                        descricao=query["desc"],
                        fonte="Lens.org",
                        string=query["str"],
                        total=str(total),
                        coletado=len(results),
                    ))
                    log(f"  ✓ {len(results)} coletados (total na base: {total})", "success")
                except Exception as e:
                    log(f"  ✗ Erro em {query['id']}: {e}", "error")
                update_progress(f"Lens → {query['id']}")
        else:
            log("Lens.org: ignorado (sem token ou desativado)", "warn")

        # --- EPO OPS ---
        if config.use_epo and config.epo_key:
            log("=== Iniciando EPO OPS ===")
            for query in active_epo:
                log(f"→ {query['id']}: {query['desc']}")
                try:
                    results, total = search_epo(config.epo_key, config.epo_secret, query)
                    for r in results:
                        session.results.append(r)
                        emit("result", r.model_dump())
                    session.sumario.append(SumarioItem(
                        query_id=query["id"],
                        descricao=query["desc"],
                        fonte="EPO OPS",
                        string=query["cql"],
                        total=str(total),
                        coletado=len(results),
                    ))
                    log(f"  ✓ {len(results)} coletados (total na base: {total})", "success")
                except Exception as e:
                    log(f"  ✗ Erro em {query['id']}: {e}", "error")
                update_progress(f"EPO → {query['id']}")
        else:
            log("EPO OPS: ignorado (sem credenciais ou desativado)", "warn")

        # --- INPI pePI ---
        if config.use_inpi:
            log("=== Iniciando INPI pePI ===")
            inpi_session = create_inpi_session()
            if not login_inpi(inpi_session):
                log("INPI: falha ao iniciar sessão — ignorando fonte", "error")
                for _ in active_inpi:
                    update_progress("INPI → (skipped)")
            else:
                log("INPI: sessão iniciada", "success")
                for query in active_inpi:
                    log(f"→ {query['id']}: {query['desc']}")
                    try:
                        results, total = search_inpi(inpi_session, query, log_fn=log)
                        for r in results:
                            session.results.append(r)
                            emit("result", r.model_dump())
                        session.sumario.append(SumarioItem(
                            query_id=query["id"],
                            descricao=query["desc"],
                            fonte="INPI pePI",
                            string=query["str"],
                            total=str(total) if total else "?",
                            coletado=len(results),
                        ))
                        log(f"  ✓ {len(results)} coletados", "success")
                    except Exception as e:
                        log(f"  ✗ Erro em {query['id']}: {e}", "error")
                    update_progress(f"INPI → {query['id']}")
        else:
            log("INPI pePI: ignorado (desativado)", "warn")

    except Exception as e:
        session.error = str(e)
        log(f"Erro fatal: {e}", "error")
    finally:
        session.running = False
        session.done = True
        session.progress = 100
        total_count = len(session.results)
        log(f"=== Busca concluída: {total_count} patentes coletadas ===", "success")
        asyncio.run_coroutine_threadsafe(
            queue.put(("done", {"total": total_count, "session_id": session_id})), loop
        )
        asyncio.run_coroutine_threadsafe(queue.put(None), loop)


def start_search(session_id: str, config: SearchConfig) -> SearchSession:
    session = SearchSession(session_id=session_id, config=config, running=True)
    sessions[session_id] = session
    event_queues[session_id] = asyncio.Queue()

    loop = asyncio.get_event_loop()
    t = threading.Thread(
        target=_run_in_thread,
        args=(session_id, config, loop),
        daemon=True,
    )
    t.start()
    return session


async def stream_events(session_id: str):
    queue = event_queues.get(session_id)
    if queue is None:
        return

    while True:
        try:
            item = await asyncio.wait_for(queue.get(), timeout=15.0)
        except asyncio.TimeoutError:
            # Send keepalive to prevent proxy/load-balancer from closing the connection
            yield "keepalive", {}
            continue

        if item is None:
            break
        event_type, data = item
        yield event_type, data


def get_session(session_id: str) -> SearchSession | None:
    return sessions.get(session_id)
