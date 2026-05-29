"""
analyzer.py
전체 레코드 통계 분석 + FailureChain 생성.
"""
from __future__ import annotations

import gc
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import polars as pl

from app.rca.chain_builder import FailureChain, build_failure_chain
from app.rca.normalizer import NormalizedEvent, normalize_record
from app.rca.parser import XdrRecord
from app.rca.procedures import get_procedure_name
from app.rca.spec_loader import get_call_type_name, get_cause_name, get_interface_name

# Interface / message code constants (mirrors chain_builder.py)
_IFACE_S6A   = 1
_IFACE_S1AP  = 2
_IFACE_S11   = 3
_IFACE_S10   = 4
_IFACE_EMM   = 5
_IFACE_ESM   = 6
_MSG_AIR_AIA = 318
_MSG_ULR_ULA = 316


def _interface_msg_to_stage(fi: int, fm: int) -> str:
    if fi == _IFACE_S6A:
        return "AUTH_REQUEST" if fm == _MSG_AIR_AIA else "UPDATE_LOCATION"
    if fi == _IFACE_S1AP:
        return "INITIAL_CONTEXT_SETUP"
    if fi in (_IFACE_S11, _IFACE_S10):
        return "CREATE_SESSION"
    if fi == _IFACE_EMM:
        return "NAS_EMM"
    if fi == _IFACE_ESM:
        return "NAS_ESM"
    return "UNKNOWN"


class CountOnlySet:
    def __init__(self, count: int):
        self.count = count

    def __len__(self) -> int:
        return self.count

    def __bool__(self) -> bool:
        return self.count > 0


class CountedDict(dict):
    def __init__(self, *args, total_count: int = 0, **kwargs):
        super().__init__(*args, **kwargs)
        self.total_count = total_count or super().__len__()

    def __len__(self) -> int:
        return self.total_count


@dataclass
class RcaAnalysis:
    # 기본 통계
    total_records: int
    attempt_count: int
    success_count: int
    failure_count: int
    failure_rate: float           # percentage (0~100)

    # 호 유형별
    call_type_distribution: Dict[str, int]
    call_type_failure_rate: Dict[str, float]

    # 에러 분포
    interface_distribution: Dict[str, int]    # first_error_interface 기준

    # 영향 범위
    affected_imsi_set: Any
    affected_mme_ids: Dict[int, int]          # mme_id → failure count
    affected_enb_ids: Dict[str, int]          # enb_id → failure count
    affected_apns: Dict[str, int]

    # Failure Chains
    failure_chains: List[FailureChain]
    top_failed_imsi_sequences: List[dict]

    # 반복 패턴 (동일 IMSI 반복 실패)
    repeated_failures: Dict[str, list]        # imsi → [chain, ...]

    # 버스트 감지 (시간대별 집중)
    time_distribution: Dict[str, int]         # "HH:MM" → count (10분 단위)
    burst_detected: bool
    burst_window: Optional[str]               # "HH:MM - HH:MM"

    # 파싱 통계
    parse_stats: dict

    # Equipment baseline: per-device attempt/success/failure/failure_rate/anomaly_ratio
    mme_baseline: List[Dict[str, Any]] = field(default_factory=list)
    enb_baseline: List[Dict[str, Any]] = field(default_factory=list)

    # Shared failure signatures: same (interface, stage, cause) across multiple devices/IMSIs
    shared_failure_signatures: List[Dict[str, Any]] = field(default_factory=list)


def _bucket_10min(ts: float) -> str:
    """epoch seconds → 10분 단위 버킷 "HH:MM"."""
    try:
        if ts > 1e12:
            ts /= 1_000_000  # microseconds → seconds
        dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        minute_bucket = (dt.minute // 10) * 10
        return f"{dt.hour:02d}:{minute_bucket:02d}"
    except Exception:
        return "00:00"


def _format_timestamp(ts: float) -> str:
    try:
        if ts > 1e12:
            ts /= 1_000_000
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def _counter_from_grouped(df: pl.DataFrame, key: str, value: str = "len", name_mapper=None) -> dict:
    out = {}
    for row in df.iter_rows(named=True):
        k = row[key]
        if name_mapper:
            k = name_mapper(k)
        out[k] = row[value]
    return out


def _collect_count(lf: pl.LazyFrame) -> int:
    return int(lf.select(pl.len()).collect().item())


def _top_counted_dict_lf(lf: pl.LazyFrame, key: str, total_unique: int, limit: int = 100) -> CountedDict:
    if total_unique <= 0:
        return CountedDict(total_count=0)
    grouped = lf.group_by(key).len().sort("len", descending=True).head(limit).collect()
    data = {row[key]: row["len"] for row in grouped.iter_rows(named=True) if row[key] not in (None, "")}
    del grouped
    return CountedDict(data, total_count=total_unique)


def _time_distribution_lf(lf: pl.LazyFrame) -> Counter[str]:
    ts = pl.col("call_start_time")
    seconds = pl.when(ts > 1_000_000_000_000).then(ts / 1_000_000).otherwise(ts)
    bucket = ((seconds // 600) * 600).cast(pl.Int64).alias("bucket")
    grouped = (
        lf.select(bucket)
        .group_by("bucket")
        .len()
        .collect()
    )
    out: Counter[str] = Counter()
    for row in grouped.iter_rows(named=True):
        out[_bucket_10min(float(row["bucket"] or 0))] += row["len"]
    del grouped
    return out


def _record_from_row(row: dict) -> XdrRecord:
    return XdrRecord(
        imsi=str(row.get("imsi") or ""),
        mme_id=int(row.get("mme_id") or 0),
        first_enb_id=str(row.get("first_enb_id") or ""),
        call_type=int(row.get("call_type") or 0),
        call_start_time=float(row.get("call_start_time") or 0.0),
        apn=str(row.get("apn") or ""),
        auth_info_cause=int(row.get("auth_info_cause") or 0),
        update_location_cause=int(row.get("update_location_cause") or 0),
        s1ap_error_message=int(row.get("s1ap_error_message") or 0),
        s1ap_error_cause=int(row.get("s1ap_error_cause") or 0),
        emm_error_message=int(row.get("emm_error_message") or 0),
        emm_error_cause=int(row.get("emm_error_cause") or 0),
        esm_error_message=int(row.get("esm_error_message") or 0),
        esm_error_cause=int(row.get("esm_error_cause") or 0),
        s11_error_message=int(row.get("s11_error_message") or 0),
        s11_error_cause=int(row.get("s11_error_cause") or 0),
        attempt_flag=int(row.get("attempt_flag") or 0),
        success_flag=int(row.get("success_flag") or 0),
        drop_flag=int(row.get("drop_flag") or 0),
        auth_attempt_flag=int(row.get("auth_attempt_flag") or 0),
        auth_success_flag=int(row.get("auth_success_flag") or 0),
        location_attempt_flag=int(row.get("location_attempt_flag") or 0),
        location_success_flag=int(row.get("location_success_flag") or 0),
        first_error_interface=int(row.get("first_error_interface") or 0),
        first_error_message=int(row.get("first_error_message") or 0),
        first_error_cause=int(row.get("first_error_cause") or 0),
        last_error_interface=int(row.get("last_error_interface") or 0),
        last_error_message=int(row.get("last_error_message") or 0),
        last_error_cause=int(row.get("last_error_cause") or 0),
    )


def _build_failure_event(row: dict) -> dict:
    rec = _record_from_row(row)
    try:
        events: List[NormalizedEvent] = normalize_record(rec)
        chain = build_failure_chain(rec, events)
    except Exception:
        chain = None

    event = {
        "timestamp": _format_timestamp(rec.call_start_time),
        "type": "FAILURE",
        "procedure": chain.procedure if chain else get_call_type_name(rec.call_type),
        "stage": chain.failure_point if chain else "UNKNOWN",
        "interface": chain.failure_interface if chain else get_interface_name(rec.first_error_interface),
        "cause": chain.failure_cause_name if chain else str(rec.first_error_cause),
        "mme": str(rec.mme_id),
        "enb": rec.first_enb_id,
        "apn": rec.apn,
    }
    del rec
    return event


def _top_failed_imsi_sequences(
    attempt_lf: pl.LazyFrame,
    failure_lf: pl.LazyFrame,
    global_failure_rate: float,
    threshold: int = 5,
    top_n: int = 10,
) -> list[dict]:
    top_imsi_df = (
        failure_lf.filter(pl.col("imsi") != "")
        .group_by("imsi")
        .len()
        .sort("len", descending=True)
        .head(top_n)
        .collect()
    )
    top_imsis = [row["imsi"] for row in top_imsi_df.iter_rows(named=True) if row["len"] >= threshold]
    del top_imsi_df

    # Per-IMSI stats (attempts/success/failures/failure_rate/anomaly_ratio)
    if top_imsis:
        istats_df = (
            attempt_lf
            .filter(pl.col("imsi").is_in(top_imsis))
            .group_by("imsi")
            .agg([
                pl.len().alias("attempts"),
                pl.col("success_flag").sum().cast(pl.Int64).alias("success"),
            ])
            .with_columns([
                (pl.col("attempts") - pl.col("success")).alias("failures"),
                (
                    (pl.col("attempts") - pl.col("success")).cast(pl.Float64)
                    / pl.col("attempts") * 100
                ).round(2).alias("failure_rate"),
            ])
            .collect()
        )
        imsi_stats: dict[str, dict] = {row["imsi"]: dict(row) for row in istats_df.iter_rows(named=True)}
        del istats_df
    else:
        imsi_stats = {}

    sequences: list[dict] = []
    for imsi in top_imsis:
        st = imsi_stats.get(imsi, {})
        fr = float(st.get("failure_rate") or 0)
        event_df = (
            attempt_lf
            .filter(pl.col("imsi") == imsi)
            .sort("call_start_time")
            .collect()
        )
        total_events = event_df.height
        events: list[dict] = []
        success_window: dict | None = None
        processed = 0

        def flush_success_window() -> None:
            nonlocal success_window
            if success_window and len(events) < 100:
                events.append(success_window)
            success_window = None

        for row in event_df.iter_rows(named=True):
            if len(events) >= 100:
                break
            processed += 1
            ts = _format_timestamp(float(row.get("call_start_time") or 0.0))
            if int(row.get("success_flag") or 0) == 1:
                if success_window is None:
                    success_window = {
                        "type": "SUCCESS_WINDOW",
                        "attempt_count": 0,
                        "success_count": 0,
                        "start_time": ts,
                        "end_time": ts,
                    }
                success_window["attempt_count"] += 1
                success_window["success_count"] += 1
                success_window["end_time"] = ts
                continue

            flush_success_window()
            if len(events) >= 100:
                break
            events.append(_build_failure_event(row))

        omitted_success_window = success_window is not None and len(events) >= 100
        flush_success_window()
        sequences.append({
            "imsi": str(imsi)[:8] + "...",
            "attempts": int(st.get("attempts") or 0),
            "success": int(st.get("success") or 0),
            "failures": int(st.get("failures") or 0),
            "failure_rate": fr,
            "anomaly_ratio": round(fr / global_failure_rate, 2) if global_failure_rate > 0 else 0.0,
            "truncated": processed < total_events or omitted_success_window,
            "total_events": total_events,
            "included_events": len(events),
            "events": events[:100],
        })
        del event_df

    return sequences


def analyze(records: pl.LazyFrame | pl.DataFrame | List[XdrRecord], parse_stats: dict) -> RcaAnalysis:
    """전체 레코드 분석."""
    materialized_df: pl.DataFrame | None = None
    if isinstance(records, pl.LazyFrame):
        lf = records
    elif isinstance(records, pl.DataFrame):
        materialized_df = records
        lf = materialized_df.lazy()
    else:
        materialized_df = pl.DataFrame([r.__dict__ for r in records])
        lf = materialized_df.lazy()

    total = int(parse_stats.get("parsed") or _collect_count(lf))
    attempt_lf = lf.filter(pl.col("attempt_flag") == 1)
    success_lf = attempt_lf.filter(pl.col("success_flag") == 1)
    failure_lf = attempt_lf.filter(pl.col("success_flag") != 1)
    attempt_count = _collect_count(attempt_lf)
    success_count = _collect_count(success_lf)
    failure_count = _collect_count(failure_lf)

    call_type_total_df = lf.group_by("call_type").len().collect()
    call_type_fail_df = failure_lf.group_by("call_type").len().collect()
    call_type_total = Counter(_counter_from_grouped(call_type_total_df, "call_type", name_mapper=get_call_type_name))
    call_type_fail = Counter(_counter_from_grouped(call_type_fail_df, "call_type", name_mapper=get_call_type_name))
    interface_dist: Counter[str] = Counter()

    failure_chains: List[FailureChain] = []
    imsi_fail_counts: Counter[str] = Counter()

    failure_df = failure_lf.collect()
    for row in failure_df.iter_rows(named=True):
        rec = _record_from_row(row)
        # NormalizedEvent 생성 후 FailureChain 빌드
        try:
            events: List[NormalizedEvent] = normalize_record(rec)
            chain = build_failure_chain(rec, events)
        except Exception:
            chain = None

        if chain:
            chain.imsi = rec.imsi
            if len(failure_chains) < 100:
                failure_chains.append(chain)
            if rec.imsi:
                imsi_fail_counts[rec.imsi] += 1
        del rec

    if failure_count:
        iface_df = failure_lf.filter(pl.col("first_error_interface") != 0).group_by("first_error_interface").len().collect()
        interface_dist = Counter(_counter_from_grouped(iface_df, "first_error_interface", name_mapper=get_interface_name))
        affected_counts_df = failure_lf.select(
            pl.col("imsi").filter(pl.col("imsi") != "").n_unique().alias("imsi"),
            pl.col("mme_id").filter(pl.col("mme_id") != 0).n_unique().alias("mme_id"),
            pl.col("first_enb_id").filter(pl.col("first_enb_id") != "").n_unique().alias("first_enb_id"),
            pl.col("apn").filter(pl.col("apn") != "").n_unique().alias("apn"),
        ).collect()
        affected_counts = affected_counts_df.row(0, named=True)
        affected_users_count = int(affected_counts["imsi"] or 0)
        affected_mme_count = int(affected_counts["mme_id"] or 0)
        affected_enb_count = int(affected_counts["first_enb_id"] or 0)
        affected_apn_count = int(affected_counts["apn"] or 0)
        affected_mme = _top_counted_dict_lf(failure_lf.filter(pl.col("mme_id") != 0), "mme_id", affected_mme_count)
        affected_enb = _top_counted_dict_lf(failure_lf.filter(pl.col("first_enb_id") != ""), "first_enb_id", affected_enb_count)
        affected_apn = _top_counted_dict_lf(failure_lf.filter(pl.col("apn") != ""), "apn", affected_apn_count)
    else:
        affected_users_count = affected_mme_count = affected_enb_count = affected_apn_count = 0
        affected_mme = CountedDict(total_count=0)
        affected_enb = CountedDict(total_count=0)
        affected_apn = CountedDict(total_count=0)

    time_dist = _time_distribution_lf(attempt_lf)
    time_fail_dist = _time_distribution_lf(failure_lf)

    # call_type 실패율
    call_type_failure_rate: Dict[str, float] = {}
    for ct, cnt in call_type_total.items():
        fail = call_type_fail.get(ct, 0)
        call_type_failure_rate[ct] = round(fail / cnt * 100, 2) if cnt else 0.0

    # 실패율
    failure_rate = round(failure_count / attempt_count * 100, 2) if attempt_count else 0.0

    # 반복 실패: 동일 IMSI에서 2회 이상 실패
    repeated_count = sum(1 for cnt in imsi_fail_counts.values() if cnt >= 2)
    repeated_failures = CountedDict(total_count=repeated_count)
    top_failed_imsi_sequences = (
        _top_failed_imsi_sequences(attempt_lf, failure_lf, failure_rate)
        if failure_count else []
    )

    # ── Equipment baseline + shared failure signatures ────────────────────────
    mme_baseline: list = []
    enb_baseline: list = []
    shared_failure_signatures: list = []

    if failure_count:
        # MME baseline: per-MME attempt/success/failures/failure_rate/anomaly_ratio
        mme_bl_df = (
            attempt_lf
            .filter(pl.col("mme_id") != 0)
            .group_by("mme_id")
            .agg([
                pl.len().alias("attempts"),
                pl.col("success_flag").sum().cast(pl.Int64).alias("success"),
            ])
            .with_columns([
                (pl.col("attempts") - pl.col("success")).alias("failures"),
                (
                    (pl.col("attempts") - pl.col("success")).cast(pl.Float64)
                    / pl.col("attempts") * 100
                ).round(2).alias("failure_rate"),
            ])
            .filter(pl.col("failures") > 0)
            .sort("failures", descending=True)
            .head(20)
            .collect()
        )
        for row in mme_bl_df.iter_rows(named=True):
            fr = float(row["failure_rate"] or 0)
            mme_baseline.append({
                "mme_id": str(row["mme_id"]),
                "attempts": row["attempts"],
                "success": int(row["success"]),
                "failures": int(row["failures"]),
                "failure_rate": fr,
                "anomaly_ratio": round(fr / failure_rate, 2) if failure_rate > 0 else 0.0,
            })
        del mme_bl_df

        # eNB baseline
        enb_bl_df = (
            attempt_lf
            .filter(pl.col("first_enb_id") != "")
            .group_by("first_enb_id")
            .agg([
                pl.len().alias("attempts"),
                pl.col("success_flag").sum().cast(pl.Int64).alias("success"),
            ])
            .with_columns([
                (pl.col("attempts") - pl.col("success")).alias("failures"),
                (
                    (pl.col("attempts") - pl.col("success")).cast(pl.Float64)
                    / pl.col("attempts") * 100
                ).round(2).alias("failure_rate"),
            ])
            .filter(pl.col("failures") > 0)
            .sort("failures", descending=True)
            .head(20)
            .collect()
        )
        for row in enb_bl_df.iter_rows(named=True):
            fr = float(row["failure_rate"] or 0)
            enb_baseline.append({
                "enb_id": str(row["first_enb_id"]),
                "attempts": row["attempts"],
                "success": int(row["success"]),
                "failures": int(row["failures"]),
                "failure_rate": fr,
                "anomaly_ratio": round(fr / failure_rate, 2) if failure_rate > 0 else 0.0,
            })
        del enb_bl_df

        # Shared failure signatures: group by (interface, message, cause), count distinct devices
        sig_df = (
            failure_lf
            .filter(pl.col("first_error_interface") != 0)
            .group_by(["first_error_interface", "first_error_message", "first_error_cause"])
            .agg([
                pl.len().alias("count"),
                pl.col("imsi").n_unique().alias("affected_imsi_count"),
                pl.col("mme_id").n_unique().alias("affected_mme_count"),
                pl.col("first_enb_id").n_unique().alias("affected_enb_count"),
            ])
            .filter(pl.col("count") > 1)
            .sort(["first_error_interface", "first_error_message", "first_error_cause"], descending=False)
            .head(10)
            .collect()
        )
        for row in sig_df.iter_rows(named=True):
            fi = int(row["first_error_interface"])
            fm = int(row["first_error_message"])
            fc = int(row["first_error_cause"])
            shared_failure_signatures.append({
                "interface": get_interface_name(fi),
                "stage": _interface_msg_to_stage(fi, fm),
                "cause": get_cause_name(fi, fc),
                "count": row["count"],
                "affected_imsi_count": row["affected_imsi_count"],
                "affected_mme_count": row["affected_mme_count"],
                "affected_enb_count": row["affected_enb_count"],
            })
        del sig_df

    # 버스트 감지: 10분 단위 구간에서 평균 대비 3배 이상 실패
    burst_detected = False
    burst_window: Optional[str] = None
    if time_fail_dist:
        values = list(time_fail_dist.values())
        mean_fail = sum(values) / len(values)
        threshold = mean_fail * 3
        bursts = [(bucket, cnt) for bucket, cnt in time_fail_dist.items() if cnt >= threshold and cnt > 1]
        if bursts:
            burst_detected = True
            bursts.sort(key=lambda x: x[1], reverse=True)
            worst = bursts[0][0]
            burst_window = f"{worst} - (10분 구간)"

    result = RcaAnalysis(
        total_records=total,
        attempt_count=attempt_count,
        success_count=success_count,
        failure_count=failure_count,
        failure_rate=failure_rate,
        call_type_distribution=dict(call_type_total),
        call_type_failure_rate=call_type_failure_rate,
        interface_distribution=dict(interface_dist),
        affected_imsi_set=CountOnlySet(affected_users_count),
        affected_mme_ids=affected_mme,
        affected_enb_ids=affected_enb,
        affected_apns=affected_apn,
        failure_chains=failure_chains,
        top_failed_imsi_sequences=top_failed_imsi_sequences,
        repeated_failures=repeated_failures,
        time_distribution=dict(time_dist),
        burst_detected=burst_detected,
        burst_window=burst_window,
        parse_stats=parse_stats,
        mme_baseline=mme_baseline,
        enb_baseline=enb_baseline,
        shared_failure_signatures=shared_failure_signatures,
    )
    del lf, attempt_lf, success_lf, failure_lf, failure_df, call_type_total_df, call_type_fail_df
    try:
        del iface_df, affected_counts_df, affected_counts
    except UnboundLocalError:
        pass
    if materialized_df is not None:
        del materialized_df
    gc.collect()
    return result
