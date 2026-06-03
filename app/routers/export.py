from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from app.services.search_engine import get_session
from app.services.exporter import build_excel, build_csv

router = APIRouter()


@router.get("/excel/{session_id}")
async def export_excel(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.done:
        raise HTTPException(status_code=409, detail="Search not finished yet")

    data = build_excel(session)
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=patentes_{session_id[:8]}.xlsx"},
    )


@router.get("/csv/{session_id}")
async def export_csv(session_id: str):
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if not session.done:
        raise HTTPException(status_code=409, detail="Search not finished yet")

    data = build_csv(session)
    return Response(
        content=data,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=patentes_{session_id[:8]}.csv"},
    )
