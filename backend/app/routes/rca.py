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
from collections import Counter
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
from app.rca.parser import parse_file
from app.rca.report_builder import (
    build_compact_rca_ir,
    build_compact_reasoning_json,
    build_semantic_summary,
    build_rca_messages,
    build_reasoning_messages,
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


def _analysis_to_markdown(analysis: RcaAnalysis) -> str:
    """RCA Observability Summary — 표(table) 형식."""
    burst_val = (analysis.burst_window or "감지됨") if analysis.burst_detected else "없음"
    lines = [
        "## RCA Observability Summary",
        " ",
        "### 통계",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 총 레코드 | {analysis.total_records:,}건 |",
        f"| 시도 | {analysis.attempt_count:,}건 |",
        f"| 성공 | {analysis.success_count:,}건 |",
        f"| 실패 | {analysis.failure_count:,}건 |",
        f"| 실패율 | {analysis.failure_rate:.2f}% |",
        f"| 영향 가입자 | {len(analysis.affected_imsi_set):,}명 |",
        f"| Burst 감지 | {burst_val} |",
    ]

    # Interface Failure 분포
    if analysis.interface_distribution:
        lines += [
            " ",
            "### Interface Failure 분포",
            "| Interface | 건수 |",
            "|---|---|",
        ]
        for iface, cnt in sorted(analysis.interface_distribution.items(), key=lambda x: x[1], reverse=True)[:8]:
            lines.append(f"| {iface} | {cnt:,} |")

    # Failure Stage 분포
    stage_hist: Counter[str] = Counter(c.failure_point for c in analysis.failure_chains)
    if stage_hist:
        lines += [
            " ",
            "### Failure Stage 분포",
            "| Stage | 건수 |",
            "|---|---|",
        ]
        for stage, cnt in stage_hist.most_common(8):
            lines.append(f"| {stage} | {cnt:,} |")

    # MME Baseline
    if analysis.mme_baseline:
        lines += [
            " ",
            "### MME",
            "| MME | 시도 | 성공 | 실패 | 실패율 | Anomaly Ratio |",
            "|---|---|---|---|---|---|",
        ]
        for m in analysis.mme_baseline[:10]:
            lines.append(
                f"| {m['mme_id']} | {m['attempts']:,} | {m['success']:,} "
                f"| {m['failures']:,} | {m['failure_rate']}% | {m['anomaly_ratio']} |"
            )

    # eNB Baseline
    if analysis.enb_baseline:
        lines += [
            " ",
            "### eNB",
            "| eNB | 시도 | 성공 | 실패 | 실패율 | Anomaly Ratio |",
            "|---|---|---|---|---|---|",
        ]
        for e in analysis.enb_baseline[:10]:
            lines.append(
                f"| {e['enb_id']} | {e['attempts']:,} | {e['success']:,} "
                f"| {e['failures']:,} | {e['failure_rate']}% | {e['anomaly_ratio']} |"
            )

    # Representative Failure Chains (중복 제거, top 5)
    seen: set[str] = set()
    rep_chains = []
    for c in analysis.failure_chains:
        key = " → ".join(c.chain)
        if key not in seen:
            seen.add(key)
            rep_chains.append(c)
        if len(rep_chains) >= 5:
            break
    if rep_chains:
        lines += ["", "### 단말 실패 체인"]
        for i, c in enumerate(rep_chains, 1):
            lines += [
                " ",
                f"**IMSI[{i}]: `{c.imsi}`**",
                f"- Procedure: `{c.procedure}`",
                f"- Interface: `{c.failure_interface}`",
                f"- Failure Point: `{c.failure_point}`",
                f"- Cause: `{c.failure_cause_name}`",
                f"- Flow: {' → '.join(c.chain)}",
            ]

    # Shared Failure Observations
    if analysis.shared_failure_signatures:
        lines += [
            " ",
            "### 유형별 실패 통계",
            "| Interface | Stage | Cause | Count | IMSI | MME | eNB |",
            "|---|---|---|---|---|---|---|",
        ]
        for s in analysis.shared_failure_signatures[:8]:
            lines.append(
                f"| {s['interface']} | {s['stage']} | {s['cause']} "
                f"| {s['count']} | {s['affected_imsi_count']} "
                f"| {s['affected_mme_count']} | {s['affected_enb_count']} |"
            )

    return "\n".join(lines)


def _analysis_to_response(analysis: RcaAnalysis, conv_id: int) -> dict[str, Any]:
    """RcaAnalysis → JSON-serializable response dict."""
    chains_raw = []
    for c in analysis.failure_chains[:20]:
        chains_raw.append({
            "procedure": c.procedure,
            "call_type": c.call_type,
            "failure_point": c.failure_point,
            "failure_interface": c.failure_interface,
            "failure_message": c.failure_message,
            "failure_cause": c.failure_cause,
            "failure_cause_name": c.failure_cause_name,
            "failure_semantic": c.failure_semantic,
            "chain": c.chain,
        })

    assistant_message = _analysis_to_markdown(analysis)

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


def _parse_reasoning_json(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        return json.loads(cleaned)
    except Exception:
        return cleaned


async def _analyze_file_path(
    filepath: str,
    filename: str,
    model: str,
    db: AsyncSession,
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
        conv = Conversation(
            title=f"RCA: {filename}",
            model=model or RCA_MODEL,
            system_prompt=json.dumps({"compact_rca_ir": compact_rca_ir}, ensure_ascii=False),
        )
        db.add(conv)
        await db.flush()

        assistant_message = _analysis_to_markdown(analysis)
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

        response = _analysis_to_response(analysis, conv.id)
        return response
    finally:
        del records, analysis, compact_rca_ir, assistant_message, response
        gc.collect()
        logger.debug("rca memory after_cleanup rss_mb=%.1f", _rss_mb())


@router.post("/analyze")
async def analyze_xdr(
    file: UploadFile = File(...),
    model: str = Form(RCA_MODEL),
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
        return await _analyze_file_path(tmp_path, file.filename, model or RCA_MODEL, db)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


@sample_router.post("/sample")
async def analyze_sample_xdr(
    model: str = Form(RCA_MODEL),
    db: AsyncSession = Depends(get_db),
):
    sample_file_path = _sample_file_path()
    if not sample_file_path.exists():
        return {"success": False, "message": "sample file not found"}
    return await _analyze_file_path(str(sample_file_path), sample_file_path.name, model or RCA_MODEL, db)


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

    messages = build_rca_messages(context)
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

    if isinstance(context, dict) and "compact_rca_ir" in context:
        compact_rca_ir = context["compact_rca_ir"]
    else:
        # Legacy conversations may still have the old full observability payload.
        compact_rca_ir = build_compact_reasoning_json(context if isinstance(context, dict) else {})
    messages = build_reasoning_messages(compact_rca_ir)

    async def generate():
        response_parts: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                llm_payload = {"model": conv.model or RCA_MODEL, "messages": messages, "stream": True}
                yield prompt_debug_event(1, "RCA Reasoning Prompt", llm_payload)
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
                            yield f"data: {json.dumps({'token': content})}\n\n"
                        if chunk.get("done"):
                            break
        except httpx.HTTPError as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            return

        full_response = "".join(response_parts)
        if full_response.strip():
            conv.system_prompt = json.dumps({
                "compact_rca_ir": compact_rca_ir,
                "rca_reasoning": full_response,
            }, ensure_ascii=False)
            db.add(Message(conversation_id=conv_id, role="assistant", content=full_response))
            await db.commit()

        yield f"data: {json.dumps({'done': True})}\n\n"
        del response_parts, full_response
        gc.collect()

    return StreamingResponse(generate(), media_type="text/event-stream")
