from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.routers import search, export

app = FastAPI(title="Patent Hunter CME/CSSD/SPD")

app.include_router(search.router, prefix="/api/search")
app.include_router(export.router, prefix="/api/export")

app.mount("/static", StaticFiles(directory="frontend"), name="static")


@app.get("/")
async def index():
    return FileResponse("frontend/index.html")
