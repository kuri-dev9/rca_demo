"""
parser.py
xDR .dat 파일을 Polars LazyFrame으로 projection-first 파싱한다.
필드 구분자: 0x1E, 레코드 구분자: \n
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import gc
import logging

import polars as pl

from app.rca.spec_loader import CALL_TYPE_MAP, FIELD_INDEX

logger = logging.getLogger(__name__)

# RCA는 장비/네트워크 RCA가 목적이므로 Paging 계열 call_type은 분석 대상에서 제외한다.
# 원본 파일은 변경하지 않고, 분석용 LazyFrame 구성 단계에서만 필터링한다.
_PAGING_CALL_TYPE_CODES: set[int] = {
    code for code, name in CALL_TYPE_MAP.items() if "paging" in name.lower()
}

# 파싱에 필요한 필드 목록 (이름 → FIELD_INDEX 기반 index)
_NEEDED: dict[str, int] = {
    "imsi":                    FIELD_INDEX["imsi"],
    "imsi_mcc_mnc_info":       FIELD_INDEX["imsi_mcc_mnc_info"],
    "mme_id":                  FIELD_INDEX["mme_id"],
    "first_enb_id":            FIELD_INDEX["first_enb_id"],
    "call_type":               FIELD_INDEX["call_type"],
    "call_start_time":         FIELD_INDEX["call_start_time"],
    "apn":                     FIELD_INDEX["apn"],
    "auth_info_cause":         FIELD_INDEX["auth_info_cause"],
    "update_location_cause":   FIELD_INDEX["update_location_cause"],
    "s1ap_error_message":      FIELD_INDEX["s1ap_error_message"],
    "s1ap_error_cause":        FIELD_INDEX["s1ap_error_cause"],
    "emm_error_message":       FIELD_INDEX["emm_error_message"],
    "emm_error_cause":         FIELD_INDEX["emm_error_cause"],
    "esm_error_message":       FIELD_INDEX["esm_error_message"],
    "esm_error_cause":         FIELD_INDEX["esm_error_cause"],
    "s11_error_message":       FIELD_INDEX["s11_error_message"],
    "s11_error_cause":         FIELD_INDEX["s11_error_cause"],
    "attempt_flag":            FIELD_INDEX["attempt_flag"],
    "success_flag":            FIELD_INDEX["success_flag"],
    "drop_flag":               FIELD_INDEX["drop_flag"],
    "auth_attempt_flag":       FIELD_INDEX["auth_attempt_flag"],
    "auth_success_flag":       FIELD_INDEX["auth_success_flag"],
    "location_attempt_flag":   FIELD_INDEX["location_attempt_flag"],
    "location_success_flag":   FIELD_INDEX["location_success_flag"],
    "first_error_interface":   FIELD_INDEX["first_error_interface"],
    "first_error_message":     FIELD_INDEX["first_error_message"],
    "first_error_cause":       FIELD_INDEX["first_error_cause"],
    "last_error_interface":    FIELD_INDEX["last_error_interface"],
    "last_error_message":      FIELD_INDEX["last_error_message"],
    "last_error_cause":        FIELD_INDEX["last_error_cause"],
}

_STRING_FIELDS = {"imsi", "imsi_mcc_mnc_info", "first_enb_id", "apn"}
_FLOAT_FIELDS = {"call_start_time"}
_TOTAL_COLUMNS = max(154, max(FIELD_INDEX.values()) + 1)
_INVALID_ENB_IDS: set[str] = {
    "bo3reaGROYftluYm2HmjZQ==",  # 복호화 값 = 0, 유효하지 않은 eNB ID
}

@dataclass
class XdrRecord:
    imsi: str
    imsi_mcc_mnc_info: str
    mme_id: int
    first_enb_id: str
    call_type: int
    call_start_time: float
    apn: str
    auth_info_cause: int
    update_location_cause: int
    s1ap_error_message: int
    s1ap_error_cause: int
    emm_error_message: int
    emm_error_cause: int
    esm_error_message: int
    esm_error_cause: int
    s11_error_message: int
    s11_error_cause: int
    attempt_flag: int
    success_flag: int
    drop_flag: int
    auth_attempt_flag: int
    auth_success_flag: int
    location_attempt_flag: int
    location_success_flag: int
    first_error_interface: int
    first_error_message: int
    first_error_cause: int
    last_error_interface: int
    last_error_message: int
    last_error_cause: int


def parse_file(
    filepath: str,
    max_records: Optional[int] = None,
    call_type_filter: Optional[list[int]] = None,
) -> tuple[pl.LazyFrame, dict]:
    """
    xDR .dat 파일을 Polars lazy 방식으로 필요한 컬럼만 projection한다.

    1. scan_csv로 LazyFrame 생성
    2. 필요한 컬럼만 projection/cast
    3. call_type_filter / max_records 적용
    4. 필요한 컬럼만 가진 LazyFrame 반환
    """
    lazy_df = pl.scan_csv(
        filepath,
        separator="\x1e",
        has_header=False,
        infer_schema=False,
        quote_char=None,
        truncate_ragged_lines=True,
        ignore_errors=True,
        low_memory=True,
        rechunk=False,
        new_columns=[f"column_{i}" for i in range(_TOTAL_COLUMNS)],
    )

    call_type_col = pl.col(f"column_{FIELD_INDEX['call_type']}").str.strip_chars()
    total_lines = lazy_df.select(pl.len()).collect().item()

    filtered_lf = lazy_df.filter(call_type_col.is_not_null() & (call_type_col != ""))

    select_exprs = []
    for name, idx in _NEEDED.items():
        expr = pl.col(f"column_{idx}").str.strip_chars()
        if name in _STRING_FIELDS:
            select_exprs.append(expr.fill_null("").alias(name))
        elif name in _FLOAT_FIELDS:
            select_exprs.append(expr.cast(pl.Float64, strict=False).fill_null(0.0).alias(name))
        else:
            select_exprs.append(expr.cast(pl.Int64, strict=False).fill_null(0).alias(name))

    projected_lf = filtered_lf.select(select_exprs)
    projected_lf = projected_lf.filter(
        ~pl.col("first_enb_id").is_in(list(_INVALID_ENB_IDS))
    )

    excluded_paging = 0
    if _PAGING_CALL_TYPE_CODES:
        pre_paging_count = projected_lf.select(pl.len()).collect().item()
        projected_lf = projected_lf.filter(
            ~pl.col("call_type").is_in(list(_PAGING_CALL_TYPE_CODES))
        )
        post_paging_count = projected_lf.select(pl.len()).collect().item()
        excluded_paging = pre_paging_count - post_paging_count
        if excluded_paging:
            logger.info("[RCA][FILTER] excluded_paging_records=%d", excluded_paging)

    if call_type_filter:
        projected_lf = projected_lf.filter(pl.col("call_type").is_in(call_type_filter))
    if max_records:
        projected_lf = projected_lf.limit(max_records)

    parsed = projected_lf.select(pl.len()).collect().item()
    parse_stats = {
        "total_lines": total_lines,
        "raw_rows": parsed,
        "parsed": parsed,
        "skipped": max(total_lines - parsed, 0),
        "excluded_paging": excluded_paging,
    }

    del filtered_lf, lazy_df
    gc.collect()
    return projected_lf, parse_stats
