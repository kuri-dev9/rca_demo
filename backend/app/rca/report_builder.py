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
