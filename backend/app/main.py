from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.database import engine, Base
from app.routes import conversations, chat, models, attachments, knowledge, rca


async def ensure_rca_lab_schema(conn):
    if conn.dialect.name != "mysql":
        return

    db_name = engine.url.database
    run_columns = {
        "model": "VARCHAR(100) NULL",
    }
    existing_run = await conn.execute(
        text(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = :db_name
              AND TABLE_NAME = 'PR_RCA_RUN'
            """
        ),
        {"db_name": db_name},
    )
    existing_run_columns = {row[0] for row in existing_run}
    for column_name, column_type in run_columns.items():
        if column_name not in existing_run_columns:
            await conn.execute(text(f"ALTER TABLE PR_RCA_RUN ADD COLUMN {column_name} {column_type}"))

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

    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS PR_RCA_JUDGE (
                judge_id BIGINT NOT NULL AUTO_INCREMENT,
                result_id BIGINT NOT NULL,
                judge_type VARCHAR(20) NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'SUCCESS',
                total_score DOUBLE NULL,
                accuracy_score DOUBLE NULL,
                reasoning_score DOUBLE NULL,
                evidence_score DOUBLE NULL,
                actionability_score DOUBLE NULL,
                accuracy_comment TEXT NULL,
                reasoning_comment TEXT NULL,
                evidence_comment TEXT NULL,
                actionability_comment TEXT NULL,
                judge_comment TEXT NULL,
                raw_response LONGTEXT NULL,
                evaluator VARCHAR(100) NULL,
                update_dt TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (judge_id),
                KEY idx_pr_rca_judge_result_id (result_id),
                KEY idx_pr_rca_judge_type (judge_type),
                CONSTRAINT fk_pr_rca_judge_result
                    FOREIGN KEY (result_id) REFERENCES PR_RCA_RESULT (result_id)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
    )


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
