from __future__ import annotations

import json
from typing import Any


def format_final_prompt(payload: dict[str, Any]) -> str:
    """Return the exact LLM request payload without transport/auth details."""
    return json.dumps(payload, ensure_ascii=False, indent=2)


def prompt_debug_event(call_index: int, label: str, payload: dict[str, Any]) -> str:
    final_prompt = format_final_prompt(payload)
    data = {
        "prompt_debug": {
            "call_index": call_index,
            "label": label,
            "final_prompt": final_prompt,
            "estimated_tokens": max(1, len(final_prompt) // 4),
        }
    }
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
