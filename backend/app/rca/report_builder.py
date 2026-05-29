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


def build_semantic_summary(analysis: RcaAnalysis) -> dict[str, Any]:
    """
    LLM 전달용 compact semantic summary.
    raw 코드 대신 의미 있는 이름으로 변환된 관측 데이터만 포함.
    token 폭발 방지: top N / histogram / representative sample 형태만 사용.
    """
    # 1. 전체 통계 (global failure/success rate 포함)
    gfr = round(analysis.failure_rate, 2)
    statistics = {
        "total_records": analysis.total_records,
        "attempt_count": analysis.attempt_count,
        "success_count": analysis.success_count,
        "failure_count": analysis.failure_count,
        "failure_rate": gfr,
        "global_failure_rate": gfr,
        "global_success_rate": round(100.0 - gfr, 2),
    }

    # 2. Failure stage 분포 (chain의 failure_point 기준)
    stage_counter: Counter[str] = Counter()
    for chain in analysis.failure_chains:
        stage_counter[chain.failure_point] += 1

    # 3. Interface failure 분포 (analyzer가 이미 interface name으로 집계)
    interface_dist = dict(analysis.interface_distribution)

    # 5. 대표 failure chain (중복 제거, top 10)
    rep_chains = []
    seen: set[str] = set()
    for chain in analysis.failure_chains:
        key = " → ".join(chain.chain)
        if key in seen:
            continue
        seen.add(key)
        rep_chains.append({
            "procedure": chain.procedure,
            "chain": chain.chain,
            "failure_point": chain.failure_point,
            "interface": chain.failure_interface,
            "cause": chain.failure_cause_name,
        })
        if len(rep_chains) >= 10:
            break

    # 6. MME baseline: per-MME attempt/success/failures/failure_rate/anomaly_ratio
    mme_baseline = analysis.mme_baseline

    # 7. eNB baseline
    enb_baseline = analysis.enb_baseline

    # 8. APN 보조 정보 (top 5, 우선순위 낮음)
    def _top_apn(d: dict, n: int = 5) -> list[dict]:
        return [
            {"apn": str(k), "count": v}
            for k, v in sorted(d.items(), key=lambda x: x[1], reverse=True)[:n]
        ]

    top_apn = _top_apn(analysis.affected_apns)

    # 9. Shared failure observations (관측 데이터 only — 판단/결론 없음)
    shared_failure_observations = analysis.shared_failure_signatures

    # 10. Top failing IMSI: stats compact list (timeline은 imsi_timelines에)
    top_failed_imsi: list[dict] = []
    imsi_timelines: list[dict] = []
    for seq in analysis.top_failed_imsi_sequences:
        top_failed_imsi.append({
            "imsi_prefix": seq.get("imsi", ""),
            "attempts": seq.get("attempts", 0),
            "success": seq.get("success", 0),
            "failures": seq.get("failures", 0),
            "failure_rate": seq.get("failure_rate", 0.0),
            "anomaly_ratio": seq.get("anomaly_ratio", 0.0),
        })
        imsi_timelines.append({
            "imsi_prefix": seq.get("imsi", ""),
            "total_events": seq.get("total_events", 0),
            "included_events": seq.get("included_events", 0),
            "timeline": seq.get("events", []),
        })

    # 11. Burst
    burst = {
        "detected": analysis.burst_detected,
        "window": analysis.burst_window,
    }

    return {
        "statistics": statistics,
        "failure_stage_distribution": dict(stage_counter),
        "interface_failure_distribution": interface_dist,
        "representative_chains": rep_chains,
        "mme_baseline": mme_baseline,
        "enb_baseline": enb_baseline,
        "shared_failure_observations": shared_failure_observations,
        "top_failed_imsi": top_failed_imsi,
        "imsi_timelines": imsi_timelines,
        "top_apn": top_apn,
        "burst": burst,
    }


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _critical_enb(enb_baseline: list[dict[str, Any]], limit: int = 10) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[float, float]:
        return (_num(row.get("anomaly_ratio")), _num(row.get("failures")))

    out = []
    for row in sorted(enb_baseline, key=sort_key, reverse=True)[:limit]:
        out.append({
            "enb_id": row.get("enb_id"),
            "attempts": row.get("attempts"),
            "success": row.get("success"),
            "failures": row.get("failures"),
            "failure_rate": row.get("failure_rate"),
            "anomaly_ratio": row.get("anomaly_ratio"),
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


def _imsi_behavior_summary_from_sequences(sequences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for seq in sequences:
        stages: set[str] = set()
        causes: set[str] = set()
        enbs: set[str] = set()
        mmes: set[str] = set()
        failure_events = 0

        for event in seq.get("events", []):
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
            "imsi_prefix": seq.get("imsi", ""),
            "failure_count": seq.get("failures", failure_events),
            "success_count": seq.get("success", 0),
            "same_cause": len(causes) == 1 if failure_events else False,
            "same_stage": len(stages) == 1 if failure_events else False,
            "multi_enb": len(enbs) > 1,
            "multi_mme": len(mmes) > 1,
        })
    return summary


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


def _compact_mme(rows: list[dict[str, Any]], limit: int = 2) -> list[dict[str, Any]]:
    out = []
    sorted_rows = sorted(rows, key=lambda row: _num(row.get("anomaly_ratio")), reverse=True)[:limit]
    for row in sorted_rows:
        out.append({
            "mme_id": row.get("mme_id"),
            "attempts": row.get("attempts"),
            "success": row.get("success"),
            "failures": row.get("failures"),
            "failure_rate": row.get("failure_rate"),
            "anomaly_ratio": row.get("anomaly_ratio"),
        })
    return out


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
        "mme_baseline": _compact_mme(analysis.mme_baseline),
        "critical_enb": _critical_enb(analysis.enb_baseline),
        "shared_failure_observations": _compact_shared_failures(analysis.shared_failure_signatures),
        "imsi_behavior_summary": _imsi_behavior_summary_from_sequences(analysis.top_failed_imsi_sequences),
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
                "You are an LTE/EPC RCA reasoning engine.\n\n"
                "Your role is causal reasoning only.\n\n"
                "Do not generate reports.\n"
                "Do not generate markdown.\n"
                "Do not generate tables.\n"
                "Do not generate HTML.\n\n"
                "Use ONLY the provided Compact RCA IR.\n\n"
                "Never invent missing values.\n\n"
                "Never infer APN-related conclusions.\n\n"
                "Keep the response concise and operationally focused."
            ),
        },
        {"role": "user", "content": build_reasoning_prompt(observability)},
    ]


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


# backward compat: /report SSE endpoint에서 사용
def build_user_prompt(context: dict[str, Any]) -> str:
    """기존 /report SSE 엔드포인트용 user prompt."""
    ctx_json = json.dumps(context, ensure_ascii=False, indent=2)
    return (
        f"다음 xDR 관측 데이터를 분석하여 RCA 보고서를 한국어로 작성해주세요.\n\n"
        f"[관측 데이터]\n{ctx_json}\n\n"
        f"[보고서 형식]\n"
        f"## 1. 장애 요약\n"
        f"## 2. 근본 원인 분석\n"
        f"## 3. 영향 범위\n"
        f"## 4. 조치 권고사항\n"
        f"## 5. 모니터링 포인트"
    )
