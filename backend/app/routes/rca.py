"""
routes/rca.py
RCA 분석 라우터.
POST /api/rca/analyze     — xDR 파일 업로드 → 분석 → 결과 반환
GET  /api/rca/conversations/{conv_id}/report  — SSE LLM 보고서 스트리밍
"""
from __future__ import annotations

import asyncio
import gc
import json
import logging
import os
import resource
import tempfile
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.database import get_db
from app.models import Conversation, Message
from app.llm_debug import prompt_debug_event
from app.rca.analyzer import RcaAnalysis, analyze
from app.rca.claude_verifier import (
    CLAUDE_SYSTEM_PROMPT,
    CLAUDE_VERIFIER_MODEL,
    ClaudeVerifierError,
    _build_user_prompt,
    verify_and_correct_step,
)
from app.rca.parser import parse_file
from app.rca.spec_loader import get_call_type_name
from app.rca.report_builder import (
    build_compact_rca_ir,
    build_compact_reasoning_json,
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
_SAMPLE_FILE_CANDIDATES = [
    Path(os.environ["PROJ_HOME"]) / "docs" / "data" / "sample.dat"
    if os.environ.get("PROJ_HOME")
    else None,
    Path.cwd() / "docs" / "data" / "sample.dat",
    Path(__file__).resolve().parents[2] / "docs" / "data" / "sample.dat",
    Path(__file__).resolve().parents[3] / "docs" / "data" / "sample.dat",
]


def _sample_file_path() -> Path:
    for path in _SAMPLE_FILE_CANDIDATES:
        if path and path.exists():
            return path
    return Path.cwd() / "docs" / "data" / "sample.dat"


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

    # 임시 파일 저장
    with tempfile.NamedTemporaryFile(suffix=".dat", delete=False) as tmp:
        tmp_path = tmp.name
        total_size = 0
        try:
            while True:
                chunk = await file.read(8 * 1024 * 1024)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > RCA_MAX_FILE_BYTES:
                    raise HTTPException(status_code=413, detail="파일 크기 제한(500MB) 초과")
                tmp.write(chunk)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"파일 저장 실패: {exc}") from exc

    try:
        return await _analyze_file_path(tmp_path, file.filename, model or RCA_MODEL, db, loop_mode)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


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

    logger.debug("rca report prompt chars=%s", sum(len(m["content"]) for m in messages))

    async def generate():
        response_parts: list[str] = []
        llm_call_index = 0
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                llm_payload = {"model": conv.model or RCA_MODEL, "messages": messages, "stream": True}
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

        try:
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
                    llm_payload = {"model": conv.model or RCA_MODEL, "messages": call_messages, "stream": True, "options": {"repeat_penalty": 1.3, "repeat_last_n": 256}}
                    yield prompt_debug_event(step_index + 1, label, llm_payload)
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
                    step_response = "".join(step_response_parts)
                    step_results.append(step_response)
                    should_verify_step2 = loop_mode and step_index == 1 and hallucination_step2
                    should_verify_step3 = loop_mode and step_index == 2 and hallucination_step3
                    if should_verify_step2 or should_verify_step3:
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
        except httpx.HTTPError as exc:
            step_label = loop_step_labels[step_index] if loop_mode else "RCA"
            yield f"data: {json.dumps({'error': f'[{step_label}] {str(exc)}'})}\n\n"
            return

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
