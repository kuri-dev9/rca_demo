"""
Claude verifier for RCA loop reasoning.
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any


CLAUDE_VERIFIER_MODEL = "claude-sonnet-4-6"
CLAUDE_SYSTEM_PROMPT = """당신은 LTE/EPC 네트워크 장애 분석 결과의 사실 검증 및 보정 전문가입니다.
3GPP TS 23.401, 24.301, 29.272, 29.274 기반으로 판단합니다.

역할:
- 아래 [입력 데이터]에 근거가 있는 주장만 유지합니다.
- 입력 데이터에 없는 값을 생성하거나 추론한 주장은 제거하거나 "추가 확인 필요"로 완화합니다.
- 3GPP 절차 상 틀린 해석이 있으면 올바르게 수정합니다.
- Interface / Message / Cause 이름은 변경하지 않습니다.
- 반드시 한국어로 작성합니다.
- 원문의 구조(문단 순서, 항목 분류)를 최대한 유지하면서 보정합니다.
- 보정한 항목은 문장 뒤에 [보정됨] 태그를 붙입니다.
- 보정 없이 유지한 항목은 그대로 출력합니다.
"""


class ClaudeVerifierError(Exception):
    """Raised when Claude verification cannot produce corrected text."""


def _extract_llm_fields(compact_rca_ir: dict[str, Any]) -> dict[str, Any]:
    """Return only top-level compact RCA IR sections explicitly marked llm=True."""
    llm_payload: dict[str, Any] = {}
    for key, value in compact_rca_ir.items():
        if isinstance(value, dict) and value.get("llm") is True:
            llm_payload[key] = value.get("data")
    return llm_payload


def _build_user_prompt(compact_rca_ir: dict[str, Any], step_result: str, step_label: str) -> str:
    llm_payload = _extract_llm_fields(compact_rca_ir)
    input_json = json.dumps(llm_payload, ensure_ascii=False, indent=2)
    return f"""[입력 데이터]
{input_json}

[검증 및 보정 대상 - {step_label} 결과]
{step_result}

위 [검증 및 보정 대상]을 [입력 데이터] 기반으로 검증하고 보정된 전체 텍스트를 출력하세요.
보정된 항목에는 [보정됨] 태그를 붙이세요.
"""


async def verify_and_correct_step(
    compact_rca_ir: dict,
    step_result: str,
    step_label: str,
    api_key: str,
) -> AsyncGenerator[str, None]:
    """
    gemma4 생성 결과를 Claude API로 검증·보정하고 보정 텍스트를 스트리밍한다.
    """
    if not api_key:
        yield step_result
        return

    try:
        from anthropic import AsyncAnthropic
    except Exception as exc:
        raise ClaudeVerifierError("anthropic 패키지를 불러올 수 없습니다") from exc

    client = AsyncAnthropic(api_key=api_key, timeout=120.0)
    user_prompt = _build_user_prompt(compact_rca_ir, step_result, step_label)
    emitted = False

    try:
        async with client.messages.stream(
            model=CLAUDE_VERIFIER_MODEL,
            max_tokens=4096,
            system=CLAUDE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        ) as stream:
            async for text in stream.text_stream:
                if text:
                    emitted = True
                    yield text
    except Exception as exc:
        raise ClaudeVerifierError("Claude verifier 호출 실패") from exc

    if not emitted:
        raise ClaudeVerifierError("Claude verifier 응답이 비어 있습니다")
