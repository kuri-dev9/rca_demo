"""
Gemini verifier for RCA loop reasoning.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

from app.rca.claude_verifier import CLAUDE_SYSTEM_PROMPT as SYSTEM_PROMPT, _build_user_prompt

GEMINI_VERIFIER_MODEL = "gemini-2.0-flash"


class GeminiVerifierError(Exception):
    """Raised when Gemini verification cannot produce corrected text."""


async def verify_and_correct_step_gemini(
    compact_rca_ir: dict,
    step_result: str,
    step_label: str,
    api_key: str,
) -> AsyncGenerator[str, None]:
    """
    gemma4 생성 결과를 Gemini API로 검증·보정하고 보정 텍스트를 스트리밍한다.
    """
    if not api_key:
        yield step_result
        return

    user_prompt = _build_user_prompt(compact_rca_ir, step_result, step_label)

    def _collect_tokens() -> list[str]:
        try:
            from google import genai
            from google.genai import types
        except Exception as exc:
            raise GeminiVerifierError("google-genai 패키지를 불러올 수 없습니다") from exc

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content_stream(
            model=GEMINI_VERIFIER_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=1200,
            ),
        )
        tokens = []
        for chunk in response:
            if chunk.text:
                tokens.append(chunk.text)
        return tokens

    try:
        tokens = await asyncio.to_thread(_collect_tokens)
    except GeminiVerifierError:
        raise
    except Exception as exc:
        raise GeminiVerifierError("Gemini verifier 호출 실패") from exc

    if not tokens:
        raise GeminiVerifierError("Gemini verifier 응답이 비어 있습니다")

    for token in tokens:
        yield token
