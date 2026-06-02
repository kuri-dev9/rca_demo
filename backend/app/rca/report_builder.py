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


def _imsi_behavior_summary_from_sequences(sequences: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for seq in sequences:
        summary.append({
            "imsi_prefix": seq.get("imsi", ""),
            "attempts": seq.get("attempts", 0),
            "failures": seq.get("failures", 0),
            "imsi_failure_rate": seq.get("imsi_failure_rate", 0.0),
            "total_failure_share": seq.get("total_failure_share", 0.0),
            "same_cause_ratio": seq.get("same_cause_ratio", 0.0),
            "same_stage_ratio": seq.get("same_stage_ratio", 0.0),
            "multi_mme": bool(seq.get("multi_mme", False)),
            "multi_enb": bool(seq.get("multi_enb", False)),
            "zero_success": int(seq.get("success") or 0) == 0,
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


def _subscriber_cause_distribution(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in patterns:
        cause = str(row.get("cause") or "UNKNOWN")
        item = grouped.setdefault(cause, {
            "cause": cause,
            "failures": 0,
            "_imsis": set(),
            "_plmns": set(),
        })
        item["failures"] += int(row.get("failures") or 0)
        if row.get("imsi_prefix"):
            item["_imsis"].add(str(row["imsi_prefix"]))
        if row.get("plmn"):
            item["_plmns"].add(str(row["plmn"]))
    out = []
    for item in grouped.values():
        out.append({
            "cause": item["cause"],
            "failures": item["failures"],
            "imsi_count": len(item["_imsis"]),
            "plmn_count": len(item["_plmns"]),
        })
    return sorted(out, key=lambda item: item["failures"], reverse=True)


def _subscriber_plmn_distribution(patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in patterns:
        plmn = str(row.get("plmn") or "UNKNOWN")
        cause = str(row.get("cause") or "UNKNOWN")
        failures = int(row.get("failures") or 0)
        item = grouped.setdefault(plmn, {
            "plmn": plmn,
            "failures": 0,
            "_imsis": set(),
            "_causes": Counter(),
        })
        item["failures"] += failures
        if row.get("imsi_prefix"):
            item["_imsis"].add(str(row["imsi_prefix"]))
        item["_causes"][cause] += failures
    out = []
    for item in grouped.values():
        top_cause = item["_causes"].most_common(1)[0][0] if item["_causes"] else ""
        out.append({
            "plmn": item["plmn"],
            "imsi_count": len(item["_imsis"]),
            "failures": item["failures"],
            "top_cause": top_cause,
        })
    return sorted(out, key=lambda item: item["failures"], reverse=True)


def _subscriber_mobility_summary(patterns: list[dict[str, Any]], affected_imsi_count: int) -> dict[str, int]:
    return {
        "affected_imsi_count": affected_imsi_count,
        "single_failure_imsi_count": sum(1 for row in patterns if int(row.get("failures") or 0) == 1),
        "repeated_failure_imsi_count": sum(1 for row in patterns if int(row.get("failures") or 0) > 1),
        "multi_mme_imsi_count": sum(1 for row in patterns if int(row.get("mme_count") or 0) > 1),
        "multi_enb_imsi_count": sum(1 for row in patterns if int(row.get("enb_count") or 0) > 1),
        "zero_success_imsi_count": sum(1 for row in patterns if bool(row.get("zero_success"))),
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


def _compact_mme(rows: list[dict[str, Any]], limit: int = 2) -> list[dict[str, Any]]:
    out = []
    sorted_rows = sorted(rows, key=lambda row: _num(row.get("failures")), reverse=True)[:limit]
    for row in sorted_rows:
        out.append({
            "mme_id": row.get("mme_id"),
            "attempts": row.get("attempts"),
            "success": row.get("success"),
            "failures": row.get("failures"),
            "failure_rate": row.get("failure_rate"),
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


STEP_SYSTEM_PROMPT = """당신은 LTE/EPC RCA 단계 분석 엔진이다.
입력 데이터만 사용하고, 없는 값/장비/IMSI/Cause를 만들지 않는다.
IMSI는 입력 문자열 그대로 사용하며, prefix 기준 grouping/aggregation을 하지 않는다.
APN/Trend/시간 기반 추론은 생성하지 않는다.
한국어 Markdown만 출력하고 JSON/HTML/영어 제목은 출력하지 않는다.
최종 Root Cause 확정은 최종 RCA 단계에서만 수행한다.
Failure Contribution은 재계산하지 않고 입력값을 그대로 사용한다. 입력에 없으면 N/A로 출력한다.
대응조치는 Final RCA 단계에서 RCA 이후 Action Item으로 분리된 경우만 허용한다.
금지 문구: 위치 기반 신호 문제, 통신 장애로 보임, 추가 분석 필요, 모니터링 필요, 최적화 필요.
"""


STEP1_TEMPLATE = """STEP 1. 네트워크 신호 추출

목표:
- 장비별 실패 신호와 주요 실패 패턴만 정리
- 입력의 entity_id를 그대로 제목에 사용
- 입력의 top_mme/top_enb/top_sgw 항목을 모두 출력
- 어떤 장비에서 어떤 interface/stage/cause가 몇 건 관찰됐는지만 출력
- Root Cause/통신 문제/위치 기반 신호/추가 분석 언급 금지

출력 형식:
## 네트워크 신호

### MME 47
| Interface | Stage | Cause | Count |
|---|---|---|---:|

### eNB bo3reaGROYftluYm2HmjZQ==
| Interface | Stage | Cause | Count |
|---|---|---|---:|

---

[STEP 1 입력]
{payload}
"""


STEP2_TEMPLATE = """STEP 1. 네트워크 증거

목표:
- 장비 관점의 사실 기반 증거 수집만 수행
- Observability Summary의 MME/eNB/SGW Failure Contribution과 유형별 실패 통계를 기반으로 Evidence 생성
- Failure Contribution 집중 장비, Interface 집중도, Stage 집중도, Cause 집중도, MME/eNB 편중도, 반복 발생 패턴 분석
- 단순 데이터 재출력 금지
- Fact 기반 관찰만 작성
- RCA 판단 금지
- Root Cause 추정 금지
- Network-side / Subscriber-side 결론 금지
- 대응방안 금지
- 원인 추정 금지
- 입력의 entity_id를 그대로 제목에 사용
- Failure Contribution은 입력값 그대로 사용하고, 입력에 없으면 N/A

출력 형식:
## 네트워크 증거

### Failure Contribution 집중 장비
- ...

### Top Cause 집중도
- ...

### Stage / Interface 집중도
- ...

### 장비 편중 여부
- ...

### 장비 관점 패턴
- ...

---

[STEP 1 입력]
{payload}
"""


STEP3_TEMPLATE = """STEP 3. 가입자 신호 추출

목표:
- PLMN별 Failure Signal 생성
- PLMN별 IMSI 수, Failure 수, Top Cause 정리
- Repeated Failure / Multi MME / Multi eNB / Zero Success 신호 정리
- Representative IMSI는 입력에 제공된 최대 3개만 출력
- RCA/Root Cause/Network-side/Subscriber-side 판단 금지

출력 형식:
## 가입자 신호

### PLMN별 Failure Signal
| PLMN | IMSI Count | Failures | Top Cause |
|---|---:|---:|---|

### Subscriber Cause Signal
| Cause | Failures | Failure Ratio | IMSI Count | PLMN Count |
|---|---:|---:|---:|---:|

### Mobility Signal
- Affected IMSI:
- Repeated Failure IMSI:
- Multi MME IMSI:
- Multi eNB IMSI:
- Zero Success IMSI:

### Representative IMSI
| IMSI | PLMN | Stage | Cause | Attempts | Failures | IMSI Failure Rate | Total Failure Share | MME Count | eNB Count | Zero Success |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---|

---

[STEP 3 입력]
{payload}
"""


STEP4_TEMPLATE = """STEP 2. 가입자 증거

목표:
- 가입자 관점의 사실 기반 증거 수집만 수행
- Observability Summary의 Subscriber 통계를 기반으로 Evidence 생성
- Cause 집중도, PLMN 집중도, Repeated Failure IMSI, Multi-MME IMSI, Multi-eNB IMSI, Zero Success IMSI, Representative IMSI 분석
- Representative IMSI에서는 IMSI Failure Rate와 Total Failure Share를 구분하여 사용
- 우선순위: Repeated Failure IMSI, Multi-MME IMSI, Multi-eNB IMSI, Zero Success IMSI, Cause Distribution, PLMN Distribution
- 단순 통계 재출력 금지
- Fact 기반 관찰만 작성
- RCA 판단 금지
- Root Cause 추정 금지
- Network-side / Subscriber-side 결론 금지
- 대응방안 금지
- 원인 추정 금지

출력 형식:
## 가입자 증거

### IMSI 집중도
- ...

### PLMN 집중도
- ...

### Cause 집중도
- ...

### Repeated Failure / Mobility Evidence
- ...

### Zero Success Evidence
- ...

---

[STEP 2 입력]
{payload}
"""


STEP5_TEMPLATE = """STEP 3. 상관관계 분석

목표:
- Step1 네트워크 증거와 Step2 가입자 증거를 비교
- Cause overlap, PLMN concentration, Device concentration, Repeated IMSI ratio, Multi-MME ratio, Multi-eNB ratio, Zero Success ratio, Stage overlap, Interface overlap 분석
- 장비 집중도, PLMN 집중도, IMSI Total Failure Share, IMSI Failure Rate, Repeated Failure, Multi-MME/eNB, Zero Success 패턴을 모두 활용
- Cause는 참고 지표일 뿐 최종 판단 근거로 사용하지 않음
- 단순 Cause 이름 비교 금지
- 최종 RCA 판단 금지
- 대응조치 금지
- Root Cause 확정 금지
- 증거 정리만 수행

출력 형식:
## 상관관계 분석

### Network-side Evidence
- ...

### Subscriber-side Evidence
- ...

### Mixed Evidence
- ...

### Contradicting Evidence
- ...

---

[STEP 3 입력]
{payload}
"""


STEP6_TEMPLATE = """STEP 4. 최종 RCA

목표:
- Step3 Correlation 결과만 근거로 최종 RCA 판단
- Network-side Dominant / Subscriber-side Dominant / Mixed / Unknown 중 하나 선택
- 새로운 근거 생성 금지
- 새로운 분석 생성 금지
- Step3에 없는 장비/가입자/Cause/통계 생성 금지
- Cause 이름만으로 판단 금지
- UE_not_responding / Unable_to_page_UE / Network_failure 등은 증상으로 취급하고 Root Cause로 확정하지 않음
- Step3 증거만 재사용하여 최종 판단과 신뢰도 작성
- 대응조치는 RCA 이후 Action Item으로 Root Cause 근거와 분리하여 작성

판단 우선순위:
1. Device Concentration
2. Interface Concentration
3. Stage Concentration
4. IMSI Total Failure Share
5. IMSI Failure Rate
6. Repeated Failure IMSI Ratio
7. Multi-MME IMSI Ratio
8. Multi-eNB IMSI Ratio

판단 기준:
- Network-side Dominant: 특정 MME/eNB Failure Contribution, Interface 집중, Stage 집중이 강하고 상위 IMSI Total Failure Share와 Repeated/Multi-MME/Multi-eNB 비율이 낮은 경우
- Subscriber-side Dominant: 특정 IMSI의 IMSI Failure Rate와 Total Failure Share가 높고 여러 MME/eNB에서 반복 실패하며 Device/Interface/Stage 집중도가 약한 경우
- Mixed: Network-side 근거와 Subscriber-side 근거가 모두 강한 경우만 사용
- Unknown: Step3 증거만으로 우선 점검 대상을 정하기 어려운 경우
- 같은 Cause가 양쪽에 보인다는 이유만으로 Mixed 판단 금지

출력 형식:
# 최종 RCA

## 판단
Network-side Dominant / Subscriber-side Dominant / Mixed / Unknown 중 하나

## 우선 점검 대상
- Step3 증거에 등장한 MME/eNB/IMSI/PLMN만 작성

## 신뢰도
High / Medium / Low 중 하나

## 근거 요약
- Step3의 Network-side Evidence / Subscriber-side Evidence / Mixed Evidence / Contradicting Evidence만 재사용

## 대응 방향
- 판단 유형에 맞는 RCA 이후 Action Item만 작성
- Network-side Dominant: 우선 점검 대상 MME/eNB 로그 확인, 집중 Interface/Stage trace 확인, 관련 Interface Counter 확인, paging/session counter 확인
- Subscriber-side Dominant: Total Failure Share가 높은 IMSI 우선 확인, 해당 IMSI의 MME/eNB 이동 경로 확인, SIM/subscription/profile 상태 확인, 동일 IMSI 반복 실패 확인
- Mixed: Network-side 우선 점검 대상과 Subscriber-side 우선 점검 대상을 분리해서 작성
- Unknown: 부족한 데이터 항목을 구체적으로 작성하고 generic한 추가 분석 문장만 단독 출력하지 않음

## 요약
3줄 이내로 작성


---

[STEP 4 입력]
{payload}
"""


LOOP_STEP_TEMPLATES = {
    "step1": STEP1_TEMPLATE,
    "step2": STEP2_TEMPLATE,
    "step3": STEP3_TEMPLATE,
    "step4": STEP4_TEMPLATE,
    "step5": STEP5_TEMPLATE,
    "step6": STEP6_TEMPLATE,
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
    }
    return build_loop_step_messages("step1", payload)


def build_loop_step2_messages(compact_rca_ir: dict[str, Any]) -> list[dict[str, str]]:
    payload = {
        "entity_failure_contribution": compact_rca_ir.get("entity_failure_contribution", {}),
        "shared_failure_observations": compact_rca_ir.get("shared_failure_observations", []),
        "interface_failure_distribution": compact_rca_ir.get("interface_failure_distribution", {}),
        "failure_stage_distribution": compact_rca_ir.get("failure_stage_distribution", {}),
    }
    return build_loop_step_messages("step2", payload)


def build_loop_step3_messages(compact_rca_ir: dict[str, Any]) -> list[dict[str, str]]:
    payload = {
        "subscriber_cause_distribution": compact_rca_ir.get("subscriber_cause_distribution", []),
        "subscriber_plmn_distribution": compact_rca_ir.get("subscriber_plmn_distribution", []),
        "subscriber_mobility_summary": compact_rca_ir.get("subscriber_mobility_summary", {}),
        "representative_imsi": compact_rca_ir.get("subscriber_failure_patterns", [])[:3],
    }
    return build_loop_step_messages("step3", payload)


def build_loop_step4_messages(compact_rca_ir: dict[str, Any]) -> list[dict[str, str]]:
    payload = {
        "subscriber_failure_patterns": compact_rca_ir.get("subscriber_failure_patterns", []),
        "subscriber_cause_distribution": compact_rca_ir.get("subscriber_cause_distribution", []),
        "subscriber_plmn_distribution": compact_rca_ir.get("subscriber_plmn_distribution", []),
        "subscriber_mobility_summary": compact_rca_ir.get("subscriber_mobility_summary", {}),
    }
    return build_loop_step_messages("step4", payload)


def build_loop_step5_messages(network_evidence: str, subscriber_evidence: str) -> list[dict[str, str]]:
    payload = {
        "network_evidence": network_evidence,
        "subscriber_evidence": subscriber_evidence,
    }
    return build_loop_step_messages("step5", payload)


def build_loop_step6_messages(correlation: str) -> list[dict[str, str]]:
    payload = {
        "correlation": correlation,
    }
    return build_loop_step_messages("step6", payload)


def build_loop_reasoning_steps(compact_rca_ir: dict[str, Any], previous_results: list[str]) -> list[dict[str, str]]:
    step_index = len(previous_results)
    if step_index == 0:
        return build_loop_step2_messages(compact_rca_ir)
    if step_index == 1:
        return build_loop_step4_messages(compact_rca_ir)
    if step_index == 2:
        return build_loop_step5_messages(previous_results[0], previous_results[1])
    if step_index == 3:
        return build_loop_step6_messages(previous_results[2])
    return build_loop_step6_messages(previous_results[-1] if previous_results else "")


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
