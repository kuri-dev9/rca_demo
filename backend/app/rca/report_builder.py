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
from app.rca.spec_loader import get_call_type_name


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
            "call_type_code": row.get("call_type_code"),
            "call_type": row.get("call_type"),
            "interface": row.get("interface"),
            "message": row.get("message"),
            "stage": row.get("stage"),
            "cause": row.get("cause"),
            "count": row.get("count"),
            "affected_imsi_count": row.get("affected_imsi_count"),
            "affected_mme_count": row.get("affected_mme_count"),
            "affected_enb_count": row.get("affected_enb_count"),
        }
        for row in shared
    ]


def _build_rca_hints(
    analysis: RcaAnalysis,
    shared: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Backend 계산 가능한 관찰 사실만 정리.
    영향도/원인/판단 확정은 하지 않음 — LLM이 해석.
    """
    total = analysis.failure_count or 1

    # 패턴 건수: eNB 집중도 기반 RAN/Core 후보 분류
    ran_count = sum(s["count"] for s in shared if s.get("affected_enb_count", 0) <= 2)
    core_count = sum(s["count"] for s in shared if s.get("affected_enb_count", 0) > 2)

    # 집중 장애 eNB: success=0 이거나 failure_contribution_pct 상위
    critical_enb = [
        {
            "entity_id": e["entity_id"],
            "failures": e["failures"],
            "success": e["success"],
            "failure_contribution_pct": e["failure_contribution_pct"],
        }
        for e in analysis.entity_failure_contributions.get("enb", [])
        if e.get("success", 1) == 0 or e.get("failure_contribution_pct", 0) >= 20.0
    ]

    # 가입자 분포
    mobility = analysis.subscriber_mobility_summary or {}
    affected = int(mobility.get("affected_imsi_count") or 0) or 1
    repeated = int(mobility.get("repeated_failure_imsi_count") or 0)
    repeated_ratio = round(repeated / affected * 100, 1)

    # 실패율 높은 절차 (5% 이상만)
    high_failure_rate_procedures = {
        ct: rate
        for ct, rate in analysis.call_type_failure_rate.items()
        if rate >= 5.0
    }

    # MME 기여율 상위
    top_mme = [
        {
            "entity_id": e["entity_id"],
            "failures": e["failures"],
            "failure_contribution_pct": e["failure_contribution_pct"],
        }
        for e in analysis.entity_failure_contributions.get("mme", [])
    ]

    return {
        "pattern_counts": {
            "ran_candidate_count": ran_count,
            "ran_candidate_pct": round(ran_count / total * 100, 1),
            "core_candidate_count": core_count,
            "core_candidate_pct": round(core_count / total * 100, 1),
            "note": "eNB 집중도 기반 사전 분류. 최종 판단은 LLM이 수행.",
        },
        "concentration": {
            "critical_enb": critical_enb,
            "note": "success=0 또는 기여율 20% 이상 eNB.",
        },
        "subscriber": {
            "repeated_failure_ratio": repeated_ratio,
            "affected_imsi_count": affected,
            "repeated_failure_imsi_count": repeated,
            "note": "반복 실패 비율과 집중도 기반으로 LLM이 영향도 판단.",
        },
        "high_failure_rate_procedures": high_failure_rate_procedures,
        "top_mme": top_mme,
    }


def _build_failure_flow(error_chains: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    error_chains의 first_error → last_error를
    사람이 읽기 쉬운 Failure Flow 형태로 변환.
    동일한 first/last면 단일 노드 장애로 표현.
    """
    flows = []
    for chain in error_chains:
        first = chain.get("first_error", {})
        last = chain.get("last_error", {})
        first_msg = first.get("message", "-")
        first_cause = first.get("cause", "-")
        last_msg = last.get("message", "-")
        last_cause = last.get("cause", "-")

        is_single = (first_msg == last_msg and first_cause == last_cause)
        flows.append({
            "call_type": chain.get("call_type", "-"),
            "first_message": first_msg,
            "first_cause": first_cause,
            "last_message": last_msg,
            "last_cause": last_cause,
            "is_single_node": is_single,
            "count": chain.get("count", 0),
        })
    flows.sort(key=lambda x: x["count"], reverse=True)
    return flows


def build_compact_rca_ir(analysis: RcaAnalysis) -> dict[str, Any]:
    """Compact RCA IR used by the LLM reasoning path."""
    stage_counter: Counter[str] = Counter()
    for chain in analysis.failure_chains:
        stage_counter[chain.failure_point] += 1

    rep_chains = []
    seen: set[tuple[int, str, str, str, str]] = set()
    for chain in analysis.failure_chains:
        item = {
            "call_type_code": chain.call_type,
            "call_type": get_call_type_name(chain.call_type),
            "procedure": chain.procedure,
            "interface": chain.failure_interface,
            "message": chain.failure_message,
            "failure_point": chain.failure_point,
            "cause": chain.failure_cause_name,
        }
        key = (
            item["call_type_code"],
            item["procedure"],
            item["interface"],
            item["failure_point"],
            item["cause"],
        )
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
    shared_data = _compact_shared_failures(analysis.shared_failure_signatures)
    return {
        "statistics": {
            "llm": True,
            "data": {
                "total_records": analysis.total_records,
                "attempt_count": analysis.attempt_count,
                "success_count": analysis.success_count,
                "failure_count": analysis.failure_count,
                "failure_rate": round(analysis.failure_rate, 2),
            },
        },
        "call_type_distribution": {
            "llm": False,   # 전체 건수는 노이즈 — LLM에 미전달
            "data": dict(analysis.call_type_distribution),
        },
        "call_type_failure_summary": {
            "llm": True,
            "data": {
                ct: {
                    "total": cnt,
                    "failure_rate": analysis.call_type_failure_rate.get(ct, 0),
                }
                for ct, cnt in analysis.call_type_distribution.items()
                if analysis.call_type_failure_rate.get(ct, 0) > 0
            },
        },
        # shared_failure_observations로 커버되므로 off
        "interface_failure_distribution": {
            "llm": False,
            "data": dict(analysis.interface_distribution),
        },
        # shared_failure_observations로 커버되므로 off
        "failure_stage_distribution": {
            "llm": False,
            "data": dict(stage_counter),
        },
        # error_chains + shared_failure_observations로 커버되므로 off
        "representative_chains": {
            "llm": False,
            "data": rep_chains,
        },
        "error_chains": {
            "llm": True,
            "data": analysis.error_chains,
        },
        "failure_flow": {
            "llm": True,
            "data": _build_failure_flow(analysis.error_chains),
        },
        "entity_failure_contribution": {
            "llm": True,
            "data": {
                "top_mme": analysis.entity_failure_contributions.get("mme", []),
                "top_enb": analysis.entity_failure_contributions.get("enb", []),
                "top_sgw": analysis.entity_failure_contributions.get("sgw", []),
            },
        },
        "shared_failure_observations": {
            "llm": True,
            "data": shared_data,
        },
        "rca_hints": {
            "llm": True,
            "data": _build_rca_hints(analysis, shared_data),
        },
        "subscriber_summary": {
            "llm": True,
            "data": _build_subscriber_summary(
                subscriber_patterns,
                analysis.subscriber_mobility_summary,
            ),
        },
        "burst_detected": {
            "llm": True,
            "data": bool(analysis.burst_detected),
        },
    }


def _get_data(ir: dict[str, Any], key: str, default: Any = None) -> Any:
    """compact_rca_ir에서 data 값 추출. 구버전 호환(플래그 없는 dict)도 지원."""
    val = ir.get(key, default)
    if isinstance(val, dict) and "data" in val:
        return val["data"]
    return val if val is not None else default


def _is_llm(ir: dict[str, Any], key: str) -> bool:
    """해당 섹션의 llm 플래그 반환. 플래그 없으면 True."""
    val = ir.get(key)
    if isinstance(val, dict) and "llm" in val:
        return bool(val["llm"])
    return True


def _ir_to_markdown(ir: dict[str, Any]) -> str:
    """compact_rca_ir → 화면용 마크다운 테이블. llm 플래그 무시하고 전체 출력."""
    stats = _get_data(ir, "statistics", {})
    burst = _get_data(ir, "burst_detected", False)
    burst_val = "감지됨" if burst else "없음"

    lines = [
        "## RCA Observability Summary",
        " ",
        "### 통계",
        "| 항목 | 값 |",
        "|---|---|",
        f"| 총 레코드 | {stats.get('total_records', 0):,}건 |",
        f"| 시도 | {stats.get('attempt_count', 0):,}건 |",
        f"| 성공 | {stats.get('success_count', 0):,}건 |",
        f"| 실패 | {stats.get('failure_count', 0):,}건 |",
        f"| 실패율 | {stats.get('failure_rate', 0):.2f}% |",
        f"| Burst 감지 | {burst_val} |",
    ]

    # Call Type 분포 (전체 건수 + 실패율)
    call_type_dist = _get_data(ir, "call_type_distribution", {})
    call_type_failure_summary = _get_data(ir, "call_type_failure_summary", {})
    if call_type_dist:
        lines += [
            " ",
            "### Call Type 분포",
            "| Call Type | 건수 | 실패율 |",
            "|---|---:|---:|",
        ]
        for ct, cnt in sorted(call_type_dist.items(), key=lambda x: x[1], reverse=True):
            fr = call_type_failure_summary.get(ct, {}).get("failure_rate", 0.0) \
                if isinstance(call_type_failure_summary.get(ct), dict) \
                else 0.0
            lines.append(f"| {ct} | {cnt:,} | {fr}% |")

    # Interface Failure 분포
    iface_dist = _get_data(ir, "interface_failure_distribution", {})
    if iface_dist:
        lines += [
            " ",
            "### Interface Failure 분포",
            "| Interface | 건수 |",
            "|---|---|",
        ]
        for iface, cnt in sorted(iface_dist.items(), key=lambda x: x[1], reverse=True)[:8]:
            lines.append(f"| {iface} | {cnt:,} |")

    # Failure Stage 분포
    stage_dist = _get_data(ir, "failure_stage_distribution", {})
    if stage_dist:
        lines += [
            " ",
            "### Failure Stage 분포",
            "| Stage | 건수 |",
            "|---|---|",
        ]
        for stage, cnt in sorted(stage_dist.items(), key=lambda x: x[1], reverse=True)[:8]:
            lines.append(f"| {stage} | {cnt:,} |")

    # MME / eNB / SGW Failure Contribution
    entity = _get_data(ir, "entity_failure_contribution", {})
    for label, key in [("MME", "top_mme"), ("eNB", "top_enb"), ("SGW", "top_sgw")]:
        rows = entity.get(key, [])
        if not rows:
            continue
        lines += [
            " ",
            f"### {label} Failure Contribution",
            "| Entity | Attempts | Failures | Failure Contribution | Top Failure Pattern |",
            "|---|---:|---:|---:|---|",
        ]
        for row in rows:
            patterns = row.get("top_failure_patterns", [])
            pattern_text = ", ".join(
                f"{p.get('call_type') or '-'} / {p.get('interface') or '-'} / "
                f"{p.get('message') or '-'} / {p.get('stage') or '-'} / "
                f"{p.get('cause')}({p.get('count')})"
                for p in patterns
                if p.get("cause") and p.get("count") is not None
            ) or "-"
            lines.append(
                f"| {row.get('entity_id')} | {row.get('attempts', 0):,} "
                f"| {row.get('failures', 0):,} "
                f"| {row.get('failure_contribution_pct', 0)}% | {pattern_text} |"
            )

    # Subscriber Summary
    subscriber = _get_data(ir, "subscriber_summary", {})
    if subscriber:
        affected = subscriber.get("affected_imsi_count", 0)
        repeated = subscriber.get("repeated_failure_imsi_count", 0)
        ratio = subscriber.get("repeated_failure_ratio", 0)
        lines += [
            " ",
            "### Subscriber Summary",
            f"- Affected IMSI: {affected:,}",
            f"- Single Failure IMSI: {subscriber.get('single_failure_imsi_count', 0):,}",
            f"- Repeated Failure IMSI: {repeated:,} ({ratio}%)",
            f"- Multi MME IMSI: {subscriber.get('multi_mme_imsi_count', 0):,}",
            f"- Multi eNB IMSI: {subscriber.get('multi_enb_imsi_count', 0):,}",
            f"- Zero Success IMSI: {subscriber.get('zero_success_imsi_count', 0):,}",
            f"- Top IMSI Failure Share: {subscriber.get('top_imsi_failure_share', 0)}%",
        ]

    # 사전 분석 데이터
    hints = _get_data(ir, "rca_hints", {})
    if hints:
        pattern_counts = hints.get("pattern_counts", {})
        procedures = hints.get("high_failure_rate_procedures", {})

        lines += [
            " ",
            "### 사전 분석 데이터",
        ]

        if pattern_counts:
            lines += [
                "| 구분 | 건수 | 비율 |",
                "|---|---:|---:|",
                f"| RAN 후보 패턴 | "
                f"{pattern_counts.get('ran_candidate_count', 0)}건 | "
                f"{pattern_counts.get('ran_candidate_pct', 0)}% |",
                f"| Core 후보 패턴 | "
                f"{pattern_counts.get('core_candidate_count', 0)}건 | "
                f"{pattern_counts.get('core_candidate_pct', 0)}% |",
            ]

        if procedures:
            lines += [" ", "| 절차 | 실패율 |", "|---|---:|"]
            for ct, rate in sorted(procedures.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"| {ct} | {rate}% |")

    # Top Error Chains
    error_chains = _get_data(ir, "error_chains", [])
    if error_chains:
        lines += [
            " ",
            "### Top Error Chains",
            "| Call Type | First Error | Last Error | Count |",
            "|---|---|---|---:|",
        ]
        for row in error_chains[:8]:
            first = row.get("first_error", {})
            last = row.get("last_error", {})
            first_text = (
                f"{first.get('interface') or '-'} / "
                f"{first.get('message') or '-'} / "
                f"{first.get('cause') or '-'}"
            )
            last_text = (
                f"{last.get('interface') or '-'} / "
                f"{last.get('message') or '-'} / "
                f"{last.get('cause') or '-'}"
            )
            lines.append(
                f"| {row.get('call_type') or '-'} "
                f"| {first_text} | {last_text} | {row.get('count', 0):,} |"
            )

    # Failure Flow Summary
    failure_flow = _get_data(ir, "failure_flow", [])
    if failure_flow:
        lines += [
            " ",
            "### Failure Flow Summary",
            "| Call Type | Flow | 건수 |",
            "|---|---|---:|",
        ]
        for flow in failure_flow[:8]:
            call_type = flow.get("call_type", "-")
            first_msg = flow.get("first_message", "-")
            first_cause = flow.get("first_cause", "-")
            last_msg = flow.get("last_message", "-")
            last_cause = flow.get("last_cause", "-")
            count = flow.get("count", 0)
            if flow.get("is_single_node", False):
                flow_text = f"{first_msg}({first_cause}) → (단일)"
            else:
                flow_text = f"{first_msg}({first_cause}) → {last_msg}({last_cause})"
            lines.append(f"| {call_type} | {flow_text} | {count:,} |")

    # 유형별 실패 통계 (shared_failure_observations)
    shared = _get_data(ir, "shared_failure_observations", [])
    if shared:
        lines += [
            " ",
            "### 유형별 실패 통계",
            "| Call Type | Interface | Message | Stage | Cause | Count | IMSI | MME | eNB |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for s in shared[:8]:
            lines.append(
                f"| {s.get('call_type') or '-'} | {s.get('interface') or '-'} "
                f"| {s.get('message') or '-'} | {s.get('stage') or '-'} "
                f"| {s.get('cause') or '-'} | {s.get('count', 0)} "
                f"| {s.get('affected_imsi_count', 0)} "
                f"| {s.get('affected_mme_count', 0)} "
                f"| {s.get('affected_enb_count', 0)} |"
            )

    return "\n".join(lines)


def build_compact_reasoning_json(observability: dict[str, Any]) -> dict[str, Any]:
    """
    LLM causal reasoning 전용 compact payload.
    Full observability는 보존하되 reasoning 호출에는 raw timeline/긴 chain/APN/timestamp를 전달하지 않는다.
    """
    stats = observability.get("statistics", {})
    rep_chains = []
    for chain in observability.get("representative_chains", [])[:10]:
        rep_chains.append({
            "call_type_code": chain.get("call_type_code"),
            "call_type": chain.get("call_type"),
            "procedure": chain.get("procedure"),
            "interface": chain.get("interface"),
            "message": chain.get("message"),
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
            "call_type_code": row.get("call_type_code"),
            "call_type": row.get("call_type"),
            "interface": row.get("interface"),
            "message": row.get("message"),
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
        "error_chains": observability.get("error_chains", []),
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
        "entity_failure_contribution": _get_data(compact_rca_ir, "entity_failure_contribution", {}),
        "shared_failure_observations": _get_data(compact_rca_ir, "shared_failure_observations", []),
        "interface_failure_distribution": _get_data(compact_rca_ir, "interface_failure_distribution", {}),
        "failure_stage_distribution": _get_data(compact_rca_ir, "failure_stage_distribution", {}),
    }
    return build_loop_step_messages("step1", payload)


def build_loop_step2_messages(compact_rca_ir: dict[str, Any]) -> list[dict[str, str]]:
    patterns = sorted(
        _get_data(compact_rca_ir, "subscriber_failure_patterns", []),
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
        "statistics": _get_data(compact_rca_ir, "statistics", {}),
        "subscriber_failure_patterns": compact_patterns,
        "subscriber_mobility_summary": _get_data(compact_rca_ir, "subscriber_mobility_summary", {}),
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
    # Report 렌더링에 필요한 핵심 통계만 전달 (토큰 절감)
    compact_summary = {
        k: compact_rca_ir.get(k)
        for k in (
            "statistics",
            "call_type_distribution",
            "interface_failure_distribution",
            "failure_stage_distribution",
            "entity_failure_contribution",
            "shared_failure_observations",
            "error_chains",
            "subscriber_summary",
            "burst_detected",
        )
        if k in compact_rca_ir
    }
    ir_json = json.dumps(compact_summary, ensure_ascii=False, indent=2)

    # reasoning이 너무 길면 앞부분만 사용
    if isinstance(reasoning, str):
        reasoning_text = reasoning[:4000]
    else:
        reasoning_text = json.dumps(reasoning, ensure_ascii=False)[:4000]

    system = (
        "당신은 LTE/EPC 운영 보고서 작성자입니다. "
        "새로운 RCA 판단을 하지 말고, 제공된 데이터와 reasoning 결과를 운영자용 markdown report로 렌더링만 하세요. "
        "reasoning 결과를 변경하거나 보강하지 마세요."
    )
    user = f"""\
아래 RCA 통계 요약과 LLM reasoning 결과만 기반으로 운영자용 markdown report를 작성하세요.

중요:
- 새로운 원인 판단 금지
- reasoning 결과를 그대로 반영
- 제공된 데이터에 없는 장비/IMSI/원인/통계 생성 금지
- markdown table 사용

[RCA 통계 요약]
{ir_json}

[LLM reasoning result]
{reasoning_text}
"""
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_gemma4_system_prompt() -> str:
    return """\
당신은 LTE/EPC 네트워크 장애 분석 전문가다.
3GPP TS 23.401, 24.301, 29.272, 29.274 기반으로 분석한다.
아래 제공된 데이터를 기반으로 장애 흐름과 패턴 간 상관관계를 분석하고 영향도를 평가한다.

출력 규칙:
- 반드시 한국어로 작성한다.
- 데이터에 있는 장비명, interface, message, cause, 수치를 그대로 인용한다.
- 데이터에 없는 장비, IMSI, Cause, Interface를 생성하지 않는다.
- 확정할 수 없는 내용은 반드시 "가능성" 또는 "추가 확인 필요"로 표현한다.
- 데이터에 없는 원인을 확정적으로 기술하지 않는다.
- LTE/EPC 일반 지식은 사용 가능하나 데이터 근거 없이 원인을 단정하지 않는다.

영향도 평가 기준:
- High: 해당 Domain 장애가 전체 실패의 30% 이상이거나 특정 장비에 집중
- Medium: 전체 실패의 10~30% 또는 복수 장비에 분산
- Low: 전체 실패의 10% 미만 또는 단발성
"""


def _format_gemma_user_message(observation: dict[str, Any]) -> str:
    stats = _get_data(observation, "statistics", {})
    entity = _get_data(observation, "entity_failure_contribution", {}) \
        if _is_llm(observation, "entity_failure_contribution") else {}
    # shared = _get_data(...) if _is_llm(...) else []  # 장애 패턴 그룹으로 대체됨
    subscriber = _get_data(observation, "subscriber_summary", {}) \
        if _is_llm(observation, "subscriber_summary") else {}
    call_type_failure_summary = _get_data(observation, "call_type_failure_summary", {}) \
        if _is_llm(observation, "call_type_failure_summary") else {}
    # error_chains = _get_data(...) if _is_llm(...) else []  # Failure Flow로 대체됨
    failure_flow = _get_data(observation, "failure_flow", []) \
        if _is_llm(observation, "failure_flow") else []
    hints = _get_data(observation, "rca_hints", {}) \
        if _is_llm(observation, "rca_hints") else {}

    top_mme = entity.get("top_mme", []) if _is_llm(observation, "entity_failure_contribution") else []
    top_enb = entity.get("top_enb", []) if _is_llm(observation, "entity_failure_contribution") else []

    lines = []

    # 통계 (llm=True)
    lines += [
        "## 장애 통계",
        f"- 총 레코드: {stats.get('total_records', 0):,}건",
        f"- 시도: {stats.get('attempt_count', 0):,}건",
        f"- 실패: {stats.get('failure_count', 0):,}건",
        f"- 실패율: {stats.get('failure_rate', 0)}%",
        "",
    ]

    if call_type_failure_summary:
        lines.append("## 절차별 실패율")
        for ct, info in call_type_failure_summary.items():
            if isinstance(info, dict):
                lines.append(
                    f"- {ct}: 전체 {info['total']:,}건 중 실패율 {info['failure_rate']}%"
                )
        lines.append("")

    if top_mme:
        lines.append("## MME 장애 기여")
        for mme in top_mme:
            lines.append(
                f"- MME {mme['entity_id']}: "
                f"{mme['failures']}건 실패, 기여율 {mme['failure_contribution_pct']}%"
            )
            for p in mme.get("top_failure_patterns", []):
                lines.append(
                    f"  - {p.get('call_type', '-')} / {p['interface']} / "
                    f"{p.get('message', '-')} / {p['stage']} / {p['cause']}: {p['count']}건"
                )
        lines.append("")

    if top_enb:
        lines.append("## eNB 장애 기여")
        for enb in top_enb:
            lines.append(
                f"- eNB {enb['entity_id']}: "
                f"{enb['failures']}건 실패 (성공 {enb['success']}건), "
                f"기여율 {enb['failure_contribution_pct']}%"
            )
            for p in enb.get("top_failure_patterns", []):
                lines.append(
                    f"  - {p.get('call_type', '-')} / {p['interface']} / "
                    f"{p.get('message', '-')} / {p['stage']} / {p['cause']}: {p['count']}건"
                )
        lines.append("")

    # if shared:  # 장애 패턴 그룹으로 대체됨
    #     lines.append("## 반복 장애 패턴")
    #     for s in shared:
    #         enb_count = s['affected_enb_count']
    #         enb_label = "[집중]" if enb_count <= 2 else "[분산]"
    #         lines.append(
    #             f"- {s.get('call_type', '-')} / {s.get('interface', '-')} / "
    #             f"{s.get('message', '-')} / {s.get('stage', '-')} / {s.get('cause', '-')}: "
    #             f"{s['count']}건, "
    #             f"영향 IMSI {s['affected_imsi_count']}명, "
    #             f"MME {s['affected_mme_count']}개, "
    #             f"eNB {enb_count}개 {enb_label}"
    #         )
    #     lines.append("")

    if failure_flow:
        lines.append("## Failure Flow Summary")
        lines.append("각 장애의 시작점과 종료점을 나타낸다.")
        lines.append("")
        for flow in failure_flow:
            call_type = flow.get("call_type", "-")
            first_msg = flow.get("first_message", "-")
            first_cause = flow.get("first_cause", "-")
            last_msg = flow.get("last_message", "-")
            last_cause = flow.get("last_cause", "-")
            count = flow.get("count", 0)
            is_single = flow.get("is_single_node", False)
            if is_single:
                lines.append(
                    f"- [{call_type}] {first_msg}({first_cause}) "
                    f"→ (단일 노드 장애) ({count}건)"
                )
            else:
                lines.append(
                    f"- [{call_type}] {first_msg}({first_cause}) "
                    f"→ {last_msg}({last_cause}) ({count}건)"
                )
        lines.append("")

    # 패턴 그룹화: eNB 집중도 기반 (shared 대신 _get_data 직접 호출)
    ran_patterns = [
        s for s in _get_data(observation, "shared_failure_observations", [])
        if _is_llm(observation, "shared_failure_observations")
        and s.get("affected_enb_count", 0) <= 2
    ]
    core_patterns = [
        s for s in _get_data(observation, "shared_failure_observations", [])
        if _is_llm(observation, "shared_failure_observations")
        and s.get("affected_enb_count", 0) > 2
    ]

    if ran_patterns or core_patterns:
        lines.append("## 장애 패턴 그룹")
        lines.append("eNB 집중도 기반으로 사전 분류한 결과다. 최종 판단은 LLM이 수행한다.")
        lines.append("")

        if ran_patterns:
            lines.append("### RAN/Access 후보 패턴 (eNB 집중)")
            for s in ran_patterns:
                enb_count = s["affected_enb_count"]
                lines.append(
                    f"- {s.get('call_type', '-')} / {s.get('interface', '-')} / "
                    f"{s.get('message', '-')} / {s.get('cause', '-')}: "
                    f"{s['count']}건, eNB {enb_count}개"
                )
            lines.append("")

        if core_patterns:
            lines.append("### Core Network 후보 패턴 (eNB 분산)")
            for s in core_patterns:
                enb_count = s["affected_enb_count"]
                lines.append(
                    f"- {s.get('call_type', '-')} / {s.get('interface', '-')} / "
                    f"{s.get('message', '-')} / {s.get('cause', '-')}: "
                    f"{s['count']}건, eNB {enb_count}개"
                )
            lines.append("")

    # if error_chains:  # Failure Flow로 대체됨
    #     lines.append("## Top Error Chains")
    #     for row in error_chains[:10]:
    #         first = row.get("first_error", {})
    #         last = row.get("last_error", {})
    #         lines.append(
    #             f"- {row.get('call_type', '-')}: "
    #             f"First {first.get('interface', '-')} / "
    #             f"{first.get('message', '-')} / {first.get('cause', '-')} "
    #             f"→ Last {last.get('interface', '-')} / "
    #             f"{last.get('message', '-')} / {last.get('cause', '-')} "
    #             f"({row.get('count', 0)}건)"
    #         )
    #     lines.append("")

    if subscriber:
        lines += [
            "## 가입자 요약",
            f"- 영향 IMSI: {subscriber.get('affected_imsi_count', 0):,}명",
            f"- 반복 실패 IMSI: {subscriber.get('repeated_failure_imsi_count', 0)}명 "
            f"({subscriber.get('repeated_failure_ratio', 0)}%)",
            f"- Zero Success IMSI: {subscriber.get('zero_success_imsi_count', 0)}명",
            f"- Top IMSI Failure Share: {subscriber.get('top_imsi_failure_share', 0)}%",
            "",
        ]

    if hints:
        pattern_counts = hints.get("pattern_counts", {})
        concentration = hints.get("concentration", {})
        subscriber_hint = hints.get("subscriber", {})
        procedures = hints.get("high_failure_rate_procedures", {})
        top_mme_hint = hints.get("top_mme", [])
        critical_enb = concentration.get("critical_enb", [])

        lines += [
            "## 사전 분석 데이터",
            "아래는 Backend가 계산한 관찰 사실이다. 영향도와 원인 판단은 LLM이 수행한다.",
            "",
        ]

        if pattern_counts:
            lines += [
                "### 패턴 건수 (eNB 집중도 기반 분류)",
                f"- RAN 후보 패턴 합계: {pattern_counts.get('ran_candidate_count', 0)}건 "
                f"({pattern_counts.get('ran_candidate_pct', 0)}%)",
                f"- Core 후보 패턴 합계: {pattern_counts.get('core_candidate_count', 0)}건 "
                f"({pattern_counts.get('core_candidate_pct', 0)}%)",
                "",
            ]

        if critical_enb:
            lines.append("### 집중 장애 eNB")
            for enb in critical_enb:
                success = enb.get("success", -1)
                success_str = f"성공 {success}건" if success >= 0 else ""
                lines.append(
                    f"- eNB {enb['entity_id']}: "
                    f"{enb['failures']}건 실패 {success_str}, "
                    f"기여율 {enb['failure_contribution_pct']}%"
                )
            lines.append("")

        if subscriber_hint:
            lines += [
                "### 가입자 분포",
                f"- 반복 실패 IMSI: {subscriber_hint.get('repeated_failure_imsi_count', 0)}명 / "
                f"{subscriber_hint.get('affected_imsi_count', 0)}명 "
                f"({subscriber_hint.get('repeated_failure_ratio', 0)}%)",
                "",
            ]

        if procedures:
            lines.append("### 높은 실패율 절차")
            for ct, rate in sorted(procedures.items(), key=lambda x: x[1], reverse=True):
                lines.append(f"- {ct}: {rate}%")
            lines.append("")

        if top_mme_hint:
            lines.append("### MME 기여율")
            for mme in top_mme_hint:
                lines.append(
                    f"- MME {mme['entity_id']}: "
                    f"{mme['failures']}건, "
                    f"기여율 {mme['failure_contribution_pct']}%"
                )
            lines.append("")

    lines += [
        "---",
        "",
        "위 데이터를 기반으로 아래 순서로 분석하세요.",
        "call_type, 장비명, interface, message, cause, 수치는 데이터 그대로 인용하세요.",
        "데이터에 없는 값은 생성하지 마세요.",
        "확정할 수 없는 내용은 '가능성' 또는 '추가 확인 필요'로 표현하세요.",
        "",
        "1. Failure Flow 분석",
        "   - 각 Flow의 시작/종료 메시지가 3GPP 절차상 어느 구간 장애인지 설명",
        "   - RAN 후보 / Core 후보 그룹의 타당성 검토 및 필요시 재분류",
        "",
        "2. 영향도 평가 (아래 테이블로 출력)",
        "   위 사전 분석 데이터의 수치를 근거로 판단하세요.",
        "   건수가 많다고 High가 아닙니다.",
        "   해당 Domain 장애가 서비스에 미치는 실질적 영향을 기준으로 판단하세요.",
        "   Subscriber/UE 영향도는 반드시 가입자 분포의 반복 실패 비율을 근거로 판단하세요.",
        "   | 구분 | 영향도 | 주요 근거 |",
        "   |---|---|---|",
        "   | RAN/Access | High/Medium/Low | 근거 |",
        "   | Core Network | High/Medium/Low | 근거 |",
        "   | Subscriber/UE | High/Medium/Low | 근거 |",
        "",
        "3. 최종 RCA",
        "   - 영향도 High인 Domain부터 장애 위치와 조치 방향 작성",
        "   - 조치 방향은 데이터에 있는 장비/인터페이스 기준으로만 작성",
    ]

    return "\n".join(lines)


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
    return [
        {"role": "system", "content": build_gemma4_system_prompt()},
        {"role": "user", "content": _format_gemma_user_message(observation)},
    ]
