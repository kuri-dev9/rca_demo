"""
report_builder.py
LLM 전달용 semantic observation summary 생성.

backend 역할: 숫자 코드 → 의미 번역, 통계 집계, 대표 패턴 추출.
RCA 판단, 원인 확정, 조치 확정은 LLM이 수행.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app.rca.analyzer import RcaAnalysis


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _critical_enb(enb_baseline: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[float, float]:
        return (_num(row.get("failures")), _num(row.get("failure_rate")))

    out = []
    for row in sorted(enb_baseline, key=sort_key, reverse=True)[:limit]:
        out.append({
            "enb_id": row.get("enb_id"),
            "attempts": row.get("attempts"),
            "success": row.get("success"),
            "failures": row.get("failures"),
            "failure_rate": row.get("failure_rate"),
        })
    return out


def _imsi_behavior_summary(observability: dict[str, Any]) -> list[dict[str, Any]]:
    stats_by_imsi = {
        row.get("imsi_prefix"): row
        for row in observability.get("top_failed_imsi", [])
        if row.get("imsi_prefix")
    }

    summary = []
    for item in observability.get("imsi_timelines", []):
        imsi_prefix = item.get("imsi_prefix", "")
        stats = stats_by_imsi.get(imsi_prefix, {})
        stages: set[str] = set()
        causes: set[str] = set()
        enbs: set[str] = set()
        mmes: set[str] = set()
        failure_events = 0

        for event in item.get("timeline", []):
            if event.get("type") != "FAILURE":
                continue
            failure_events += 1
            if event.get("stage"):
                stages.add(str(event["stage"]))
            if event.get("cause"):
                causes.add(str(event["cause"]))
            if event.get("enb"):
                enbs.add(str(event["enb"]))
            if event.get("mme"):
                mmes.add(str(event["mme"]))

        summary.append({
            "imsi_prefix": imsi_prefix,
            "failure_count": stats.get("failures", failure_events),
            "success_count": stats.get("success", 0),
            "same_cause": len(causes) == 1 if failure_events else False,
            "same_stage": len(stages) == 1 if failure_events else False,
            "multi_enb": len(enbs) > 1,
            "multi_mme": len(mmes) > 1,
        })
    return summary


def _subscriber_failure_patterns_from_sequences(sequences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    patterns = []
    for seq in sequences:
        attempts = int(seq.get("attempts") or 0)
        failures = int(seq.get("failures") or 0)
        patterns.append({
            "imsi_prefix": seq.get("imsi", ""),
            "attempts": attempts,
            "failures": failures,
            "imsi_failure_rate": float(seq.get("imsi_failure_rate") or 0.0),
            "total_failure_share": float(seq.get("total_failure_share") or 0.0),
            "zero_success": int(seq.get("success") or 0) == 0,
            "stage": seq.get("stage", ""),
            "cause": seq.get("cause", ""),
            "mme_count": int(seq.get("mme_count") or 0),
            "enb_count": int(seq.get("enb_count") or 0),
        })
    return patterns


def _build_subscriber_summary(
    compact_patterns: list[dict[str, Any]],
    mobility_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    summary = mobility_summary or {}
    affected = int(summary.get("affected_imsi_count") or 0)
    repeated = int(summary.get("repeated_failure_imsi_count") or 0)
    top_failure_share = max(
        (_num(row.get("total_failure_share")) for row in compact_patterns),
        default=0.0,
    )
    return {
        "affected_imsi_count": affected,
        "single_failure_imsi_count": int(summary.get("single_failure_imsi_count") or 0),
        "repeated_failure_imsi_count": repeated,
        "repeated_failure_ratio": round(repeated / affected * 100, 1) if affected else 0.0,
        "multi_mme_imsi_count": int(summary.get("multi_mme_imsi_count") or 0),
        "multi_enb_imsi_count": int(summary.get("multi_enb_imsi_count") or 0),
        "zero_success_imsi_count": int(summary.get("zero_success_imsi_count") or 0),
        "top_imsi_failure_share": round(top_failure_share, 1),
    }


def _compact_shared_failures(rows: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    shared = sorted(rows, key=lambda row: _num(row.get("count")), reverse=True)[:limit]
    return [
        {
            "interface": row.get("interface"),
            "stage": row.get("stage"),
            "cause": row.get("cause"),
            "count": row.get("count"),
            "affected_imsi_count": row.get("affected_imsi_count"),
            "affected_mme_count": row.get("affected_mme_count"),
            "affected_enb_count": row.get("affected_enb_count"),
        }
        for row in shared
    ]


def build_compact_rca_ir(analysis: RcaAnalysis) -> dict[str, Any]:
    """Compact RCA IR used by the LLM reasoning path."""
    stage_counter: Counter[str] = Counter()
    for chain in analysis.failure_chains:
        stage_counter[chain.failure_point] += 1

    rep_chains = []
    seen: set[tuple[str, str, str, str]] = set()
    for chain in analysis.failure_chains:
        item = {
            "procedure": chain.procedure,
            "interface": chain.failure_interface,
            "failure_point": chain.failure_point,
            "cause": chain.failure_cause_name,
        }
        key = (item["procedure"], item["interface"], item["failure_point"], item["cause"])
        if key in seen:
            continue
        seen.add(key)
        rep_chains.append(item)
        if len(rep_chains) >= 10:
            break
    for seq in analysis.top_failed_imsi_sequences:
        attempts = _num(seq.get("attempts"))
        failures = _num(seq.get("failures"))
        seq["imsi_failure_rate"] = round(failures / attempts * 100, 1) if attempts else 0.0
        seq["total_failure_share"] = (
            round(failures / analysis.failure_count * 100, 1)
            if analysis.failure_count else 0.0
        )
    subscriber_patterns = _subscriber_failure_patterns_from_sequences(analysis.top_failed_imsi_sequences)
    return {
        "statistics": {
            "attempt_count": analysis.attempt_count,
            "success_count": analysis.success_count,
            "failure_count": analysis.failure_count,
            "failure_rate": round(analysis.failure_rate, 2),
        },
        "interface_failure_distribution": dict(analysis.interface_distribution),
        "failure_stage_distribution": dict(stage_counter),
        "representative_chains": rep_chains,
        "entity_failure_contribution": {
            "top_mme": analysis.entity_failure_contributions.get("mme", []),
            "top_enb": analysis.entity_failure_contributions.get("enb", []),
            "top_sgw": analysis.entity_failure_contributions.get("sgw", []),
        },
        "shared_failure_observations": _compact_shared_failures(analysis.shared_failure_signatures),
        # Legacy comparison payload. Keep the generation code above for future A/B tests,
        # but do not send per-IMSI rows to the one-shot RCA path.
        # "subscriber_failure_patterns": subscriber_patterns,
        "subscriber_summary": _build_subscriber_summary(
            subscriber_patterns,
            analysis.subscriber_mobility_summary,
        ),
        "burst_detected": bool(analysis.burst_detected),
    }


def build_compact_reasoning_json(observability: dict[str, Any]) -> dict[str, Any]:
    """
    LLM causal reasoning 전용 compact payload.
    Full observability는 보존하되 reasoning 호출에는 raw timeline/긴 chain/APN/timestamp를 전달하지 않는다.
    """
    stats = observability.get("statistics", {})
    rep_chains = []
    for chain in observability.get("representative_chains", [])[:10]:
        rep_chains.append({
            "procedure": chain.get("procedure"),
            "interface": chain.get("interface"),
            "failure_point": chain.get("failure_point"),
            "cause": chain.get("cause"),
        })

    shared = sorted(
        observability.get("shared_failure_observations", []),
        key=lambda row: _num(row.get("count")),
        reverse=True,
    )[:10]
    shared = [
        {
            "interface": row.get("interface"),
            "stage": row.get("stage"),
            "cause": row.get("cause"),
            "count": row.get("count"),
            "affected_imsi_count": row.get("affected_imsi_count"),
            "affected_mme_count": row.get("affected_mme_count"),
            "affected_enb_count": row.get("affected_enb_count"),
        }
        for row in shared
    ]

    burst = observability.get("burst", {})
    mme_baseline = [
        {
            "mme_id": row.get("mme_id"),
            "attempts": row.get("attempts"),
            "success": row.get("success"),
            "failures": row.get("failures"),
            "failure_rate": row.get("failure_rate"),
            "anomaly_ratio": row.get("anomaly_ratio"),
        }
        for row in observability.get("mme_baseline", [])
    ]

    return {
        "statistics": {
            "attempt_count": stats.get("attempt_count"),
            "success_count": stats.get("success_count"),
            "failure_count": stats.get("failure_count"),
            "failure_rate": stats.get("failure_rate"),
        },
        "interface_failure_distribution": observability.get("interface_failure_distribution", {}),
        "failure_stage_distribution": observability.get("failure_stage_distribution", {}),
        "representative_chains": rep_chains,
        "mme_baseline": mme_baseline,
        "critical_enb": _critical_enb(observability.get("enb_baseline", [])),
        "shared_failure_observations": shared,
        "imsi_behavior_summary": _imsi_behavior_summary(observability),
        "burst_detected": bool(burst.get("detected", False)),
    }


def build_reasoning_prompt(observability: dict[str, Any]) -> str:
    ctx_json = json.dumps(observability, ensure_ascii=False, indent=2)
    return f"""\
당신은 LTE/EPC RCA reasoning engine입니다.

목표는 운영 보고서 작성이 아니라 원인 판단입니다.
제공된 데이터만 사용하세요.

수행할 작업:
- network-side / subscriber-side 판단
- 주요 원인 분석
- 반복 failure pattern 분석
- anomaly correlation 분석
- confidence 산출
- 추가 필요 데이터 제시

Subscriber 판단 규칙:
- 개별 IMSI 사례보다 전체 가입자 분포를 우선하세요.
- repeated_failure_ratio가 낮으면 subscriber 집중 현상으로 해석하지 마세요.
- top_imsi_failure_share 단독으로 subscriber-side를 판단하지 마세요.
- affected_imsi_count 대비 repeated_failure_imsi_count 비율을 우선 고려하세요.
- multi_mme_imsi_count, multi_enb_imsi_count는 보조 증거로만 사용하세요.

절대 금지:
- markdown
- HTML
- recommendation
- operator summary
- 입력 데이터에 없는 값 생성

응답 형식:
- 자연스러운 한국어 문장으로만 작성
- 핵심 내용만 간결하게 작성

[Compact RCA IR]
{ctx_json}
"""


def build_reasoning_messages(observability: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "당신은 LTE/EPC RCA 원인 분석 엔진입니다.\n"
                "당신의 역할은 원인 추론(reasoning)만 수행하는 것입니다.\n"
                "레포트를 생성하지 마세요.\n"
                "markdown을 생성하지 마세요.\n"
                "table을 생성하지 마세요.\n"
                "HTML을 생성하지 마세요.\n"
                "반드시 제공된 데이터만 사용하세요.\n"
                "누락된 값을 임의로 생성하지 마세요.\n"
                "APN 관련 결론을 추론하지 마세요.\n"
                "응답은 간결하고 운영 분석 중심으로 작성하세요."
            ),
        },
        {"role": "user", "content": build_reasoning_prompt(observability)},
    ]


STEP_SYSTEM_PROMPT = """
당신의 역할은 RCA 분석가가 아니다.

당신의 역할은 입력 데이터를 정렬하고 관찰 결과를 추출하는 것이다.

중요:
- 입력에 없는 값 생성 금지
- 숫자 계산 금지
- 비율 계산 금지
- 원인 추론 금지
- 의미 해석 금지
- Cause 이름 변경 금지
- Interface 이름 변경 금지
- Stage 이름 변경 금지

반드시 입력값 그대로 사용한다.

예:
UE_not_responding -> UE_not_responding
VENDOR_SPECIFIC_CAUSE_15001 -> VENDOR_SPECIFIC_CAUSE_15001
S11_GTPv2C -> S11_GTPv2C

STEP1, STEP2에서는 설명하지 말고 관찰 결과만 작성한다.

최종 판단은 STEP3에서만 수행한다.
"""


STEP1_TEMPLATE = """
STEP 1. 네트워크 증거

목표:
네트워크 관련 데이터를 정렬하여 관찰 결과만 추출한다.

절대 하지 말 것:
- 원인 추론
- 의미 해석
- RCA 판단
- 대응조치 작성
- 가입자 언급

수행:
1. Failure Contribution 상위 장비 출력
2. Failure Count 상위 Cause 출력
3. Failure Count 상위 Interface 출력
4. Failure Count 상위 Stage 출력
5. 동일 Cause가 여러 장비에서 반복되는 경우만 기록

출력 형식:
## Top Devices

- Entity:
- Failure Contribution:

## Top Causes

- Cause:
- Count:

## Top Interfaces

- Interface:
- Count:

## Top Stages

- Stage:
- Count:

## Repeated Device Patterns

- ...

[STEP 1 입력]
{payload}
"""

STEP2_TEMPLATE = """
STEP 2. 가입자 증거

목표:
가입자 관련 데이터를 정렬하여 관찰 결과만 추출한다.
전체 실패 건수 대비 IMSI의 Total Failure Share를 우선 평가한다.
IMSI Failure Rate는 보조 지표로 사용한다.
IMSI Failure Rate가 100%라도 Total Failure Share가 낮으면 가입자 집중도는 낮게 평가한다.

절대 하지 말 것:

- 원인 추론
- 이동성 문제 추정
- Network-side 판단
- RCA 판단
- 대응조치 작성

우선순위:

1. Total Failure Share
2. IMSI Failure Rate
3. Repeated Failure IMSI
4. Multi-MME IMSI
5. Multi-eNB IMSI
6. Zero Success IMSI

출력 형식:

## Top IMSI

- IMSI:
- Failures:
- IMSI Failure Rate:
- Total Failure Share:

## Repeated Failure IMSI

- ...

## Multi-MME IMSI

- ...

## Multi-eNB IMSI

- ...

## Zero Success IMSI

- ...

[STEP 2 입력]
{payload}
"""

STEP3_TEMPLATE = """
STEP 3. 최종 RCA

STEP1과 STEP2 결과만 사용한다.

새로운 분석 금지.
새로운 데이터 생성 금지.
STEP1, STEP2 내용을 반복 출력하지 않는다.

판단 우선순위:

1. Device Concentration
2. Interface Concentration
3. Stage Concentration
4. Total Failure Share
5. Repeated Failure IMSI
6. Multi-MME IMSI
7. Multi-eNB IMSI
8. IMSI Failure Rate

판단 규칙:
- IMSI Failure Rate가 100%여도 Total Failure Share가 낮으면 Subscriber-side 근거를 약하게 본다.
- 특정 IMSI의 Failure Rate보다 전체 실패 중 차지하는 비중인 Total Failure Share를 우선한다.
- 예: IMSI Failure Rate = 100%, Total Failure Share = 7.9% 는 가입자 집중도 낮음.
- 예: IMSI Failure Rate = 100%, Total Failure Share = 45% 는 가입자 집중도 높음.

출력:

## 판단

Network-side Dominant
또는
Subscriber-side Dominant

## 신뢰도

High
Medium
Low

## 우선 점검 대상

MME:
eNB:
IMSI:

## 판단 근거

- Device:
- Interface:
- Stage:
- IMSI:

## 대응조치

- 즉시 확인 장비:
- 즉시 확인 인터페이스:
- 즉시 확인 가입자:

[STEP 3 입력]
{payload}
"""

LOOP_STEP_TEMPLATES = {
    "step1": STEP1_TEMPLATE,
    "step2": STEP2_TEMPLATE,
    "step3": STEP3_TEMPLATE,
}


def build_loop_step_messages(step_name: str, payload: dict[str, Any]) -> list[dict[str, str]]:
    template = LOOP_STEP_TEMPLATES[step_name]
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": STEP_SYSTEM_PROMPT},
        {"role": "user", "content": template.format(payload=payload_text)},
    ]


def build_loop_step1_messages(compact_rca_ir: dict[str, Any]) -> list[dict[str, str]]:
    payload = {
        "entity_failure_contribution": compact_rca_ir.get("entity_failure_contribution", {}),
        "shared_failure_observations": compact_rca_ir.get("shared_failure_observations", []),
        "interface_failure_distribution": compact_rca_ir.get("interface_failure_distribution", {}),
        "failure_stage_distribution": compact_rca_ir.get("failure_stage_distribution", {}),
    }
    return build_loop_step_messages("step1", payload)


def build_loop_step2_messages(compact_rca_ir: dict[str, Any]) -> list[dict[str, str]]:
    patterns = sorted(
        compact_rca_ir.get("subscriber_failure_patterns", []),
        key=lambda row: _num(row.get("total_failure_share")),
        reverse=True,
    )[:5]
    compact_patterns = [
        {
            "imsi_prefix": row.get("imsi_prefix", ""),
            "attempts": row.get("attempts", 0),
            "failures": row.get("failures", 0),
            "imsi_failure_rate": row.get("imsi_failure_rate", 0.0),
            "total_failure_share": row.get("total_failure_share", 0.0),
            "mme_count": row.get("mme_count", 0),
            "enb_count": row.get("enb_count", 0),
            "zero_success": row.get("zero_success", False),
        }
        for row in patterns
    ]
    payload = {
        "statistics": compact_rca_ir.get("statistics", {}),
        "subscriber_failure_patterns": compact_patterns,
        "subscriber_mobility_summary": compact_rca_ir.get("subscriber_mobility_summary", {}),
    }
    return build_loop_step_messages("step2", payload)


def build_loop_step3_messages(
    compact_rca_ir: dict[str, Any],
    network_evidence: str,
    subscriber_evidence: str,
) -> list[dict[str, str]]:
    payload = {
        "statistics": compact_rca_ir.get("statistics", {}),
        "network_evidence": network_evidence,
        "subscriber_evidence": subscriber_evidence,
    }
    return build_loop_step_messages("step3", payload)


def build_loop_reasoning_steps(compact_rca_ir: dict[str, Any], previous_results: list[str]) -> list[dict[str, str]]:
    step_index = len(previous_results)
    if step_index == 0:
        return build_loop_step1_messages(compact_rca_ir)
    if step_index == 1:
        return build_loop_step2_messages(compact_rca_ir)
    if step_index == 2:
        return build_loop_step3_messages(compact_rca_ir, previous_results[0], previous_results[1])
    return build_loop_step3_messages(
        compact_rca_ir,
        previous_results[0] if previous_results else "",
        previous_results[1] if len(previous_results) > 1 else "",
    )


def build_report_prompt_from_reasoning(
    compact_rca_ir: dict[str, Any],
    reasoning: Any,
) -> list[dict[str, str]]:
    ir_json = json.dumps(compact_rca_ir, ensure_ascii=False, indent=2)
    reasoning_text = json.dumps(reasoning, ensure_ascii=False, indent=2) if not isinstance(reasoning, str) else reasoning
    system = (
        "당신은 LTE/EPC 운영 보고서 작성자입니다. "
        "새로운 RCA 판단을 하지 말고, 제공된 데이터와 reasoning 결과를 운영자용 markdown report로 렌더링만 하세요. "
        "reasoning 결과를 변경하거나 보강하지 마세요."
    )
    user = f"""\
아래 Compact RCA IR과 LLM reasoning 결과만 기반으로 운영자용 markdown report를 작성하세요.

중요:
- 새로운 원인 판단 금지
- reasoning 결과를 그대로 반영
- Compact RCA IR과 reasoning 결과에 없는 장비/IMSI/원인/통계 생성 금지
- 원본 xDR 또는 추가 분석 데이터가 없다고 가정하고, reasoning 결과를 포맷팅만 수행
- markdown table 사용

[Compact RCA IR]
{ir_json}

[LLM reasoning result]
{reasoning_text}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_default_system_prompt() -> str:
    return """\
당신은 LTE/EPC 네트워크 RCA 분석 전문가입니다.

반드시 입력 데이터만 사용합니다.
반드시 한국어로 결과를 작성합니다.

절대 금지:
- 입력에 없는 장비 생성
- 입력에 없는 IMSI 생성
- 입력에 없는 Cause 생성
- 입력에 없는 Interface 생성
- 입력에 없는 Stage 생성
- 입력에 없는 PLMN 생성
- Cause / Interface / Stage 이름 변경
- 대응조치 생성
- 운영 권고 생성
- 최적화 제안 생성
- Vendor 문의 제안 생성

다음 내용은 입력 데이터에 명시되어 있지 않으면 추론하지 않습니다:
- 무선 품질 문제
- 커버리지 문제
- 간섭
- DRX
- 장비 버그
- Software Issue
- Hardware Issue
- HSS 문제
- Backhaul 문제
- Vendor 문제
- Resource 문제

값 보존 예:
- UE_not_responding 은 그대로 사용
- VENDOR_SPECIFIC_CAUSE_15001 은 그대로 사용
- S11_GTPv2C 는 그대로 사용

RCA 판단 시 가장 중요하게 사용할 데이터:
1. Entity Failure Contribution
2. Shared Failure Observations
3. Interface Failure Distribution
4. Failure Stage Distribution
5. Representative Chains
6. Subscriber Summary

Network-side 우세 조건:
- 특정 MME/eNB에 Failure 집중
- 높은 Failure Contribution
- 동일 Interface/Stage/Cause 조합 반복
- Shared Failure Observation 반복
- affected_imsi_count 큼
- affected_mme_count 큼
- affected_enb_count 큼

Subscriber-side 우세 조건:
- 전체 가입자 중 반복 실패 가입자 비율이 높음
- 상위 IMSI의 Total Failure Share가 높음
- Multi-MME IMSI 비율이 높음
- Multi-eNB IMSI 비율이 높음
- Zero Success IMSI가 Subscriber Summary 내에서 의미 있게 집중됨

주의:
- 개별 IMSI 사례보다 전체 가입자 분포를 우선합니다.
- repeated_failure_ratio가 낮으면 subscriber 집중 현상으로 해석하지 않습니다.
- top_imsi_failure_share 단독으로 subscriber-side를 판단하지 않습니다.
- affected_imsi_count 대비 repeated_failure_imsi_count 비율을 우선 고려합니다.
- multi_mme_imsi_count, multi_enb_imsi_count는 보조 증거로만 사용합니다.

판단 우선순위:
1. Failure Contribution
2. Shared Failure Observation
3. Interface Distribution
4. Stage Distribution
5. Repeated Failure Ratio
6. Top IMSI Failure Share
7. Multi-MME IMSI
8. Multi-eNB IMSI

최종 RCA는 반드시 아래 중 하나만 사용:
- Network-side Dominant
- Subscriber-side Dominant
- Mixed
- Unknown

신뢰도는 반드시 아래 중 하나만 사용:
- High
- Medium
- Low

필요 시 아래 항목만 작성합니다:
- 우선 점검 장비
- 우선 점검 Interface
- 우선 점검 IMSI
- 추가 확인 필요 데이터

Markdown을 사용하고, HTML은 사용하지 않습니다."""


def build_gemma4_system_prompt() -> str:
    return """\
당신은 LTE/EPC RCA 분석 엔진이다.

반드시 입력 데이터만 사용한다.
반드시 한국어로 작성한다.
"""


def build_rca_messages(summary: dict[str, Any], model_name: str = "") -> list[dict[str, str]]:
    """
    RCA LLM 호출용 messages (system + user).
    LLM이 RCA 판단/보고서를 직접 생성한다.
    """
    observation = summary.get("compact_rca_ir", summary) if isinstance(summary, dict) else summary
    if isinstance(observation, dict):
        observation = {
            k: v
            for k, v in observation.items()
            if k not in {"subscriber_cause_distribution", "subscriber_plmn_distribution"}
        }
    is_gemma = "gemma" in (model_name or "").lower()
    system = build_gemma4_system_prompt() if is_gemma else build_default_system_prompt()

    ctx_json = json.dumps(observation, ensure_ascii=False, indent=2)
    user = f"""\
다음 xDR 관측 데이터를 분석하여 RCA 판단 결과를 한국어로 작성하세요.

[관측 데이터]
{ctx_json}

[출력 형식]

## 최종 RCA

| 항목 | 값 |
|---|---|
| 판단 | Network-side Dominant / Subscriber-side Dominant / Mixed / Unknown 중 하나 |
| 신뢰도 | High / Medium / Low 중 하나 |

## 판단 근거

### Network-side 근거
- 입력 데이터의 Entity Failure Contribution / Shared Failure Observations / Interface / Stage 기반 근거만 작성

### Subscriber-side 근거
- 입력 데이터의 Subscriber Summary 기반 근거만 작성

### 반대 근거 또는 제한 사항
- 판단을 약하게 만드는 입력 데이터 기반 근거만 작성

## 우선 확인 대상

- 우선 점검 장비:
- 우선 점검 Interface:
- 우선 점검 IMSI:
- 추가 확인 필요 데이터:
"""
    if is_gemma:
        user += """\

중요:
출력 형식을 지키지 않으면 오답이다.
반드시 다음 문자열로 시작한다.

## 최종 RCA

Classification:
Reasoning:
Conclusion:
Summary:

사용 금지
"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
