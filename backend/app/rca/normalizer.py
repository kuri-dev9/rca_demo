"""
normalizer.py
raw XdrRecord → NormalizedEvent 리스트 변환.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.rca.code_mapper import _build_semantic, map_interface_error
from app.rca.parser import XdrRecord
from app.rca.spec_loader import (
    FIELD_INDEX,
    get_cause_name,
    get_interface_name,
    get_message_name,
    is_error_cause,
)


@dataclass
class NormalizedEvent:
    procedure_step: str    # "AUTH_REQUEST", "UPDATE_LOCATION", "CREATE_SESSION" 등
    interface: str         # "S6a_Diameter"
    message: str           # "AIR_AIA"
    cause_code: int
    cause_name: str        # "DIAMETER_ERROR_USER_UNKNOWN"
    is_failure: bool
    semantic: str          # rules.py 키 (예: "S6A_USER_UNKNOWN")
    timestamp: float


def build_semantic_key(interface_code: int, cause_code: int) -> str:
    """interface + cause → semantic key. NAS ESM은 cause 기반으로 세분화."""
    if interface_code == 6:
        if cause_code == 8:
            return "NAS_ESM_OPERATOR_BARRING"
        if cause_code == 27:
            return "NAS_ESM_APN_UNKNOWN"
        if cause_code == 29:
            return "NAS_ESM_AUTH_FAILED"
        if cause_code == 33:
            return "NAS_ESM_SERVICE_NOT_SUBSCRIBED"
        if cause_code in (26, 30):
            return "NAS_ESM_CORE_RESOURCE_REJECT"
        if cause_code != 0:
            return "NAS_ESM_PDN_REJECT"
    return _build_semantic(interface_code, 0, cause_code)


def _make_event(
    step: str,
    interface_code: int,
    msg_code: int,
    cause_code: int,
    timestamp: float,
) -> NormalizedEvent:
    iface_name = get_interface_name(interface_code)
    msg_name = get_message_name(interface_code, msg_code)
    cause_name = get_cause_name(interface_code, cause_code)
    failure = is_error_cause(interface_code, cause_code)
    semantic = _build_semantic(interface_code, msg_code, cause_code)
    return NormalizedEvent(
        procedure_step=step,
        interface=iface_name,
        message=msg_name,
        cause_code=cause_code,
        cause_name=cause_name,
        is_failure=failure,
        semantic=semantic,
        timestamp=timestamp,
    )


# Interface protocol codes (from spec_loader)
_IFACE_S6A  = 1
_IFACE_S1AP = 2
_IFACE_S11  = 3
_IFACE_S10  = 4
_IFACE_EMM  = 5
_IFACE_ESM  = 6
_IFACE_S3   = 7
_IFACE_S13  = 8

# Message codes
_MSG_AIR_AIA = 318   # S6a Authentication Information
_MSG_ULR_ULA = 316   # S6a Update Location
_MSG_CREATE_SESSION_RESP = 33


def normalize_record(record: XdrRecord) -> list[NormalizedEvent]:
    """
    XdrRecord에서 NormalizedEvent 리스트를 생성한다.

    first_error를 우선 처리하여 최초 실패 이벤트를 앞에 배치.
    이후 개별 interface 오류 필드를 순서대로 추가한다.
    """
    events: list[NormalizedEvent] = []
    seen_steps: set[str] = set()
    ts = record.call_start_time

    def add(step: str, iface: int, msg: int, cause: int, t: float = 0.0) -> None:
        key = (step, iface, cause)
        if key in seen_steps:
            return
        seen_steps.add(key)
        events.append(_make_event(step, iface, msg, cause, t or ts))

    # ── 1. first_error 우선 배치 ────────────────────────────────────────────
    fe_iface = record.first_error_interface
    fe_msg   = record.first_error_message
    fe_cause = record.first_error_cause
    if fe_iface != 0 and is_error_cause(fe_iface, fe_cause):
        if fe_iface == _IFACE_S6A:
            step = "AUTH_REQUEST" if fe_msg == _MSG_AIR_AIA else "UPDATE_LOCATION"
        elif fe_iface == _IFACE_S1AP:
            step = "INITIAL_CONTEXT_SETUP"
        elif fe_iface == _IFACE_S11 or fe_iface == _IFACE_S10:
            step = "CREATE_SESSION"
        elif fe_iface == _IFACE_EMM:
            step = "NAS_EMM"
        elif fe_iface == _IFACE_ESM:
            step = "NAS_ESM"
        else:
            step = "UNKNOWN_STEP"
        add(step, fe_iface, fe_msg, fe_cause)

    # ── 2. S6a AIR/AIA → AUTH_REQUEST ───────────────────────────────────────
    if record.auth_info_cause != 0:
        add("AUTH_REQUEST", _IFACE_S6A, _MSG_AIR_AIA, record.auth_info_cause)

    # ── 3. S6a ULR/ULA → UPDATE_LOCATION ────────────────────────────────────
    if record.update_location_cause != 0:
        add("UPDATE_LOCATION", _IFACE_S6A, _MSG_ULR_ULA, record.update_location_cause)

    # ── 4. S11 → CREATE_SESSION ──────────────────────────────────────────────
    if record.s11_error_cause != 0:
        add("CREATE_SESSION", _IFACE_S11, record.s11_error_message, record.s11_error_cause)

    # ── 5. S1AP → INITIAL_CONTEXT_SETUP ─────────────────────────────────────
    if record.s1ap_error_cause != 0:
        add("INITIAL_CONTEXT_SETUP", _IFACE_S1AP, record.s1ap_error_message, record.s1ap_error_cause)

    # ── 6. NAS-EMM ───────────────────────────────────────────────────────────
    if record.emm_error_cause != 0:
        add("NAS_EMM", _IFACE_EMM, record.emm_error_message, record.emm_error_cause)

    # ── 7. NAS-ESM ───────────────────────────────────────────────────────────
    if record.esm_error_cause != 0:
        add("NAS_ESM", _IFACE_ESM, record.esm_error_message, record.esm_error_cause)

    return events
