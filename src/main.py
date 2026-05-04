from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import logging

from src.api.routes import router as api_router

logger = logging.getLogger(__name__)

from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from src.core.rumination import rumination_engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start the background rumination scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(rumination_engine.ruminate, 'interval', hours=6)
    scheduler.start()
    logger.info("Rumination scheduler started (Interval: 6h)")
    
    yield
    
    # Shutdown
    scheduler.shutdown()
    logger.info("Rumination scheduler stopped")

app = FastAPI(title="AIManager Knowledge Explorer", lifespan=lifespan)

# Allow CORS for local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(api_router, prefix="/api")

# Mount Explorer static files at root
app.mount("/", StaticFiles(directory="src/explorer", html=True), name="explorer")

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting Explorer on http://localhost:8000")
    uvicorn.run("src.main:app", host="127.0.0.1", port=8000, reload=True)
