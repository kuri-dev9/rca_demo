from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import Conversation, Message
from app.schemas import (
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationDetailResponse,
    ConversationImport,
    SearchResult,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation).order_by(Conversation.updated_at.desc())
    )
    return result.scalars().all()


@router.get("/search", response_model=list[SearchResult])
async def search_conversations(
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    keyword = f"%{q}%"
    result = await db.execute(
        select(Message)
        .join(Conversation)
        .where(
            or_(
                Message.content.like(keyword),
                Conversation.title.like(keyword),
            )
        )
        .options(selectinload(Message.conversation))
        .order_by(Message.created_at.desc())
        .limit(50)
    )
    messages = result.scalars().all()
    results = []
    for m in messages:
        idx = m.content.lower().find(q.lower())
        start = max(0, idx - 40)
        end = min(len(m.content), idx + len(q) + 40)
        snippet = ("..." if start > 0 else "") + m.content[start:end] + ("..." if end < len(m.content) else "")
        results.append(SearchResult(
            conversation_id=m.conversation_id,
            conversation_title=m.conversation.title,
            message_id=m.id,
            role=m.role,
            content_snippet=snippet,
            created_at=m.created_at,
        ))
    return results


@router.post("", response_model=ConversationResponse, status_code=201)
async def create_conversation(
    data: ConversationCreate, db: AsyncSession = Depends(get_db)
):
    conv = Conversation(title=data.title, model=data.model, system_prompt=data.system_prompt)
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
async def get_conversation(conversation_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")
    return conv


@router.patch("/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    conversation_id: int,
    data: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")

    if data.title is not None:
        conv.title = data.title
    if data.model is not None:
        conv.model = data.model
    if data.system_prompt is not None:
        conv.system_prompt = data.system_prompt if data.system_prompt else None

    await db.commit()
    await db.refresh(conv)
    return conv


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")

    await db.delete(conv)
    await db.commit()


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: int,
    format: str = Query("json", pattern="^(json|markdown)$"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Conversation)
        .where(Conversation.id == conversation_id)
        .options(selectinload(Conversation.messages))
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")

    if format == "markdown":
        lines = [f"# {conv.title}\n"]
        if conv.system_prompt:
            lines.append(f"> **시스템 프롬프트:** {conv.system_prompt}\n")
        lines.append(f"모델: {conv.model}  ")
        lines.append(f"생성일: {conv.created_at.isoformat()}\n")
        lines.append("---\n")
        for m in conv.messages:
            role_label = "사용자" if m.role == "user" else "AI"
            lines.append(f"### {role_label}\n")
            lines.append(f"{m.content}\n")
        content = "\n".join(lines)
        filename = quote(f"{conv.title}.md")
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )

    import json
    export_data = {
        "title": conv.title,
        "model": conv.model,
        "system_prompt": conv.system_prompt,
        "created_at": conv.created_at.isoformat(),
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "references": m.references,
                "created_at": m.created_at.isoformat(),
            }
            for m in conv.messages
        ],
    }
    content = json.dumps(export_data, ensure_ascii=False, indent=2)
    filename = quote(f"{conv.title}.json")
    return Response(
        content=content,
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
    )


@router.post("/import", response_model=ConversationResponse, status_code=201)
async def import_conversation(
    data: ConversationImport,
    db: AsyncSession = Depends(get_db),
):
    conv = Conversation(
        title=data.title,
        model=data.model,
        system_prompt=data.system_prompt,
    )
    db.add(conv)
    await db.flush()

    for msg in data.messages:
        m = Message(
            conversation_id=conv.id,
            role=msg.role,
            content=msg.content,
        )
        db.add(m)

    await db.commit()
    await db.refresh(conv)
    return conv
