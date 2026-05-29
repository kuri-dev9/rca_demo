import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.database import get_db, async_session
from app.config import settings
from app.models import KnowledgeDocument
from app.file_parser import extract_text
from app.chunker import split_text
from app import vector_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20MB


async def generate_summary(text: str, filename: str) -> str:
    preview = text[:4000]
    prompt = (
        "다음 문서의 내용을 분석하여 3~5문장으로 요약해주세요. "
        "문서의 주제, 핵심 내용, 주요 키워드를 포함해주세요. "
        "요약만 출력하고 다른 설명은 하지 마세요.\n\n"
        f"[문서명: {filename}]\n\n"
        f"{preview}"
    )
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": "gemma4:26b", "prompt": prompt, "stream": False},
            )
            data = resp.json()
            summary = data.get("response", "").strip()
            return summary[:2000] if summary else ""
    except Exception as e:
        logger.warning("요약 생성 실패 (filename=%s): %s", filename, e)
        return ""


async def process_document(doc_id: int, filename: str, content: bytes):
    async with async_session() as db:
        try:
            text = extract_text(filename, content)
            if not text.strip():
                await db.execute(
                    update(KnowledgeDocument)
                    .where(KnowledgeDocument.id == doc_id)
                    .values(status="error", error_message="문서에서 텍스트를 추출할 수 없습니다")
                )
                await db.commit()
                return

            summary = await generate_summary(text, filename)

            chunks = split_text(text, chunk_size=500, overlap=50)
            if not chunks:
                await db.execute(
                    update(KnowledgeDocument)
                    .where(KnowledgeDocument.id == doc_id)
                    .values(status="error", error_message="청크 분할 결과가 없습니다")
                )
                await db.commit()
                return

            vector_store.add_chunks(doc_id, chunks)

            await db.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == doc_id)
                .values(status="ready", chunk_count=len(chunks), summary=summary or None)
            )
            await db.commit()

        except Exception as e:
            logger.exception("문서 처리 실패 (doc_id=%d, filename=%s)", doc_id, filename)
            await db.execute(
                update(KnowledgeDocument)
                .where(KnowledgeDocument.id == doc_id)
                .values(status="error", error_message=str(e)[:500])
            )
            await db.commit()


@router.get("")
async def list_documents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(KnowledgeDocument).order_by(KnowledgeDocument.created_at.desc())
    )
    docs = result.scalars().all()
    return [
        {
            "id": d.id,
            "filename": d.filename,
            "file_size": d.file_size,
            "chunk_count": d.chunk_count,
            "summary": d.summary,
            "status": d.status,
            "error_message": d.error_message,
            "created_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기는 20MB 이하여야 합니다")

    doc = KnowledgeDocument(
        filename=file.filename or "document.txt",
        file_size=len(content),
        status="processing",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    background_tasks.add_task(process_document, doc.id, doc.filename, content)

    return {
        "id": doc.id,
        "filename": doc.filename,
        "file_size": doc.file_size,
        "status": doc.status,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


@router.get("/{doc_id}/status")
async def get_document_status(doc_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")
    return {
        "id": doc.id,
        "status": doc.status,
        "chunk_count": doc.chunk_count,
        "summary": doc.summary,
        "error_message": doc.error_message,
    }


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다")

    vector_store.delete_by_doc_id(doc_id)
    await db.delete(doc)
    await db.commit()
