from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models import Conversation, Attachment
from app.file_parser import extract_text

router = APIRouter(prefix="/api/conversations", tags=["attachments"])

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@router.post("/{conversation_id}/attachments")
async def upload_attachment(
    conversation_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="파일 크기는 10MB 이하여야 합니다")

    try:
        text = extract_text(file.filename or "file.txt", content)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"파일을 읽을 수 없습니다: {str(e)}")

    attachment = Attachment(
        conversation_id=conversation_id,
        filename=file.filename or "file.txt",
        content_text=text,
        file_size=len(content),
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    return {
        "id": attachment.id,
        "filename": attachment.filename,
        "file_size": attachment.file_size,
        "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
    }


@router.get("/{conversation_id}/attachments")
async def list_attachments(
    conversation_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Attachment)
        .where(Attachment.conversation_id == conversation_id)
        .order_by(Attachment.created_at.desc())
    )
    attachments = result.scalars().all()
    return [
        {
            "id": a.id,
            "filename": a.filename,
            "file_size": a.file_size,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in attachments
    ]


@router.delete("/{conversation_id}/attachments/{attachment_id}", status_code=204)
async def delete_attachment(
    conversation_id: int,
    attachment_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Attachment).where(
            Attachment.id == attachment_id,
            Attachment.conversation_id == conversation_id,
        )
    )
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="첨부파일을 찾을 수 없습니다")

    await db.delete(attachment)
    await db.commit()
