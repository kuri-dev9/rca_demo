"""
procedures.py
LTE 절차 템플릿 정의.
MVP: Attach(call_type 1,2)만 완전 구현. 나머지는 기본 반환.
"""
from __future__ import annotations

from typing import Dict, List

ATTACH_FLOW: List[str] = [
    "RRC_CONNECTION",
    "INITIAL_UE_MESSAGE",
    "IDENTITY_REQUEST",
    "AUTH_REQUEST",
    "AUTH_RESPONSE",
    "SECURITY_MODE_COMMAND",
    "SECURITY_MODE_COMPLETE",
    "UPDATE_LOCATION",
    "INSERT_SUBSCRIBER_DATA",
    "UPDATE_LOCATION_ACK",
    "CREATE_SESSION",
    "INITIAL_CONTEXT_SETUP",
    "ATTACH_ACCEPT",
    "ATTACH_COMPLETE",
    "MODIFY_BEARER",
]

TAU_FLOW: List[str] = [
    "RRC_CONNECTION",
    "INITIAL_UE_MESSAGE",
    "AUTH_REQUEST",
    "AUTH_RESPONSE",
    "SECURITY_MODE_COMMAND",
    "SECURITY_MODE_COMPLETE",
    "UPDATE_LOCATION",
    "UPDATE_LOCATION_ACK",
    "TAU_ACCEPT",
    "TAU_COMPLETE",
]

SERVICE_REQUEST_FLOW: List[str] = [
    "SERVICE_REQUEST",
    "INITIAL_CONTEXT_SETUP",
    "SERVICE_ACCEPT",
]

# 절차별 인터페이스 매핑
STEP_INTERFACE_MAP: Dict[str, str] = {
    "AUTH_REQUEST":             "S6a_Diameter",
    "AUTH_RESPONSE":            "S6a_Diameter",
    "UPDATE_LOCATION":          "S6a_Diameter",
    "INSERT_SUBSCRIBER_DATA":   "S6a_Diameter",
    "UPDATE_LOCATION_ACK":      "S6a_Diameter",
    "CREATE_SESSION":           "S11_GTPv2C",
    "MODIFY_BEARER":            "S11_GTPv2C",
    "INITIAL_CONTEXT_SETUP":    "S1MME_S1AP",
    "UE_CONTEXT_RELEASE":       "S1MME_S1AP",
    "ATTACH_ACCEPT":            "S1MME_NAS_EMM",
    "ATTACH_COMPLETE":          "S1MME_NAS_EMM",
    "TAU_ACCEPT":               "S1MME_NAS_EMM",
    "TAU_COMPLETE":             "S1MME_NAS_EMM",
    "SERVICE_ACCEPT":           "S1MME_NAS_EMM",
    "NAS_EMM":                  "S1MME_NAS_EMM",
    "NAS_ESM":                  "S1MME_NAS_ESM",
}

# call_type → 절차 이름
_PROCEDURE_NAME: Dict[int, str] = {
    1: "ATTACH",
    2: "ATTACH",
    3: "SERVICE_REQUEST",
    4: "SERVICE_REQUEST",
    5: "TAU",
    6: "PAGING",
    7: "EXTENDED_SERVICE",
    8: "EXTENDED_SERVICE",
    9: "DETACH",
    10: "HANDOVER",
}

# call_type → flow
_FLOW_MAP: Dict[int, List[str]] = {
    1: ATTACH_FLOW,
    2: ATTACH_FLOW,
    5: TAU_FLOW,
    3: SERVICE_REQUEST_FLOW,
    4: SERVICE_REQUEST_FLOW,
}


def get_procedure_name(call_type: int) -> str:
    return _PROCEDURE_NAME.get(call_type, "UNKNOWN")


def get_procedure_flow(call_type: int) -> List[str]:
    """call_type → 해당 절차 flow 반환. 미지원은 빈 리스트."""
    return _FLOW_MAP.get(call_type, [])


def get_step_index(flow: List[str], step: str) -> int:
    """절차 내 step의 인덱스. 없으면 -1."""
    try:
        return flow.index(step)
    except ValueError:
        return -1
