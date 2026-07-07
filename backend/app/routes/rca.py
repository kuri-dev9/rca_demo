"""
routes/rca.py
RCA 분석 라우터.
POST /api/rca/analyze     — xDR 파일 업로드 → 분석 → 결과 반환
GET  /api/rca/conversations/{conv_id}/report  — SSE LLM 보고서 스트리밍
"""
from __future__ import annotations

import asyncio
import gc
import hashlib
import json
import logging
import os
import resource
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.models import Conversation, Message, RcaInput, RcaPrompt, RcaResult, RcaRun, RcaStep
from app.schemas import RcaPromptCreate, RcaPromptResponse, RcaRunNormalRequest, RcaRunNormalResponse
from app.llm_debug import prompt_debug_event
from app.rca.analyzer import RcaAnalysis, analyze
from app.rca.claude_verifier import (
    CLAUDE_SYSTEM_PROMPT,
    CLAUDE_VERIFIER_MODEL,
    ClaudeVerifierError,
    _build_user_prompt,
    verify_and_correct_step,
)
from app.rca.forbidden_terms import build_retry_instruction, find_forbidden_terms
from app.rca.parser import parse_file
from app.rca.spec_loader import get_call_type_name
from app.rca.report_builder import (
    build_fact_ranking_json,
    build_fact_ranking_text,
    build_compact_rca_ir,
    build_compact_reasoning_json,
    build_local_step2_enrichment_messages,
    build_local_step3_rca_messages,
    build_rca_messages,
    build_report_prompt_from_reasoning,
    build_loop_reasoning_steps,
    build_reasoning_messages,
    _ir_to_markdown,
)

router = APIRouter(prefix="/api/rca", tags=["rca"])
sample_router = APIRouter(prefix="/api/v1/analysis", tags=["rca"])
logger = logging.getLogger(__name__)

RCA_MODEL = "gemma4:26b"
RCA_MAX_FILE_BYTES = 500 * 1024 * 1024  # 500 MB
QUALITY_STEP_TIMEOUT_SEC = 300.0
BASE_NUM_PREDICT = 1024
STEP4_NUM_PREDICT = 2048
NORMAL_RUN_NUM_PREDICT = 4096
STEP2A_NUM_PREDICT_MULTIPLIER = 4
STEP3A_NUM_PREDICT_MULTIPLIER = 4
QUALITY_THINKING_LOG_LIMIT = 2000
_SAMPLE_FILE_CANDIDATES = [
    Path(os.environ["PROJ_HOME"]) / "docs" / "data" / "sample.dat"
    if os.environ.get("PROJ_HOME")
    else None,
    Path.cwd() / "docs" / "data" / "sample.dat",
    Path(__file__).resolve().parents[2] / "docs" / "data" / "sample.dat",
    Path(__file__).resolve().parents[3] / "docs" / "data" / "sample.dat",
]


def build_quality_options(*, think: bool, multiplier: int = 1) -> dict[str, Any]:
    options: dict[str, Any] = {"num_predict": BASE_NUM_PREDICT}
    if think:
        options.update({
            "num_predict": BASE_NUM_PREDICT * multiplier,
            "temperature": 1.0,
            "top_p": 0.95,
            "top_k": 64,
        })
    return options


def build_core_options(*, num_predict: int = BASE_NUM_PREDICT) -> dict[str, Any]:
    return {
        "num_predict": num_predict,
        "repeat_penalty": 1.3,
        "repeat_last_n": 256,
    }


def _sample_file_path() -> Path:
    for path in _SAMPLE_FILE_CANDIDATES:
        if path and path.exists():
            return path
    return Path.cwd() / "docs" / "data" / "sample.dat"


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def _get_or_create_rca_input(
    db: AsyncSession,
    *,
    input_name: str,
    text: str,
    priority: int = 0,
) -> tuple[RcaInput, bool]:
    text_hash = _sha256_text(text)
    existing = await db.scalar(select(RcaInput).where(RcaInput.hash == text_hash))
    if existing:
        return existing, False
    row = RcaInput(
        input_name=input_name,
        text=text,
        hash=text_hash,
        priority=priority,
    )
    db.add(row)
    await db.flush()
    return row, True


async def _get_or_create_rca_prompt(
    db: AsyncSession,
    *,
    text: str,
    priority: int = 0,
) -> tuple[RcaPrompt, bool]:
    text_hash = _sha256_text(text)
    existing = await db.scalar(select(RcaPrompt).where(RcaPrompt.hash == text_hash))
    if existing:
        return existing, False
    row = RcaPrompt(text=text, hash=text_hash, priority=priority)
    db.add(row)
    await db.flush()
    return row, True


def _extract_chat_content(payload: dict[str, Any]) -> str:
    message = payload.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if content:
            return str(content)
    for key in ("response", "content"):
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _rss_mb() -> float:
    try:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except Exception:
        return 0.0


def _subscriber_pattern_rows(analysis: RcaAnalysis) -> list[dict[str, Any]]:
    rows = []
    for seq in analysis.top_failed_imsi_sequences:
        attempts = int(seq.get("attempts") or 0)
        failures = int(seq.get("failures") or 0)
        rows.append({
            "imsi_prefix": seq.get("imsi", ""),
            "stage": seq.get("stage", ""),
            "cause": seq.get("cause", ""),
            "attempts": attempts,
            "failures": failures,
            "imsi_failure_rate": round(failures / attempts * 100, 1) if attempts else 0.0,
            "total_failure_share": round(failures / analysis.failure_count * 100, 1)
            if analysis.failure_count else 0.0,
            "mme_count": int(seq.get("mme_count") or 0),
            "enb_count": int(seq.get("enb_count") or 0),
            "zero_success": int(seq.get("success") or 0) == 0,
        })
    return rows


def _analysis_to_response(analysis: RcaAnalysis, conv_id: int, compact_rca_ir: dict[str, Any]) -> dict[str, Any]:
    """RcaAnalysis → JSON-serializable response dict."""
    chains_raw = []
    for c in analysis.failure_chains[:20]:
        chains_raw.append({
            "procedure": c.procedure,
            "call_type_code": c.call_type,
            "call_type": get_call_type_name(c.call_type),
            "failure_point": c.failure_point,
            "failure_interface": c.failure_interface,
            "failure_message": c.failure_message,
            "failure_cause": c.failure_cause,
            "failure_cause_name": c.failure_cause_name,
            "failure_semantic": c.failure_semantic,
            "chain": c.chain,
        })

    assistant_message = _ir_to_markdown(compact_rca_ir)

    return {
        "parse_stats": analysis.parse_stats,
        "summary": {
            "total_records": analysis.total_records,
            "attempt_count": analysis.attempt_count,
            "success_count": analysis.success_count,
            "failure_count": analysis.failure_count,
            "failure_rate": analysis.failure_rate,
        },
        # frontend 호환 유지 — LLM이 판단하므로 빈 값
        "primary_root_cause": {},
        "top_root_causes": [],
        "recommended_actions": [],
        "failure_chains": chains_raw,
        "error_chains": analysis.error_chains,
        "impacted_nodes": {
            "mme_count": len(analysis.affected_mme_ids),
            "enb_count": len(analysis.affected_enb_ids),
            "apn_count": len(analysis.affected_apns),
            "affected_users": len(analysis.affected_imsi_set),
        },
        "time_distribution": analysis.time_distribution,
        "burst_detected": analysis.burst_detected,
        "burst_window": analysis.burst_window,
        "interface_distribution": analysis.interface_distribution,
        "repeated_failure_count": len(analysis.repeated_failures),
        "conversation_id": conv_id,
        "assistant_message": assistant_message,
    }


async def _analyze_file_path(
    filepath: str,
    filename: str,
    model: str,
    db: AsyncSession,
    loop_mode: bool = False,
) -> dict[str, Any]:
    records = analysis = compact_rca_ir = assistant_message = response = None
    try:
        logger.debug("rca memory before_parse rss_mb=%.1f", _rss_mb())
        records, parse_stats = await asyncio.to_thread(parse_file, filepath)
        logger.debug("rca memory after_parse rss_mb=%.1f records=%s", _rss_mb(), parse_stats.get("parsed", 0))
        if parse_stats.get("parsed", 0) <= 0:
            raise HTTPException(status_code=422, detail="파싱 가능한 레코드가 없습니다")

        analysis = await asyncio.to_thread(analyze, records, parse_stats)
        logger.debug("rca memory after_analysis rss_mb=%.1f", _rss_mb())

        compact_rca_ir = build_compact_rca_ir(analysis)
        if loop_mode:
            # Preserve the current loop-mode input shape while the one-shot RCA path
            # uses aggregate-only subscriber_summary.
            compact_rca_ir["subscriber_failure_patterns"] = _subscriber_pattern_rows(analysis)
            compact_rca_ir["subscriber_mobility_summary"] = analysis.subscriber_mobility_summary
        conv = Conversation(
            title=f"RCA: {filename}",
            model=model or RCA_MODEL,
            system_prompt=json.dumps({
                "compact_rca_ir": compact_rca_ir,
                "rca_loop_mode": loop_mode,
            }, ensure_ascii=False),
        )
        db.add(conv)
        await db.flush()

        assistant_message = _ir_to_markdown(compact_rca_ir)
        db.add(Message(
            conversation_id=conv.id,
            role="user",
            content=f"xDR 파일 RCA 분석: {filename}",
        ))
        db.add(Message(
            conversation_id=conv.id,
            role="assistant",
            content=assistant_message,
        ))
        await db.commit()
        await db.refresh(conv)

        response = _analysis_to_response(analysis, conv.id, compact_rca_ir)
        return response
    finally:
        del records, analysis, compact_rca_ir, assistant_message, response
        gc.collect()
        logger.debug("rca memory after_cleanup rss_mb=%.1f", _rss_mb())


@router.post("/analyze")
async def analyze_xdr(
    file: UploadFile = File(...),
    model: str = Form(RCA_MODEL),
    loop_mode: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    """
    xDR .dat 파일 업로드 → 파싱 → 분석 → 결과 반환.
    일반 채팅과 동일한 Conversation을 생성하고 RCA 요약 메시지만 추가한다.
    """
    if not file.filename or not file.filename.lower().endswith(".dat"):
        raise HTTPException(status_code=422, detail="xDR .dat 파일만 지원합니다")

    tmp_path = ""
    try:
        # 임시 파일 저장
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as tmp:
            tmp_path = tmp.name
            total_size = 0
            while True:
                chunk = await file.read(8 * 1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > RCA_MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="파일 크기 제한(500MB) 초과")
                tmp.write(chunk)
        return await _analyze_file_path(tmp_path, file.filename, model or RCA_MODEL, db, loop_mode)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"파일 저장/분석 실패: {exc}") from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


async def _import_rca_inputs_from_path(
    *,
    filepath: str,
    filename: str,
    chunk_size: int,
    input_name: str | None,
    priority: int,
    model: str,
    db: AsyncSession,
) -> dict[str, Any]:
    if chunk_size <= 0:
        raise HTTPException(status_code=422, detail="chunk_size는 1 이상이어야 합니다")

    records = analysis = compact_rca_ir = None
    created_ids: list[int] = []
    existing_ids: list[int] = []
    try:
        records, parse_stats = await asyncio.to_thread(parse_file, filepath)
        parsed = int(parse_stats.get("parsed") or 0)
        if parsed <= 0:
            raise HTTPException(status_code=422, detail="파싱 가능한 레코드가 없습니다")

        for chunk_index, start in enumerate(range(0, parsed, chunk_size), start=1):
            current_size = min(chunk_size, parsed - start)
            chunk_records = records.slice(start, current_size)
            chunk_stats = {
                **parse_stats,
                "parsed": current_size,
                "raw_rows": current_size,
                "chunk_index": chunk_index,
                "chunk_start": start,
                "chunk_size": current_size,
            }
            analysis = await asyncio.to_thread(analyze, chunk_records, chunk_stats)
            compact_rca_ir = build_compact_rca_ir(analysis)
            input_text = _ir_to_markdown(compact_rca_ir)
            chunk_name = input_name or filename
            row, created = await _get_or_create_rca_input(
                db,
                input_name=f"{chunk_name} #{chunk_index:04d}",
                text=input_text,
                priority=priority,
            )
            if created:
                created_ids.append(row.input_id)
            else:
                existing_ids.append(row.input_id)

        await db.commit()
        return {
            "success": True,
            "created_count": len(created_ids),
            "existing_count": len(existing_ids),
            "input_ids": created_ids,
            "existing_input_ids": existing_ids,
            "total_records": parsed,
            "chunk_size": chunk_size,
        }
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"RCA input import 실패: {exc}") from exc
    finally:
        del records, analysis, compact_rca_ir
        gc.collect()


@router.post("/input/import")
async def import_rca_input(
    file: UploadFile = File(...),
    chunk_size: int = Form(10000),
    input_name: str | None = Form(None),
    priority: int = Form(0),
    model: str = Form(RCA_MODEL),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.lower().endswith(".dat"):
        raise HTTPException(status_code=422, detail="xDR .dat 파일만 지원합니다")

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as tmp:
            tmp_path = tmp.name
            total_size = 0
            while True:
                chunk = await file.read(8 * 1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > RCA_MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="파일 크기 제한(500MB) 초과")
                tmp.write(chunk)
        return await _import_rca_inputs_from_path(
            filepath=tmp_path,
            filename=file.filename,
            chunk_size=chunk_size,
            input_name=input_name,
            priority=priority,
            model=model or RCA_MODEL,
            db=db,
        )
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


@router.post("/input/import/sample")
async def import_sample_rca_input(
    chunk_size: int = Form(10000),
    input_name: str | None = Form(None),
    priority: int = Form(0),
    model: str = Form(RCA_MODEL),
    db: AsyncSession = Depends(get_db),
):
    sample_file_path = _sample_file_path()
    if not sample_file_path.exists():
        raise HTTPException(status_code=404, detail="sample file not found")
    return await _import_rca_inputs_from_path(
        filepath=str(sample_file_path),
        filename=sample_file_path.name,
        chunk_size=chunk_size,
        input_name=input_name,
        priority=priority,
        model=model or RCA_MODEL,
        db=db,
    )


@router.post("/prompt", response_model=RcaPromptResponse)
async def create_rca_prompt(
    payload: RcaPromptCreate,
    db: AsyncSession = Depends(get_db),
):
    prompt_text = payload.text.strip()
    if not prompt_text:
        raise HTTPException(status_code=422, detail="Prompt text가 비어 있습니다")
    prompt, _created = await _get_or_create_rca_prompt(
        db,
        text=prompt_text,
        priority=payload.priority,
    )
    await db.commit()
    await db.refresh(prompt)
    return prompt


@router.post("/run/normal", response_model=RcaRunNormalResponse)
async def run_normal_rca_experiment(
    payload: RcaRunNormalRequest,
    db: AsyncSession = Depends(get_db),
):
    rca_input = await db.scalar(select(RcaInput).where(RcaInput.input_id == payload.input_id))
    if not rca_input:
        raise HTTPException(status_code=404, detail="RCA input을 찾을 수 없습니다")
    rca_prompt = await db.scalar(select(RcaPrompt).where(RcaPrompt.prompt_id == payload.prompt_id))
    if not rca_prompt:
        raise HTTPException(status_code=404, detail="RCA prompt를 찾을 수 없습니다")

    run = RcaRun(run_mode="NORMAL")
    db.add(run)
    await db.flush()
    step = RcaStep(
        step_type="NORMAL",
        run_id=run.run_id,
        input_id=rca_input.input_id,
        prompt_id=rca_prompt.prompt_id,
        priority=payload.priority,
    )
    db.add(step)
    await db.flush()

    messages = [
        {"role": "system", "content": rca_prompt.text},
        {"role": "user", "content": rca_input.text},
    ]
    llm_payload = {
        "model": payload.model or RCA_MODEL,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": build_core_options(num_predict=NORMAL_RUN_NUM_PREDICT),
    }

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json=llm_payload,
            )
            response.raise_for_status()
            result_text = _extract_chat_content(response.json())
        if not result_text.strip():
            raise HTTPException(status_code=502, detail="LLM 응답이 비어 있습니다")

        result_row = RcaResult(text=result_text, priority=payload.priority)
        db.add(result_row)
        await db.flush()
        step.result_id = result_row.result_id
        await db.commit()
        return RcaRunNormalResponse(
            success=True,
            run_id=run.run_id,
            step_id=step.step_id,
            result_id=result_row.result_id,
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"RCA normal run 실패: {exc}") from exc


@sample_router.post("/sample")
async def analyze_sample_xdr(
    model: str = Form(RCA_MODEL),
    loop_mode: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    sample_file_path = _sample_file_path()
    if not sample_file_path.exists():
        return {"success": False, "message": "sample file not found"}
    return await _analyze_file_path(str(sample_file_path), sample_file_path.name, model or RCA_MODEL, db, loop_mode)


@router.get("/conversations/{conv_id}/report")
async def stream_rca_report(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    저장된 RCA 컨텍스트(system_prompt)를 기반으로 Ollama LLM 보고서를 SSE 스트리밍.
    """
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")
    if not conv.system_prompt:
        raise HTTPException(status_code=422, detail="RCA 컨텍스트가 없습니다")

    try:
        context = json.loads(conv.system_prompt)
    except Exception:
        raise HTTPException(status_code=422, detail="RCA 컨텍스트 파싱 실패")

    # reasoning이 이미 있으면 report 렌더링 경로, 없으면 일반 RCA 판단 경로
    rca_reasoning = context.get("rca_reasoning") if isinstance(context, dict) else None
    compact_rca_ir = context.get("compact_rca_ir", context) if isinstance(context, dict) else context

    if rca_reasoning:
        messages = build_report_prompt_from_reasoning(compact_rca_ir, rca_reasoning)
    else:
        messages = build_rca_messages(context, conv.model or RCA_MODEL)

    input_row, _input_created = await _get_or_create_rca_input(
        db,
        input_name=f"conversation:{conv_id}:report",
        text=messages[-1]["content"],
    )
    prompt_row, _prompt_created = await _get_or_create_rca_prompt(
        db,
        text=messages[0]["content"],
    )
    run_row = RcaRun(
        run_mode="LOOP" if isinstance(context, dict) and context.get("rca_loop_mode") else "NORMAL"
    )
    db.add(run_row)
    await db.flush()
    step_row = RcaStep(
        step_type="REPORT" if rca_reasoning else "NORMAL",
        run_id=run_row.run_id,
        input_id=input_row.input_id,
        prompt_id=prompt_row.prompt_id,
    )
    db.add(step_row)
    await db.commit()
    messages = [
        {"role": "system", "content": prompt_row.text},
        {"role": "user", "content": input_row.text},
    ]

    logger.debug("rca report prompt chars=%s", sum(len(m["content"]) for m in messages))

    async def generate():
        response_parts: list[str] = []
        llm_call_index = 0
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                llm_payload = {
                    "model": conv.model or RCA_MODEL,
                    "messages": messages,
                    "stream": True,
                    "think": False,
                    "options": build_core_options(num_predict=STEP4_NUM_PREDICT),
                }
                llm_call_index += 1
                yield prompt_debug_event(llm_call_index, "RCA LLM Prompt", llm_payload)
                async with client.stream(
                    "POST",
                    f"{settings.ollama_base_url}/api/chat",
                    json=llm_payload,
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        msg = chunk.get("message", {})
                        content = msg.get("content", "")
                        if content:
                            response_parts.append(content)
                            yield f"data: {json.dumps({'token': content})}\n\n"
                        if chunk.get("done"):
                            break
        except httpx.HTTPError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

        # assistant 메시지 저장
        full_response = "".join(response_parts)
        if full_response.strip():
            result_row = RcaResult(text=full_response)
            db.add(result_row)
            await db.flush()
            step_row.result_id = result_row.result_id
            msg_obj = Message(
                conversation_id=conv_id,
                role="assistant",
                content=full_response,
            )
            db.add(msg_obj)
            await db.commit()

        yield f"data: {json.dumps({'done': True})}\n\n"
        del response_parts, full_response
        gc.collect()

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/conversations/{conv_id}/reasoning")
async def stream_rca_reasoning(
    conv_id: int,
    hallucination_step2: bool = False,
    hallucination_step3: bool = False,
    hallucination_provider: str = "claude",
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="대화를 찾을 수 없습니다")
    if not conv.system_prompt:
        raise HTTPException(status_code=422, detail="RCA 컨텍스트가 없습니다")

    try:
        context = json.loads(conv.system_prompt)
    except Exception:
        raise HTTPException(status_code=422, detail="RCA 컨텍스트 파싱 실패")

    loop_mode = bool(context.get("rca_loop_mode", False)) if isinstance(context, dict) else False
    if isinstance(context, dict) and "compact_rca_ir" in context:
        compact_rca_ir = context["compact_rca_ir"]
    else:
        # Legacy conversations may still have the old full observability payload.
        compact_rca_ir = build_compact_reasoning_json(context if isinstance(context, dict) else {})
    messages = build_rca_messages({"compact_rca_ir": compact_rca_ir}, conv.model or RCA_MODEL)

    async def generate():
        response_parts: list[str] = []
        step_results: list[str] = []
        step2_enrichment_result = ""

        async def run_optional_quality_step(
            client: httpx.AsyncClient,
            step_response: str,
            step_label: str,
            step_index: int,
            step2a_result: str = "",
        ) -> Any:
            if not loop_mode or step_index not in (1, 2):
                yield ("result", step_response)
                return

            if step_index == 1:
                verifier_step_label = "STEP 2-A Observation Enrichment"
                quality_multiplier = STEP2A_NUM_PREDICT_MULTIPLIER
                verifier_messages = build_local_step2_enrichment_messages(
                    compact_rca_ir,
                    step_response,
                    build_fact_ranking_json(compact_rca_ir),
                )
            else:
                verifier_step_label = "STEP 3-A RCA 추론"
                quality_multiplier = STEP3A_NUM_PREDICT_MULTIPLIER
                verifier_messages = build_local_step3_rca_messages(
                    compact_rca_ir,
                    step2a_result or (step_results[1] if len(step_results) > 1 else ""),
                    step_response,
                )

            header = f"\n\n---\n**[{verifier_step_label} 실행 중...]**\n\n"
            response_parts.append(header)
            yield ("sse", f"data: {json.dumps({'token': header})}\n\n")

            verifier_payload = {
                "model": conv.model or RCA_MODEL,
                "messages": verifier_messages,
                "stream": True,
                "think": True,
                "options": build_quality_options(think=True, multiplier=quality_multiplier),
            }
            quality_options = verifier_payload["options"]
            system_prompt = verifier_messages[0].get("content", "") if verifier_messages else ""
            user_prompt = verifier_messages[-1].get("content", "") if verifier_messages else ""
            logger.warning(
                "[QUALITY_REQUEST] step=%s ollama_base_url=%s model=%s stream=%s think=%s options=%s timeout=%s messages=%s system_length=%s user_length=%s user_head=%s user_tail=%s",
                verifier_step_label,
                settings.ollama_base_url,
                verifier_payload["model"],
                verifier_payload["stream"],
                verifier_payload["think"],
                json.dumps(quality_options, ensure_ascii=False),
                QUALITY_STEP_TIMEOUT_SEC,
                len(verifier_messages),
                len(system_prompt),
                len(user_prompt),
                user_prompt[:500],
                user_prompt[-500:],
            )
            yield ("sse", prompt_debug_event(step_index + 20, f"RCA Loop {verifier_step_label}", verifier_payload))

            payload = None
            done_reason = None
            content_length = 0
            thinking_length = 0
            raw_size = 0
            eval_count = None
            total_duration = None
            chunk_count = 0
            first_thinking_elapsed = None
            first_content_elapsed = None
            raw_response_head = ""
            raw_response_tail = ""
            request_started_at = time.monotonic()
            content_parts: list[str] = []
            thinking_preview_parts: list[str] = []

            async def read_quality_stream() -> tuple[str, dict[str, Any], str, str, int, int]:
                nonlocal chunk_count, content_length, thinking_length, raw_size, raw_response_head, raw_response_tail
                nonlocal first_thinking_elapsed, first_content_elapsed
                final_chunk: dict[str, Any] = {}

                async with client.stream(
                    "POST",
                    f"{settings.ollama_base_url}/api/chat",
                    json=verifier_payload,
                ) as verifier_response:
                    verifier_response.raise_for_status()
                    async for line in verifier_response.aiter_lines():
                        if not line:
                            continue
                        raw_line = line + "\n"
                        raw_size += len(raw_line)
                        if len(raw_response_head) < 5000:
                            raw_response_head = (raw_response_head + raw_line)[:5000]
                        raw_response_tail = (raw_response_tail + raw_line)[-5000:]

                        chunk = json.loads(line)
                        chunk_count += 1
                        message = chunk.get("message", {})
                        if isinstance(message, dict):
                            content = message.get("content") or ""
                            thinking = message.get("thinking") or ""
                        else:
                            content = ""
                            thinking = ""
                        content = content or chunk.get("response") or chunk.get("content") or ""
                        thinking = thinking or chunk.get("thinking") or ""
                        if content:
                            content_parts.append(content)
                            content_length += len(content)
                            if first_content_elapsed is None:
                                first_content_elapsed = round(time.monotonic() - request_started_at, 3)
                        if thinking:
                            thinking_length += len(thinking)
                            if first_thinking_elapsed is None:
                                first_thinking_elapsed = round(time.monotonic() - request_started_at, 3)
                            remaining = QUALITY_THINKING_LOG_LIMIT - sum(
                                len(part) for part in thinking_preview_parts
                            )
                            if remaining > 0:
                                thinking_preview_parts.append(thinking[:remaining])
                        if chunk.get("done"):
                            final_chunk = chunk
                        logger.warning(
                            "[QUALITY_STREAM_CHUNK] step=%s chunk_count=%s thinking_length=%s content_length=%s first_thinking_elapsed=%s first_content_elapsed=%s done_reason=%s keys=%s",
                            verifier_step_label,
                            chunk_count,
                            thinking_length,
                            content_length,
                            first_thinking_elapsed,
                            first_content_elapsed,
                            chunk.get("done_reason"),
                            list(chunk.keys()),
                        )
                        if chunk.get("done"):
                            break

                corrected = "".join(content_parts)
                thinking_preview = "".join(thinking_preview_parts)
                stream_payload = {
                    "chunk_count": chunk_count,
                    "final": final_chunk,
                    "content_length": len(corrected),
                    "content_preview": corrected[:2000],
                    "thinking_length": thinking_length,
                    "thinking_preview": thinking_preview,
                    "raw_response_head": raw_response_head,
                    "raw_response_tail": raw_response_tail,
                }
                return (
                    corrected,
                    final_chunk,
                    thinking_preview,
                    json.dumps(stream_payload, ensure_ascii=False),
                    thinking_length,
                    chunk_count,
                )

            try:
                corrected_result, payload, thinking, raw_payload, thinking_length, chunk_count = await asyncio.wait_for(
                    read_quality_stream(),
                    timeout=QUALITY_STEP_TIMEOUT_SEC,
                )
                elapsed_seconds = round(time.monotonic() - request_started_at, 3)
                logger.warning("[QUALITY_RAW_RESPONSE_HEAD] %s", raw_response_head)
                logger.warning("[QUALITY_RAW_RESPONSE_TAIL] %s", raw_response_tail)
                done_reason = payload.get("done_reason")
                eval_count = payload.get("eval_count")
                total_duration = payload.get("total_duration")
                content_length = len(corrected_result)
                logger.warning(
                    "[QUALITY_RESPONSE] step=%s elapsed=%s thinking_length=%s content_length=%s done_reason=%s eval_count=%s total_duration=%s chunk_count=%s first_thinking_elapsed=%s first_content_elapsed=%s",
                    verifier_step_label,
                    elapsed_seconds,
                    thinking_length,
                    content_length,
                    done_reason,
                    eval_count,
                    total_duration,
                    chunk_count,
                    first_thinking_elapsed,
                    first_content_elapsed,
                )
                if not corrected_result.strip():
                    logger.warning(
                        "[QUALITY_EMPTY_RESPONSE] elapsed=%s keys=%s message_keys=%s done_reason=%s content_length=%s thinking_length=%s eval_count=%s total_duration=%s raw_size=%s raw_head=%s raw_tail=%s payload=%s",
                        elapsed_seconds,
                        list(payload.keys()),
                        list(payload.get("message", {}).keys()) if isinstance(payload.get("message"), dict) else None,
                        done_reason,
                        content_length,
                        thinking_length,
                        eval_count,
                        total_duration,
                        raw_size,
                        raw_response_head,
                        raw_response_tail,
                        raw_payload[:2000],
                    )
                    raise ValueError("Verifier 응답이 비어 있습니다")
            except Exception as exc:
                exc_type = type(exc).__name__
                exc_msg = str(exc)
                elapsed_seconds = round(time.monotonic() - request_started_at, 3)
                partial_result = "".join(content_parts)
                if partial_result.strip():
                    content_length = len(partial_result)
                    logger.warning(
                        "%s optional quality step partial result preserved after %s: %s elapsed=%s content_length=%s thinking_length=%s eval_count=%s total_duration=%s chunk_count=%s raw_size=%s raw_head=%s raw_tail=%s",
                        verifier_step_label,
                        exc_type,
                        exc_msg,
                        elapsed_seconds,
                        content_length,
                        thinking_length,
                        eval_count,
                        total_duration,
                        chunk_count,
                        raw_size,
                        raw_response_head,
                        raw_response_tail,
                        exc_info=True,
                    )
                    if isinstance(exc, asyncio.TimeoutError):
                        warning_text = (
                            f"{verifier_step_label} Timeout({QUALITY_STEP_TIMEOUT_SEC}s), "
                            "partial 결과 사용"
                        )
                    else:
                        detail = f"{exc_type}: {exc_msg}"[:300]
                        warning_text = f"{verifier_step_label} 실패({detail}), partial 결과 사용"
                    response_parts.append(f"\n\n*({warning_text})*\n\n")
                    response_parts.append(partial_result)
                    yield ("sse", f"data: {json.dumps({'warning': warning_text})}\n\n")
                    yield ("sse", f"data: {json.dumps({'token': partial_result})}\n\n")
                    yield ("result", partial_result)
                    return
                if payload is not None and raw_size == 0:
                    raw_size = len(json.dumps(payload, ensure_ascii=False))
                logger.warning(
                    "%s optional quality step skipped: %s: %s elapsed=%s done_reason=%s content_length=%s thinking_length=%s eval_count=%s total_duration=%s chunk_count=%s raw_size=%s raw_head=%s raw_tail=%s",
                    verifier_step_label,
                    exc_type,
                    exc_msg,
                    elapsed_seconds,
                    done_reason,
                    content_length,
                    thinking_length,
                    eval_count,
                    total_duration,
                    chunk_count,
                    raw_size,
                    raw_response_head,
                    raw_response_tail,
                    exc_info=True,
                )
                if isinstance(exc, asyncio.TimeoutError):
                    warning_text = (
                        f"{verifier_step_label} Timeout({QUALITY_STEP_TIMEOUT_SEC}s), "
                        f"{step_label} 결과 사용"
                    )
                else:
                    detail = f"{exc_type}: {exc_msg}"[:300]
                    warning_text = f"{verifier_step_label} 실패({detail}), {step_label} 결과 사용"
                response_parts.append(f"\n\n*({warning_text})*\n\n")
                yield ("sse", f"data: {json.dumps({'warning': warning_text})}\n\n")
                yield ("result", step_response)
                return

            response_parts.append(corrected_result)
            yield ("sse", f"data: {json.dumps({'token': corrected_result})}\n\n")
            yield ("result", corrected_result)

        async def run_verifier(step_response: str, step_label: str, step_index: int):
            if hallucination_provider == "gemini":
                from app.rca.gemini_verifier import (
                    GEMINI_VERIFIER_MODEL,
                    GeminiVerifierError,
                    verify_and_correct_step_gemini,
                )
                api_key = settings.google_api_key
                provider_label = "Gemini Verifier"
                verifier_fn = verify_and_correct_step_gemini
                error_class = GeminiVerifierError
                no_key_msg = "GOOGLE_API_KEY 미설정, 원본 결과 사용"
                model_label = GEMINI_VERIFIER_MODEL
            else:
                api_key = settings.anthropic_api_key
                provider_label = "Claude Verifier"
                verifier_fn = verify_and_correct_step
                error_class = ClaudeVerifierError
                no_key_msg = "ANTHROPIC_API_KEY 미설정, 원본 결과 사용"
                model_label = CLAUDE_VERIFIER_MODEL

            verifier_header = f"\n\n---\n**[{provider_label} - {step_label} 보정 중...]**\n\n"
            response_parts.append(verifier_header)
            yield ("sse", f"data: {json.dumps({'token': verifier_header})}\n\n")

            if not api_key:
                warning_text = f"\n\n*({provider_label}: {no_key_msg})*\n\n"
                response_parts.append(warning_text)
                yield ("sse", f"data: {json.dumps({'warning': no_key_msg})}\n\n")
                yield ("result", step_response)
                return

            verifier_call_index = step_index + 10
            verifier_label = f"{provider_label} {step_label}"
            verifier_prompt_text = _build_user_prompt(compact_rca_ir, step_response, step_label)
            verifier_payload = {
                "model": f"{provider_label} ({model_label})",
                "messages": [
                    {"role": "system", "content": CLAUDE_SYSTEM_PROMPT},
                    {"role": "user", "content": verifier_prompt_text},
                ],
            }
            yield ("sse", prompt_debug_event(verifier_call_index, verifier_label, verifier_payload))

            corrected_parts: list[str] = []
            try:
                async for token in verifier_fn(
                    compact_rca_ir=compact_rca_ir,
                    step_result=step_response,
                    step_label=step_label,
                    api_key=api_key,
                ):
                    corrected_parts.append(token)
                    response_parts.append(token)
                    yield ("sse", f"data: {json.dumps({'token': token})}\n\n")
            except Exception as exc:
                logger.error("%s 호출 중 예외 발생: %s", provider_label, exc, exc_info=True)
                warning_text = f"\n\n*({provider_label} 호출 실패: {type(exc).__name__}: {exc})*\n\n"
                response_parts.append(warning_text)
                yield ("sse", f"data: {json.dumps({'warning': f'{provider_label} 호출 실패, 원본 결과 사용'})}\n\n")
                yield ("result", step_response)
                return

            corrected_result = "".join(corrected_parts)
            yield ("result", corrected_result if corrected_result.strip() else step_response)

        async with httpx.AsyncClient(timeout=300.0) as client:
            loop_step_labels = ["STEP 1", "STEP 2", "STEP 3", "STEP 4"]
            total_steps = len(loop_step_labels) if loop_mode else 1
            for step_index in range(total_steps):
                call_messages = (
                    build_loop_reasoning_steps(compact_rca_ir, step_results)
                    if loop_mode
                    else messages
                )
                logical_step = loop_step_labels[step_index] if loop_mode else ""
                label = f"RCA Loop {logical_step}" if loop_mode else "RCA LLM Prompt"
                if loop_mode:
                    try:
                        marker_text = f"[{logical_step} 입력]\n"
                        step_input = json.loads(call_messages[1]["content"].split(marker_text, 1)[1])
                        logger.debug(
                            "rca loop %s input payload=%s",
                            logical_step,
                            json.dumps(step_input, ensure_ascii=False),
                        )
                    except Exception:
                        logger.debug("rca loop %s input payload parse failed", logical_step)
                if loop_mode:
                    marker = f"\n{logical_step} 결과\n"
                    response_parts.append(marker)
                    yield f"data: {json.dumps({'token': marker})}\n\n"

                step_response_parts: list[str] = []
                if loop_mode and step_index == 2:
                    ranking_json = build_fact_ranking_json(compact_rca_ir)
                    step_response = build_fact_ranking_text(ranking_json)
                    response_parts.append(step_response)
                    step_response_parts.append(step_response)
                    yield prompt_debug_event(
                        step_index + 1,
                        f"{label} (Code Ranking)",
                        {
                            "source": "deterministic",
                            "output": json.loads(ranking_json),
                            "display": step_response,
                        },
                    )
                    yield f"data: {json.dumps({'token': step_response})}\n\n"
                else:
                    core_num_predict = (
                        STEP4_NUM_PREDICT if loop_mode and step_index == 3
                        else BASE_NUM_PREDICT if loop_mode
                        else NORMAL_RUN_NUM_PREDICT
                    )
                    llm_payload = {
                        "model": conv.model or RCA_MODEL,
                        "messages": call_messages,
                        "stream": True,
                        "think": False,
                        "options": build_core_options(num_predict=core_num_predict),
                    }
                    yield prompt_debug_event(step_index + 1, label, llm_payload)
                    try:
                        async with client.stream(
                            "POST",
                            f"{settings.ollama_base_url}/api/chat",
                            json=llm_payload,
                        ) as response:
                            response.raise_for_status()
                            async for line in response.aiter_lines():
                                if not line:
                                    continue
                                chunk = json.loads(line)
                                content = chunk.get("message", {}).get("content", "")
                                if content:
                                    response_parts.append(content)
                                    step_response_parts.append(content)
                                    yield f"data: {json.dumps({'token': content})}\n\n"
                                if chunk.get("done"):
                                    break
                    except Exception as exc:
                        logger.error("rca loop %s core step failed: %s", logical_step or "RCA", exc, exc_info=True)
                        fallback_response = (
                            f"[{logical_step or 'RCA'} 생성 실패: {type(exc).__name__}: {exc}]\n"
                            "이 단계는 실패했지만 RCA 파이프라인은 중단하지 않고 다음 단계로 진행합니다."
                        )
                        response_parts.append(fallback_response)
                        step_response_parts.append(fallback_response)
                        failed_step_label = logical_step or "RCA"
                        yield f"data: {json.dumps({'warning': f'{failed_step_label} 실패, 다음 단계 진행'})}\n\n"
                        yield f"data: {json.dumps({'token': fallback_response})}\n\n"
                    step_response = "".join(step_response_parts)

                if loop_mode:
                    step_key = f"step{step_index + 1}"
                    violations = find_forbidden_terms(step_key, step_response)
                    if violations:
                        logger.warning(
                            "rca loop %s forbidden terms detected: %s",
                            logical_step, violations,
                        )
                        retry_notice = f"\n*[{logical_step} 금지 표현 감지({', '.join(violations)}) — 재시도 중...]*\n\n"
                        response_parts.append(retry_notice)
                        yield f"data: {json.dumps({'token': retry_notice})}\n\n"

                        retry_messages = call_messages + [
                            {"role": "assistant", "content": step_response},
                            {"role": "user", "content": build_retry_instruction(violations)},
                        ]
                        retry_payload = {
                            "model": conv.model or RCA_MODEL,
                            "messages": retry_messages,
                            "stream": True,
                            "think": False,
                            "options": build_core_options(num_predict=core_num_predict),
                        }
                        yield prompt_debug_event(step_index + 1, f"{label} (Retry)", retry_payload)
                        retry_parts: list[str] = []
                        try:
                            async with client.stream(
                                "POST",
                                f"{settings.ollama_base_url}/api/chat",
                                json=retry_payload,
                            ) as retry_response:
                                retry_response.raise_for_status()
                                async for line in retry_response.aiter_lines():
                                    if not line:
                                        continue
                                    chunk = json.loads(line)
                                    content = chunk.get("message", {}).get("content", "")
                                    if content:
                                        response_parts.append(content)
                                        retry_parts.append(content)
                                        yield f"data: {json.dumps({'token': content})}\n\n"
                                    if chunk.get("done"):
                                        break
                        except Exception as exc:
                            logger.warning("rca loop %s forbidden retry failed: %s", logical_step, exc, exc_info=True)
                            yield f"data: {json.dumps({'warning': f'{logical_step} 재시도 실패, 원본 결과 사용'})}\n\n"
                        retried_response = "".join(retry_parts)
                        if retried_response.strip():
                            remaining = find_forbidden_terms(step_key, retried_response)
                            if remaining:
                                logger.warning(
                                    "rca loop %s forbidden terms persist after retry: %s",
                                    logical_step, remaining,
                                )
                            step_response = retried_response
                        del retry_parts, retried_response

                if loop_mode and step_index == 1:
                    enriched_result = None
                    async for event_type, verifier_event in run_optional_quality_step(
                        client,
                        step_response,
                        logical_step,
                        step_index,
                    ):
                        if event_type == "sse":
                            yield verifier_event
                        elif event_type == "result":
                            enriched_result = verifier_event
                    step2_enrichment_result = enriched_result or step_response

                    if hallucination_step2:
                        verified_enrichment = None
                        async for event_type, verifier_event in run_verifier(
                            step2_enrichment_result,
                            "STEP 2-A",
                            step_index,
                        ):
                            if event_type == "sse":
                                yield verifier_event
                            elif event_type == "result":
                                verified_enrichment = verifier_event
                        if verified_enrichment is not None:
                            step2_enrichment_result = verified_enrichment

                if loop_mode and step_index == 2:
                    corrected_result = None
                    async for event_type, verifier_event in run_optional_quality_step(
                        client,
                        step_response,
                        logical_step,
                        step_index,
                        step2_enrichment_result,
                    ):
                        if event_type == "sse":
                            yield verifier_event
                        elif event_type == "result":
                            corrected_result = verifier_event
                    if corrected_result is not None:
                        step_response = corrected_result

                step_results.append(step_response)
                should_verify_step3 = loop_mode and step_index == 2 and hallucination_step3
                if should_verify_step3:
                    corrected_result = None
                    async for event_type, verifier_event in run_verifier(step_response, logical_step, step_index):
                        if event_type == "sse":
                            yield verifier_event
                        elif event_type == "result":
                            corrected_result = verifier_event
                    if corrected_result is not None:
                        step_results[-1] = corrected_result
                if loop_mode and step_index < total_steps - 1:
                    # STEP 완료 이벤트 — 프론트에서 현재 streamingContent를 messages에 flush
                    yield f"data: {json.dumps({'step_done': True, 'step_index': step_index})}\n\n"
                    separator = "\n\n"
                    response_parts.append(separator)
                    yield f"data: {json.dumps({'token': separator})}\n\n"
                del step_response_parts, step_response

        full_response = "".join(response_parts)
        if full_response.strip():
            conv.system_prompt = json.dumps({
                "compact_rca_ir": compact_rca_ir,
                "rca_loop_mode": loop_mode,
                "rca_reasoning_steps": step_results if loop_mode else [],
                "rca_reasoning": step_results[-1] if loop_mode and step_results else full_response,
            }, ensure_ascii=False)
            db.add(Message(conversation_id=conv_id, role="assistant", content=full_response))
            await db.commit()

        yield f"data: {json.dumps({'done': True})}\n\n"
        del response_parts, step_results, full_response
        gc.collect()

    return StreamingResponse(generate(), media_type="text/event-stream")
