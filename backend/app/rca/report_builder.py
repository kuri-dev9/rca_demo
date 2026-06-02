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
            "plmn": seq.get("plmn", ""),
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
        "subscriber_failure_patterns": subscriber_patterns,
        "subscriber_cause_distribution": analysis.subscriber_cause_distribution,
        "subscriber_plmn_distribution": analysis.subscriber_plmn_distribution,
        "subscriber_mobility_summary": analysis.subscriber_mobility_summary,
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
입력 데이터만 사용한다.

금지:
- 입력에 없는 값 생성
- Cause 의미 해석
- Interface 의미 해석
- Vendor Cause 의미 추정
- Stage 의미 추정

다음 값은 그대로 사용한다:
- Interface
- Stage
- Cause
- Entity
- Failure Contribution
- IMSI
- PLMN

예시:
- UE_not_responding → 그대로 사용
- VENDOR_SPECIFIC_CAUSE_15001 → 그대로 사용
- S11_GTPv2C → 그대로 사용

출력은 한국어 Markdown만 사용한다.

최종 RCA 판단은 STEP3에서만 수행한다.
"""


STEP1_TEMPLATE = """
STEP 1. 네트워크 증거

목표:
- 장비 관점 증거 수집
- RCA 판단 금지
- Subscriber 분석 금지

분석 대상:
- Failure Contribution
- Interface Distribution
- Stage Distribution
- Shared Failure Observation

허용:
- 상위 장비 정렬
- 집중도 분석
- 반복 패턴 분석

출력:

## Failure Contribution 집중 장비

## Top Cause 집중도

## Stage / Interface 집중도

## 장비 편중 여부

## 장비 관점 패턴

[STEP 1 입력]
{payload}
"""

STEP2_TEMPLATE = """
STEP 2. 가입자 증거

목표:
- 가입자 관점 증거 수집
- RCA 판단 금지
- Network-side 판단 금지

우선순위:
1. Repeated Failure IMSI
2. Multi-MME IMSI
3. Multi-eNB IMSI
4. Zero Success IMSI
5. IMSI Failure Rate
6. Total Failure Share

분석 대상:
- IMSI Failure Rate
- Total Failure Share
- Cause Distribution
- PLMN Distribution
- Repeated Failure IMSI
- Multi-MME IMSI
- Multi-eNB IMSI
- Zero Success IMSI

출력:

## IMSI 집중도

## PLMN 집중도

## Cause 집중도

## Repeated Failure Evidence

## Mobility Evidence

## Zero Success Evidence

[STEP 2 입력]
{payload}

---
PLMN Failure Count 자체는 RCA 판단 근거로 사용하지 않는다.
PLMN은 분포 확인 용도로만 사용한다.
IMSI Failure Rate와 Total Failure Share를 우선한다.
"""

STEP3_TEMPLATE = """
STEP 3. 최종 RCA

목표:
- STEP1 네트워크 증거와 STEP2 가입자 증거만 사용
- 새로운 분석 생성 금지
- 새로운 근거 생성 금지

판단:
- Network-side Dominant
- Subscriber-side Dominant

Mixed 사용 조건:
- Network-side와 Subscriber-side 증거가 모두 강하고
- 우선 점검 대상을 하나로 정할 수 없는 경우만 허용

Unknown 사용 금지

판단 우선순위:
1. Device Concentration
2. Interface Concentration
3. Stage Concentration
4. IMSI Failure Rate
5. Total Failure Share
6. Repeated Failure IMSI
7. Multi-MME IMSI
8. Multi-eNB IMSI

출력:

## 판단

## 신뢰도

## 우선 점검 대상
- MME
- eNB
- IMSI

## 근거
- Device Concentration
- Interface Concentration
- Stage Concentration
- IMSI Failure Rate
- Total Failure Share
- Mobility Evidence

## 대응조치
- 즉시 확인할 장비
- 즉시 확인할 Procedure
- 즉시 확인할 가입자

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
    payload = {
        "subscriber_failure_patterns": compact_rca_ir.get("subscriber_failure_patterns", []),
        "subscriber_cause_distribution": compact_rca_ir.get("subscriber_cause_distribution", []),
        "subscriber_plmn_distribution": compact_rca_ir.get("subscriber_plmn_distribution", []),
        "subscriber_mobility_summary": compact_rca_ir.get("subscriber_mobility_summary", {}),
    }
    return build_loop_step_messages("step2", payload)


def build_loop_step3_messages(network_evidence: str, subscriber_evidence: str) -> list[dict[str, str]]:
    payload = {
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
        return build_loop_step3_messages(previous_results[0], previous_results[1])
    return build_loop_step3_messages(
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


def build_rca_messages(summary: dict[str, Any]) -> list[dict[str, str]]:
    """
    RCA LLM 호출용 messages (system + user).
    LLM이 RCA 판단/보고서를 직접 생성한다.
    """
    system = """\
당신은 LTE/EPC 네트워크 RCA 분석 전문가입니다.

제공된 xDR 관측 데이터(statistics, baseline, representative failure chain,
shared failure observation, IMSI timeline)를 기반으로
운영자 관점의 RCA 분석 결과를 작성하세요.

========================
[핵심 원칙]
========================

1. 입력 데이터 우선
- 제공된 관측 데이터를 기반으로 분석하세요.
- 입력 데이터에 없는 값을 새로 생성하지 마세요.
- 숫자 재계산 최소화.
- attempts/success/failures/failure_rate/anomaly_ratio 값은 입력값 그대로 사용하세요.

2. Hallucination 최소화
다음 내용은 입력 데이터 근거가 있을 때만 작성:
- recovery pattern
- retry pattern
- intermittent failure
- vendor issue
- resource issue
- software update
- optimization
- tuning
- escalation

근거가 부족하면 아래 표현만 사용하세요:
- 판단 불가
- 추가 데이터 필요
- 가능성 존재

3. RCA 판단 기준
다음 관측값을 우선 활용:
- anomaly_ratio
- failure_rate
- shared_failure_observations
- representative_chains
- interface/stage 분포
- IMSI timeline

4. 장비 vs 가입자 판단 규칙

다음 조건을 기반으로 network-side / subscriber-side를 판단하세요.
단일 지표만으로 확정하지 마세요

[network-side 가능성 증가 조건]
- 동일 interface/stage/cause가 다수 IMSI에서 반복되면 network-side 가능성 증가
- affected_imsi_count가 큼
- 특정 eNB에서 success=0이면 장비 이상 가능성 증가
- 특정 eNB에 failure 집중
- 동일 cause가 여러 가입자에 공통 발생

[subscriber-side 가능성 증가 조건]
- 특정 IMSI만 지속 실패
- 특정 stage/cause가 단일 가입자 중심으로 반복

5. APN은 보조 정보
- APN 기반 결론 금지

6. Generic 운영 문구 금지
다음 문장 생성 금지:

- software update 필요
- optimization 필요
- tuning 필요
- vendor issue 가능성
- resource issue 가능성
- escalation 필요
- 추가 분석 필요

대신 실제 필요한 추가 데이터 항목을 구체적으로 작성하세요.

좋은 예:
- S1AP reject trace 필요
- eNB sector KPI 필요
- UE capability 정보 필요
- RRC Reject counter 필요
- Attach Reject 상세 cause 필요

========================
[출력 규칙]
========================
1. Markdown 사용
2. 주요 분석은 markdown table syntax를 사용
3. 설명은 짧고 명확하게 작성
4. 입력 데이터에 없는 예시값 생성 금지
5. HTML 태그 사용 금지"""

    ctx_json = json.dumps(summary, ensure_ascii=False, indent=2)
    user = f"""\
다음 xDR 관측 데이터를 분석하여 RCA 보고서를 한국어로 작성해주세요.

[관측 데이터]
{ctx_json}

[출력 형식]

# 1. Interface / Stage 분석

## Interface Failure 분포

| Interface | Failures |
|---|---|

## Failure Stage 분포

| Stage | Failures |
|---|---|

========================

# 2. 장비 분석

## MME

| MME | Attempts | Success | Failures | Failure Rate | Anomaly Ratio | 분석 |
|---|---|---|---|---|---|---|

분석 기준:
- anomaly_ratio 높음 여부
- failure_rate 비교
- 특정 MME 집중 여부

## eNB

| eNB | Attempts | Success | Failures | Failure Rate | Anomaly Ratio | 분석 |
|---|---|---|---|---|---|---|

분석 기준:
- success=0 여부
- anomaly_ratio 높음 여부
- failure 집중 여부

========================

# 3. Representative Failure Chain 분석

아래 형식 사용:

- [절차명]
  - Interface:
  - Failure Point:
  - Cause:
  - Chain:
    - IMSI: IMSI_PREFIX1
      - EVENT1 → EVENT2 → EVENT3 ...
    - IMSI: IMSI_PREFIX2
      - EVENT1 → EVENT2 → EVENT3 ...

========================

# 4. 실패 통계

| Interface | Stage | Cause | Count | IMSI | MME | eNB | 해석 |
|---|---|---|---|---|---|---|---|

해석 기준:
- 동일 cause가 다수 IMSI 반복
- 특정 eNB 집중 여부
- 여러 eNB 분산 여부
- network-side 가능성
- subscriber-side 가능성

단, 입력 데이터 근거 없이 단정 금지.

========================

# 5. IMSI Timeline 분석

| IMSI | 특징 | 해석 |
|---|---|---|

가능한 분석:
- 동일 IMSI 반복 실패
- 여러 장비 이동 중 동일 실패
- 성공 이벤트 없음
- 특정 stage 고정 실패
- 특정 interface 반복 실패

입력 데이터에 없는 패턴 생성 금지.

========================

# 6. 최종 RCA 판단

| 항목 | 판단 |
|---|---|
| 주요 성격 | |
| 주요 근거 | |
| Network-side 가능성 | |
| Subscriber-side 가능성 | |
| 추가 필요 데이터 | |

최종 결론은 반드시 아래 중 하나만 사용:
- network-side 우세
- subscriber-side 우세
- 혼합형
- 판단 불가

"추가 분석 필요" 문장 금지.
대신 필요한 데이터 항목을 구체적으로 작성하세요."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
