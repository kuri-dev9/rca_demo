from datetime import datetime
from typing import Optional
from sqlalchemy import BigInteger, Float, String, Text, DateTime, ForeignKey, JSON, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

LONG_TEXT = Text().with_variant(mysql.LONGTEXT, "mysql")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), default="새 대화")
    model: Mapped[str] = mapped_column(String(100), default="gemma4:26b")
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(20))  # user, assistant
    content: Mapped[str] = mapped_column(Text)
    references: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_text: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="attachments")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(default=0)
    chunk_count: Mapped[int] = mapped_column(default=0)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="processing")  # processing, ready, error
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RcaInput(Base):
    __tablename__ = "PR_RCA_INPUT"

    input_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    input_name: Mapped[str] = mapped_column(String(255), default="")
    text: Mapped[str] = mapped_column(LONG_TEXT)
    hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    priority: Mapped[int] = mapped_column(default=0)
    update_dt: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class RcaPrompt(Base):
    __tablename__ = "PR_RCA_PROMPT"

    prompt_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(LONG_TEXT)
    hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    priority: Mapped[int] = mapped_column(default=0)
    update_dt: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class RcaRun(Base):
    __tablename__ = "PR_RCA_RUN"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_mode: Mapped[str] = mapped_column(String(20))
    update_dt: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    steps: Mapped[list["RcaStep"]] = relationship(back_populates="run")


class RcaResult(Base):
    __tablename__ = "PR_RCA_RESULT"

    result_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    text: Mapped[str] = mapped_column(LONG_TEXT)
    accuracy_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reasoning_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actionability_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    accuracy_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reasoning_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    actionability_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    hallucination_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    over_confidence_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evidence_missing_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    domain_bias_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    evaluation_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(default=0)
    update_dt: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class RcaStep(Base):
    __tablename__ = "PR_RCA_STEP"

    step_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    step_type: Mapped[str] = mapped_column(String(50))
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("PR_RCA_RUN.run_id", ondelete="CASCADE"))
    input_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("PR_RCA_INPUT.input_id"))
    prompt_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("PR_RCA_PROMPT.prompt_id"))
    result_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("PR_RCA_RESULT.result_id"), nullable=True)
    priority: Mapped[int] = mapped_column(default=0)
    update_dt: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    run: Mapped["RcaRun"] = relationship(back_populates="steps")
    input: Mapped["RcaInput"] = relationship()
    prompt: Mapped["RcaPrompt"] = relationship()
    result: Mapped[Optional["RcaResult"]] = relationship()


class RcaHumanEvaluation(Base):
    __tablename__ = "PR_RCA_HUMAN_EVAL"

    evaluation_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    result_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("PR_RCA_RESULT.result_id", ondelete="CASCADE"))
    rating: Mapped[str] = mapped_column(String(20))
    selected_result_id: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("PR_RCA_RESULT.result_id"), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evaluator: Mapped[str] = mapped_column(String(100), default="human")
    update_dt: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    result: Mapped["RcaResult"] = relationship(foreign_keys=[result_id])
