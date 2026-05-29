"""
chain_builder.py
Expected vs Observed 비교 → FailureChain 생성.
핵심 원칙: first_failure 기준. last_error 직접 사용 금지.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.rca.normalizer import NormalizedEvent
from app.rca.parser import XdrRecord
from app.rca.procedures import (
    ATTACH_FLOW,
    get_procedure_flow,
    get_procedure_name,
    get_step_index,
)
from app.rca.spec_loader import get_cause_name, get_interface_name, get_message_name, is_error_cause

# Interface codes
_IFACE_S6A  = 1
_IFACE_S1AP = 2
_IFACE_S11  = 3
_IFACE_S10  = 4
_IFACE_EMM  = 5
_IFACE_ESM  = 6

# S6a message codes
_MSG_AIR_AIA = 318
_MSG_ULR_ULA = 316


@dataclass
class FailureChain:
    procedure: str
    call_type: int
    expected_flow: list[str]
    observed_steps: list[str]
    failure_point: str
    failure_interface: str
    failure_message: str
    failure_cause: int
    failure_cause_name: str
    failure_semantic: str
    chain: list[str]
    imsi: str = ""


def _determine_failure_point(record: XdrRecord) -> tuple[str, str]:
    """
    first_error_interface + first_error_message 기반으로
    (failure_step, failure_semantic) 결정.
    """
    fi = record.first_error_interface
    fm = record.first_error_message
    fc = record.first_error_cause

    from app.rca.code_mapper import _build_semantic

    if record.auth_attempt_flag == 1 and record.auth_success_flag == 0:
        msg = fm if fi == _IFACE_S6A else _MSG_AIR_AIA
        cause = record.auth_info_cause or fc
        return "AUTH_REQUEST", _build_semantic(_IFACE_S6A, msg, cause)

    if record.location_attempt_flag == 1 and record.location_success_flag == 0:
        msg = fm if fi == _IFACE_S6A else _MSG_ULR_ULA
        cause = record.update_location_cause or fc
        return "UPDATE_LOCATION", _build_semantic(_IFACE_S6A, msg, cause)

    if fi == 0 or not is_error_cause(fi, fc):
        # first_error 없음 → 개별 필드에서 찾기
        if record.auth_info_cause != 0 and is_error_cause(_IFACE_S6A, record.auth_info_cause):
            fi, fm, fc = _IFACE_S6A, _MSG_AIR_AIA, record.auth_info_cause
        elif record.update_location_cause != 0 and is_error_cause(_IFACE_S6A, record.update_location_cause):
            fi, fm, fc = _IFACE_S6A, _MSG_ULR_ULA, record.update_location_cause
        elif record.s11_error_cause != 0 and is_error_cause(_IFACE_S11, record.s11_error_cause):
            fi, fm, fc = _IFACE_S11, record.s11_error_message, record.s11_error_cause
        elif record.s1ap_error_cause != 0:
            fi, fm, fc = _IFACE_S1AP, record.s1ap_error_message, record.s1ap_error_cause
        elif record.emm_error_cause != 0:
            fi, fm, fc = _IFACE_EMM, record.emm_error_message, record.emm_error_cause
        elif record.esm_error_cause != 0:
            fi, fm, fc = _IFACE_ESM, record.esm_error_message, record.esm_error_cause
        else:
            return "UNKNOWN_STEP", "UNKNOWN"

    # interface + message → step 이름
    if fi == _IFACE_S6A:
        step = "AUTH_REQUEST" if fm == _MSG_AIR_AIA else "UPDATE_LOCATION"
    elif fi == _IFACE_S1AP:
        step = "INITIAL_CONTEXT_SETUP"
    elif fi in (_IFACE_S11, _IFACE_S10):
        step = "CREATE_SESSION"
    elif fi == _IFACE_EMM:
        step = "NAS_EMM"
    elif fi == _IFACE_ESM:
        step = "NAS_ESM"
    else:
        step = "UNKNOWN_STEP"

    semantic = _build_semantic(fi, fm, fc)
    return step, semantic


def _observed_steps_before(flow: list[str], failure_step: str, record: XdrRecord) -> list[str]:
    """
    failure_step 이전 완료된 스텝 목록.
    auth_success_flag / location_success_flag 등 flag로 보완.
    """
    idx = get_step_index(flow, failure_step)
    if idx <= 0:
        return []

    # 기본: failure_step 이전 스텝 모두 완료로 간주
    observed = list(flow[:idx])

    # flag 기반 보완: 완료 확인된 스텝 추가
    if record.auth_success_flag == 1 and "AUTH_REQUEST" not in observed:
        if "AUTH_REQUEST" in flow:
            observed.append("AUTH_REQUEST")
    if record.location_success_flag == 1 and "UPDATE_LOCATION" not in observed:
        if "UPDATE_LOCATION" in flow:
            observed.append("UPDATE_LOCATION")

    return observed


def _semantic_chain_label(semantic: str, fallback_step: str) -> str:
    mapping = {
        "NAS_ESM_OPERATOR_BARRING": "NAS_ESM_OPERATOR_BARRING",
        "NAS_ESM_APN_UNKNOWN": "NAS_ESM_APN_UNKNOWN",
        "NAS_ESM_AUTH_FAILED": "NAS_ESM_AUTH_FAILED",
        "NAS_ESM_SERVICE_NOT_SUBSCRIBED": "NAS_ESM_SERVICE_NOT_SUBSCRIBED",
        "NAS_ESM_CORE_RESOURCE_REJECT": "NAS_ESM_CORE_RESOURCE_REJECT",
        "NAS_ESM_PDN_REJECT": "NAS_ESM_PDN_REJECT",
        "S6A_AUTH_TIMEOUT": "AUTH_TIMEOUT",
        "S6A_AUTH_DATA_UNAVAILABLE": "AUTH_DATA_UNAVAILABLE",
        "S6A_USER_UNKNOWN": "S6A_USER_UNKNOWN",
        "S6A_ROAMING_NOT_ALLOWED": "S6A_ROAMING_NOT_ALLOWED",
        "S6A_UPDATE_LOCATION_TIMEOUT": "UPDATE_LOCATION_TIMEOUT",
        "S6A_UPDATE_LOCATION_FAIL": "UPDATE_LOCATION_FAIL",
        "S6A_VENDOR_SPECIFIC": "S6A_VENDOR_SPECIFIC_REJECT",
        "GTP_CONTEXT_NOT_FOUND": "CREATE_SESSION_CONTEXT_NOT_FOUND",
        "GTP_CREATE_SESSION_FAIL": "CREATE_SESSION_FAIL",
        "GTP_TIMEOUT": "CREATE_SESSION_TIMEOUT",
        "S1AP_INITIAL_CONTEXT_FAIL": "INITIAL_CONTEXT_SETUP_FAIL",
        "S1AP_RADIO_LOST": "RADIO_LINK_LOST",
    }
    return mapping.get(semantic, f"{fallback_step}_FAIL")


def _build_attach_chain_steps(record: XdrRecord, failure_step: str, failure_semantic: str) -> list[str]:
    """Attach 절차의 주요 EPC 단계 성공/실패 evidence를 명시한다."""
    chain: list[str] = []

    auth_failed = (
        (record.auth_attempt_flag == 1 and record.auth_success_flag == 0)
        or (record.first_error_interface == _IFACE_S6A and record.first_error_message == _MSG_AIR_AIA)
        or failure_step == "AUTH_REQUEST"
    )
    if record.auth_success_flag == 1 and not auth_failed:
        chain.append("AUTH_SUCCESS")
    elif auth_failed:
        return [_semantic_chain_label(failure_semantic, "AUTH"), "ATTACH_REJECT"]

    location_failed = (
        (record.location_attempt_flag == 1 and record.location_success_flag == 0)
        or (record.first_error_interface == _IFACE_S6A and record.first_error_message == _MSG_ULR_ULA)
        or failure_step == "UPDATE_LOCATION"
    )
    if record.location_success_flag == 1 and not location_failed:
        chain.append("UPDATE_LOCATION_SUCCESS")
    elif location_failed:
        chain.extend([_semantic_chain_label(failure_semantic, "UPDATE_LOCATION"), "ATTACH_REJECT"])
        return chain

    create_session_failed = (
        record.s11_error_cause >= 64
        or record.first_error_interface in (_IFACE_S11, _IFACE_S10)
        or failure_step == "CREATE_SESSION"
    )
    if create_session_failed:
        chain.extend([_semantic_chain_label(failure_semantic, "CREATE_SESSION"), "ATTACH_REJECT"])
        return chain

    context_setup_failed = (
        record.s1ap_error_cause != 0 and record.first_error_interface == _IFACE_S1AP
    ) or failure_step == "INITIAL_CONTEXT_SETUP"
    if context_setup_failed:
        chain.append("CREATE_SESSION_SUCCESS")
        chain.extend([_semantic_chain_label(failure_semantic, "INITIAL_CONTEXT_SETUP"), "ATTACH_REJECT"])
        return chain

    nas_esm_failed = (
        record.esm_error_cause != 0 and record.first_error_interface == _IFACE_ESM
    ) or failure_step == "NAS_ESM"
    if nas_esm_failed:
        chain.append("CREATE_SESSION_SUCCESS")
        chain.extend([_semantic_chain_label(failure_semantic, "NAS_ESM"), "ATTACH_REJECT"])
        return chain

    chain.extend([_semantic_chain_label(failure_semantic, failure_step), "ATTACH_REJECT"])
    return chain


def _build_chain_steps(flow: list[str], failure_step: str, failure_semantic: str, record: XdrRecord) -> list[str]:
    """failure_step부터 절차 종료까지 chain 구성."""
    if record.call_type in (1, 2):
        return _build_attach_chain_steps(record, failure_step, failure_semantic)

    idx = get_step_index(flow, failure_step)
    if idx < 0:
        return [_semantic_chain_label(failure_semantic, failure_step)]

    chain = []
    for i, step in enumerate(flow[idx:]):
        if i == 0:
            chain.append(_semantic_chain_label(failure_semantic, step))
        elif step in ("ATTACH_ACCEPT", "ATTACH_COMPLETE", "TAU_ACCEPT", "TAU_COMPLETE", "SERVICE_ACCEPT"):
            chain.append(f"{step}_REJECTED")
            break
    return chain


def build_failure_chain(
    record: XdrRecord,
    events: list[NormalizedEvent],
) -> Optional[FailureChain]:
    """
    성공 레코드(success_flag=1)는 None 반환.
    attempt_flag=0이면 None 반환.
    """
    if record.attempt_flag != 1:
        return None
    if record.success_flag == 1:
        return None

    call_type = record.call_type
    procedure = get_procedure_name(call_type)
    flow = get_procedure_flow(call_type)

    # MVP: Attach 이외는 UNSUPPORTED_PROCEDURE 반환
    if not flow:
        fi = record.first_error_interface
        fm = record.first_error_message
        fc = record.first_error_cause
        from app.rca.code_mapper import _build_semantic
        semantic = _build_semantic(fi, fm, fc) if fi != 0 else "UNKNOWN"
        return FailureChain(
            procedure=procedure,
            call_type=call_type,
            expected_flow=[],
            observed_steps=[],
            failure_point="UNSUPPORTED_PROCEDURE",
            failure_interface=get_interface_name(fi),
            failure_message=get_message_name(fi, fm),
            failure_cause=fc,
            failure_cause_name=get_cause_name(fi, fc),
            failure_semantic=semantic,
            chain=["UNSUPPORTED_PROCEDURE"],
        )

    failure_step, failure_semantic = _determine_failure_point(record)

    # failure_step이 flow에 없으면 첫 이벤트에서 가져오기
    if failure_step not in flow and events:
        first_fail = next((e for e in events if e.is_failure), None)
        if first_fail:
            failure_step = first_fail.procedure_step
            failure_semantic = first_fail.semantic

    # first_error 필드
    fi = record.first_error_interface
    fm = record.first_error_message
    fc = record.first_error_cause
    if fi == 0 and events:
        first_fail = next((e for e in events if e.is_failure), events[0])
        fi_name = first_fail.interface
        fm_name = first_fail.message
        fc = first_fail.cause_code
        fi = next(
            (
                code for code in (_IFACE_S6A, _IFACE_S1AP, _IFACE_S11, _IFACE_S10, _IFACE_EMM, _IFACE_ESM)
                if get_interface_name(code) == fi_name
            ),
            0,
        )
    else:
        fi_name = get_interface_name(fi)
        fm_name = get_message_name(fi, fm)

    cause_name = get_cause_name(fi, fc)
    observed = _observed_steps_before(flow, failure_step, record)
    chain = _build_chain_steps(flow, failure_step, failure_semantic, record)

    return FailureChain(
        procedure=procedure,
        call_type=call_type,
        expected_flow=flow,
        observed_steps=observed,
        failure_point=failure_step,
        failure_interface=fi_name,
        failure_message=fm_name,
        failure_cause=fc,
        failure_cause_name=cause_name,
        failure_semantic=failure_semantic,
        chain=chain,
    )
