import logging

from src.platform.app_factory import create_platform_app

logger = logging.getLogger(__name__)

app = create_platform_app()

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting AIManager platform on http://localhost:8000")
    uvicorn.run("src.main:app", host="127.0.0.1", port=8000, reload=True)
