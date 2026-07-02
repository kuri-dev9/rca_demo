from datetime import datetime
from pydantic import BaseModel, field_validator


class MessageBase(BaseModel):
    role: str
    content: str


class MessageResponse(MessageBase):
    id: int
    conversation_id: int
    references: list[dict] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationCreate(BaseModel):
    title: str = "새 대화"
    model: str = "gemma4:26b"
    system_prompt: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = None
    model: str | None = None
    system_prompt: str | None = None


class ConversationResponse(BaseModel):
    id: int
    title: str
    model: str
    system_prompt: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ConversationDetailResponse(ConversationResponse):
    messages: list[MessageResponse] = []


class ChatRequest(BaseModel):
    message: str
    agent_mode: bool = False

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("메시지가 비어있습니다")
        return stripped


class ModelResponse(BaseModel):
    name: str
    size: int
    modified_at: str


class SearchResult(BaseModel):
    conversation_id: int
    conversation_title: str
    message_id: int
    role: str
    content_snippet: str
    created_at: datetime

    class Config:
        from_attributes = True


class ConversationExport(BaseModel):
    title: str
    model: str
    system_prompt: str | None = None
    created_at: str
    messages: list[dict]


class ConversationImport(BaseModel):
    title: str
    model: str = "gemma4:26b"
    system_prompt: str | None = None
    messages: list[MessageBase] = []


class RcaPromptCreate(BaseModel):
    text: str
    priority: int = 0


class RcaPromptResponse(BaseModel):
    prompt_id: int
    hash: str
    priority: int

    class Config:
        from_attributes = True


class RcaRunNormalRequest(BaseModel):
    input_id: int
    prompt_id: int
    model: str = "gemma4:26b"
    priority: int = 0


class RcaRunNormalResponse(BaseModel):
    success: bool
    run_id: int
    step_id: int
    result_id: int
