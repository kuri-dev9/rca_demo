"""
rules.py
Failure Semantic → Root Cause 매핑 규칙.
"""
from __future__ import annotations

from typing import Dict

ROOT_CAUSE_RULES: Dict[str, dict] = {
    # S6a Authentication
    "S6A_AUTH_TIMEOUT": {
        "root_cause": "HSS_UNREACHABLE",
        "category": "HSS",
        "subcategory": "Connectivity",
        "severity": "CRITICAL",
        "confidence": 0.90,
        "description": "S6a 인터페이스 Authentication Information Request 타임아웃. HSS 연결 불가 또는 Diameter 링크 장애.",
    },
    "S6A_AUTH_DATA_UNAVAILABLE": {
        "root_cause": "HSS_AUTH_DATA_UNAVAILABLE",
        "category": "HSS",
        "subcategory": "Data",
        "severity": "HIGH",
        "confidence": 0.85,
        "description": "HSS가 인증 데이터를 반환 불가. 가입자 데이터 불일치 또는 HSS 내부 오류.",
    },
    "S6A_USER_UNKNOWN": {
        "root_cause": "SUBSCRIBER_NOT_PROVISIONED",
        "category": "HSS",
        "subcategory": "Provisioning",
        "severity": "HIGH",
        "confidence": 0.92,
        "description": "HSS에서 IMSI를 찾을 수 없음. 가입자 미등록 또는 IMSI 오류.",
    },
    "S6A_UPDATE_LOCATION_TIMEOUT": {
        "root_cause": "HSS_UNREACHABLE",
        "category": "HSS",
        "subcategory": "Connectivity",
        "severity": "CRITICAL",
        "confidence": 0.88,
        "description": "S6a Update Location Request 타임아웃.",
    },
    "S6A_UPDATE_LOCATION_FAIL": {
        "root_cause": "HSS_UPDATE_LOCATION_REJECTED",
        "category": "HSS",
        "subcategory": "Authorization",
        "severity": "HIGH",
        "confidence": 0.82,
        "description": "HSS가 Update Location을 거부. 가입자 로밍 제한 또는 서비스 불허.",
    },
    "S6A_ROAMING_NOT_ALLOWED": {
        "root_cause": "SUBSCRIBER_ROAMING_RESTRICTED",
        "category": "HSS",
        "subcategory": "Authorization",
        "severity": "MEDIUM",
        "confidence": 0.95,
        "description": "HSS 로밍 불허 정책. 가입자 로밍 미가입.",
    },
    "S6A_VENDOR_SPECIFIC": {
        "root_cause": "HSS_VENDOR_SPECIFIC_REJECTION",
        "category": "HSS",
        "subcategory": "Vendor",
        "severity": "HIGH",
        "confidence": 0.70,
        "description": "HSS 벤더 특정 에러코드. HSS 운영팀 확인 필요.",
    },
    # S1AP
    "S1AP_AUTH_FAILURE": {
        "root_cause": "UE_AUTHENTICATION_FAILURE",
        "category": "UE",
        "subcategory": "Authentication",
        "severity": "MEDIUM",
        "confidence": 0.80,
        "description": "NAS 인증 실패로 S1AP Release. UE SIM 오류 또는 인증 벡터 불일치.",
    },
    "S1AP_RADIO_LOST": {
        "root_cause": "RADIO_LINK_FAILURE",
        "category": "RAN",
        "subcategory": "Radio",
        "severity": "MEDIUM",
        "confidence": 0.85,
        "description": "무선 연결 손실. UE 이동 또는 커버리지 불량.",
    },
    "S1AP_INITIAL_CONTEXT_FAIL": {
        "root_cause": "INITIAL_CONTEXT_SETUP_FAILURE",
        "category": "RAN",
        "subcategory": "Radio",
        "severity": "HIGH",
        "confidence": 0.78,
        "description": "Initial Context Setup 실패. eNB 자원 부족 또는 무선 환경 불량.",
    },
    "S1AP_TIMEOUT": {
        "root_cause": "S1AP_INTERFACE_TIMEOUT",
        "category": "RAN",
        "subcategory": "Connectivity",
        "severity": "HIGH",
        "confidence": 0.80,
        "description": "S1AP 인터페이스 타임아웃. eNB-MME 연결 문제.",
    },
    # NAS
    "NAS_ESM_PDN_REJECT": {
        "root_cause": "PDN_CONNECTIVITY_REJECTED",
        "category": "Core",
        "subcategory": "PGW",
        "severity": "HIGH",
        "confidence": 0.75,
        "description": "PDN Connectivity Reject. PGW APN 정책 또는 가입자 서비스 미가입.",
    },
    "NAS_ESM_OPERATOR_BARRING": {
        "root_cause": "APN_OPERATOR_BARRED",
        "category": "Core",
        "subcategory": "Policy/APN",
        "severity": "HIGH",
        "confidence": 0.86,
        "description": "NAS ESM Operator Determined Barring. APN 또는 가입자 정책에 의해 PDN 연결이 차단됨.",
    },
    "NAS_ESM_APN_UNKNOWN": {
        "root_cause": "APN_NOT_CONFIGURED_OR_UNKNOWN",
        "category": "Core",
        "subcategory": "APN/PGW",
        "severity": "HIGH",
        "confidence": 0.90,
        "description": "NAS ESM Missing or unknown APN. UE 요청 APN이 HSS/PGW 정책 또는 APN 테이블에 없을 가능성이 높음.",
    },
    "NAS_ESM_AUTH_FAILED": {
        "root_cause": "PDN_SUBSCRIBER_AUTH_FAILED",
        "category": "Core",
        "subcategory": "AAA/PGW",
        "severity": "HIGH",
        "confidence": 0.86,
        "description": "NAS ESM 사용자 인증 실패. APN별 인증/AAA 또는 가입자 credential 확인 필요.",
    },
    "NAS_ESM_SERVICE_NOT_SUBSCRIBED": {
        "root_cause": "APN_SERVICE_NOT_SUBSCRIBED",
        "category": "Core",
        "subcategory": "Subscription",
        "severity": "MEDIUM",
        "confidence": 0.88,
        "description": "요청 서비스 옵션 미가입. HSS/UDR 가입자 APN subscription 확인 필요.",
    },
    "NAS_ESM_CORE_RESOURCE_REJECT": {
        "root_cause": "PGW_SGW_RESOURCE_OR_POLICY_REJECT",
        "category": "Core",
        "subcategory": "SGW/PGW",
        "severity": "HIGH",
        "confidence": 0.82,
        "description": "SGW/PGW 또는 자원 부족으로 PDN 연결이 거부됨. PGW 자원, IP pool, 정책 상태 확인 필요.",
    },
    "NAS_EMM_NETWORK_FAILURE": {
        "root_cause": "MME_INTERNAL_ERROR",
        "category": "Core",
        "subcategory": "MME",
        "severity": "HIGH",
        "confidence": 0.72,
        "description": "NAS Network Failure. MME 내부 오류.",
    },
    # S11 GTP
    "GTP_CONTEXT_NOT_FOUND": {
        "root_cause": "SGW_PGW_CONTEXT_MISSING",
        "category": "Core",
        "subcategory": "SGW/PGW",
        "severity": "HIGH",
        "confidence": 0.82,
        "description": "S11 Context Not Found. SGW/PGW 세션 컨텍스트 소실.",
    },
    "GTP_CREATE_SESSION_FAIL": {
        "root_cause": "SESSION_CREATION_FAILURE",
        "category": "Core",
        "subcategory": "PGW",
        "severity": "HIGH",
        "confidence": 0.80,
        "description": "Create Session 실패. APN 설정 오류 또는 PGW 자원 부족.",
    },
    "GTP_TIMEOUT": {
        "root_cause": "SGW_PGW_UNREACHABLE",
        "category": "Core",
        "subcategory": "SGW/PGW",
        "severity": "CRITICAL",
        "confidence": 0.85,
        "description": "S11 GTP 타임아웃. SGW/PGW 연결 불가.",
    },
    # 기본값
    "UNKNOWN": {
        "root_cause": "UNKNOWN",
        "category": "Unknown",
        "subcategory": "Unknown",
        "severity": "LOW",
        "confidence": 0.30,
        "description": "분석 불가.",
    },
}


def get_root_cause(semantic: str) -> dict:
    """semantic key → root cause dict 반환. 없으면 UNKNOWN 반환."""
    return ROOT_CAUSE_RULES.get(semantic, ROOT_CAUSE_RULES["UNKNOWN"])
