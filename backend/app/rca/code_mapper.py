"""
code_mapper.py
raw 인터페이스/메시지/원인 코드 → 의미 변환.
spec_loader의 함수를 조합하여 구조화된 dict를 반환한다.
"""
from __future__ import annotations

from app.rca.parser import XdrRecord
from app.rca.spec_loader import (
    get_cause_name,
    get_interface_name,
    get_message_name,
    is_error_cause,
)

# S6a 메시지 코드 → 절차 스텝 이름
_S6A_MSG_TO_STEP = {
    318: "AUTH_REQUEST",     # AIR/AIA
    316: "UPDATE_LOCATION",  # ULR/ULA
    319: "INSERT_SUBSCRIBER_DATA",
    317: "CANCEL_LOCATION",
}

# S1AP 메시지 코드 → 절차 스텝 이름
_S1AP_MSG_TO_STEP = {
    9:  "INITIAL_CONTEXT_SETUP",
    12: "INITIAL_UE_MESSAGE",
    18: "UE_CONTEXT_RELEASE",
    23: "UE_CONTEXT_RELEASE",
}

# S11 메시지 코드 → 절차 스텝 이름
_S11_MSG_TO_STEP = {
    32: "CREATE_SESSION",
    33: "CREATE_SESSION",
    34: "MODIFY_BEARER",
    35: "MODIFY_BEARER",
    36: "DELETE_SESSION",
    37: "DELETE_SESSION",
}


def _step_from_interface_msg(interface_code: int, msg_code: int) -> str:
    iface = get_interface_name(interface_code)
    if "S6a" in iface or "S13" in iface:
        return _S6A_MSG_TO_STEP.get(msg_code, "S6A_OPERATION")
    if "S1AP" in iface:
        return _S1AP_MSG_TO_STEP.get(msg_code, "S1AP_OPERATION")
    if "S11" in iface or "S10" in iface:
        return _S11_MSG_TO_STEP.get(msg_code, "GTP_OPERATION")
    if "NAS_EMM" in iface:
        return "NAS_EMM"
    if "NAS_ESM" in iface:
        return "NAS_ESM"
    return "UNKNOWN_STEP"


def _build_semantic(interface_code: int, msg_code: int, cause_code: int) -> str:
    """interface + message + cause → semantic key (rules.py 키 형식)"""
    iface = get_interface_name(interface_code)
    cause_name = get_cause_name(interface_code, cause_code)

    # TIMEOUT은 인터페이스별 처리
    if cause_code == 900:
        if "S6a" in iface:
            step = _step_from_interface_msg(interface_code, msg_code)
            if step == "AUTH_REQUEST":
                return "S6A_AUTH_TIMEOUT"
            return "S6A_UPDATE_LOCATION_TIMEOUT"
        if "S11" in iface or "S10" in iface:
            return "GTP_TIMEOUT"
        if "S1AP" in iface:
            return "S1AP_TIMEOUT"
        return "UNKNOWN"

    if "S6a" in iface or "S13" in iface:
        step = _step_from_interface_msg(interface_code, msg_code)
        if cause_code == 5001:
            return "S6A_USER_UNKNOWN"
        if msg_code == 318 and cause_code == 4181:
            return "S6A_AUTH_DATA_UNAVAILABLE"
        if msg_code == 318 and cause_code != 0:
            if cause_code >= 10000:
                return "S6A_VENDOR_SPECIFIC"
            return "S6A_AUTH_DATA_UNAVAILABLE"
        if msg_code == 316 and cause_code == 5004:
            return "S6A_ROAMING_NOT_ALLOWED"
        if msg_code == 316 and cause_code != 0:
            if cause_code >= 10000:
                return "S6A_VENDOR_SPECIFIC"
            return "S6A_UPDATE_LOCATION_FAIL"
        if cause_code == 5004:
            return "S6A_ROAMING_NOT_ALLOWED"
        if cause_code == 4181:
            return "S6A_AUTH_DATA_UNAVAILABLE"
        if cause_code >= 10000:
            return "S6A_VENDOR_SPECIFIC"
        if step == "AUTH_REQUEST":
            return "S6A_AUTH_DATA_UNAVAILABLE"
        return "S6A_UPDATE_LOCATION_FAIL"

    if "S1AP" in iface:
        if cause_code == 301:
            return "S1AP_AUTH_FAILURE"
        if cause_code == 121:
            return "S1AP_RADIO_LOST"
        if cause_code == 126 or cause_code == 110:
            return "S1AP_INITIAL_CONTEXT_FAIL"
        return "S1AP_INITIAL_CONTEXT_FAIL"

    if "NAS_EMM" in iface:
        if cause_code == 17:
            return "NAS_EMM_NETWORK_FAILURE"
        return "NAS_EMM_NETWORK_FAILURE"

    if "NAS_ESM" in iface:
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
        return "NAS_ESM_PDN_REJECT"

    if "S11" in iface or "S10" in iface:
        if cause_code == 64:
            return "GTP_CONTEXT_NOT_FOUND"
        if cause_code >= 64:
            return "GTP_CREATE_SESSION_FAIL"

    return "UNKNOWN"


def map_interface_error(
    interface_code: int,
    message_code: int,
    cause_code: int,
) -> dict:
    """
    반환:
    {
      "interface": "S6a_Diameter",
      "message": "AIR_AIA",
      "cause": "DIAMETER_ERROR_USER_UNKNOWN",
      "is_error": True,
      "semantic": "S6A_USER_UNKNOWN"
    }
    """
    return {
        "interface": get_interface_name(interface_code),
        "message": get_message_name(interface_code, message_code),
        "cause": get_cause_name(interface_code, cause_code),
        "is_error": is_error_cause(interface_code, cause_code),
        "semantic": _build_semantic(interface_code, message_code, cause_code),
    }


def map_first_error(record: XdrRecord) -> dict:
    """first_error_interface / first_error_message / first_error_cause 기반 매핑"""
    return map_interface_error(
        record.first_error_interface,
        record.first_error_message,
        record.first_error_cause,
    )


def map_last_error(record: XdrRecord) -> dict:
    """last_error_interface / last_error_message / last_error_cause 기반 매핑"""
    return map_interface_error(
        record.last_error_interface,
        record.last_error_message,
        record.last_error_cause,
    )
