import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import ValidationError

from app.config import get_settings
from app.database import Base, engine
from app.models import lead as _lead_models  # noqa: F401 — registers models with Base
from app.routes import leads, webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        get_settings()
        logger.info("Configuration validated — OPENAI_API_KEY is set.")
    except ValidationError:
        logger.critical(
            "Missing required environment variable: OPENAI_API_KEY\n"
            "Create a .env file (see .env.example) and set your key."
        )
        sys.exit(1)

    Base.metadata.create_all(bind=engine)
    logger.info("Database tables verified.")
    yield
    logger.info("Application shutting down.")


app = FastAPI(
    title="AI Lead Qualification Agent",
    description="Automatically qualifies inbound leads using OpenAI and routes them to the right sales team.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(webhook.router)
app.include_router(leads.router)


@app.get("/health", tags=["Health"])
def health_check():
    return {"status": "ok"}
