"""Production main.py — thin wrapper over api_server lifespan."""

import os
import sys

# Load .env
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from src.youtube_instagram_bot.config.settings import get_settings
from src.youtube_instagram_bot.logging_config import configure_logging, get_logger

settings = get_settings()
configure_logging()
log = get_logger("main")

def main() -> None:
    import uvicorn
    log.info(
        "launching",
        host=settings.api_host,
        port=settings.api_port,
        environment=settings.environment,
        workers=settings.api_workers,
    )
    uvicorn.run(
        "api_server:app",
        host=settings.api_host,
        port=settings.api_port,
        workers=settings.api_workers,
        reload=(settings.environment == "development"),
        log_level=settings.log_level.lower(),
        access_log=True,
    )

if __name__ == "__main__":
    main()
