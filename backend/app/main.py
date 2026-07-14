from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import engine, Base
from app.routes import conversations, chat, models, attachments, knowledge, rca


async def ensure_rca_lab_schema(conn):
    if conn.dialect.name != "mysql":
        return

    result_columns = {
        "accuracy_score": "DOUBLE NULL",
        "reasoning_score": "DOUBLE NULL",
        "evidence_score": "DOUBLE NULL",
        "actionability_score": "DOUBLE NULL",
        "accuracy_comment": "TEXT NULL",
        "reasoning_comment": "TEXT NULL",
        "evidence_comment": "TEXT NULL",
        "actionability_comment": "TEXT NULL",
    }
    db_name = engine.url.database
    existing = await conn.execute(
        text(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = :db_name
              AND TABLE_NAME = 'PR_RCA_RESULT'
            """
        ),
        {"db_name": db_name},
    )
    existing_columns = {row[0] for row in existing}
    for column_name, column_type in result_columns.items():
        if column_name not in existing_columns:
            await conn.execute(text(f"ALTER TABLE PR_RCA_RESULT ADD COLUMN {column_name} {column_type}"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_rca_lab_schema(conn)
    yield
    await engine.dispose()


app = FastAPI(title="Chat Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations.router)
app.include_router(chat.router)
app.include_router(models.router)
app.include_router(attachments.router)
app.include_router(knowledge.router)
app.include_router(rca.router)
app.include_router(rca.sample_router)


@app.get("/api/health")
async def health():
    return {"status": "ok"}
