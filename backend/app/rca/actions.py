"""
actions.py
Root Cause별 조치 가이드.
"""
from __future__ import annotations

from typing import Dict, List

ACTIONS: Dict[str, List[str]] = {
    "HSS_UNREACHABLE": [
        "HSS 서버 상태 및 프로세스 확인",
        "MME-HSS 간 Diameter 링크 상태 확인 (sctp association)",
        "HSS IP 연결성 확인 (ping, traceroute)",
        "Diameter 라우팅 설정 확인",
        "HSS 장애 발생 시간대 로그 수집",
    ],
    "SUBSCRIBER_NOT_PROVISIONED": [
        "HSS 가입자 프로비저닝 상태 확인 (IMSI 조회)",
        "최근 가입자 개통/해지 이력 확인",
        "HLR/HSS 동기화 상태 확인",
        "IMSI 입력 오류 여부 확인",
    ],
    "HSS_AUTH_DATA_UNAVAILABLE": [
        "HSS 인증 벡터 생성 가능 여부 확인",
        "AuC (Authentication Center) 상태 확인",
        "가입자 Ki/OPc 값 정상 여부 확인",
        "HSS 내부 오류 로그 수집",
    ],
    "SUBSCRIBER_ROAMING_RESTRICTED": [
        "가입자 로밍 서비스 가입 여부 확인",
        "방문지 PLMN 로밍 협정 여부 확인",
        "HSS 로밍 허용 PLMN 리스트 확인",
    ],
    "HSS_UPDATE_LOCATION_REJECTED": [
        "HSS Update Location 거부 원인 코드 상세 확인",
        "가입자 LTE 서비스 허용 여부 확인",
        "MME Pool 설정 확인",
        "가입자 데이터 무결성 점검",
    ],
    "HSS_VENDOR_SPECIFIC_REJECTION": [
        "HSS 운영팀에 vendor-specific 에러코드 확인 요청",
        "HSS 벤더 릴리즈 노트 및 알려진 이슈 확인",
        "발생 시간대 HSS 로그 수집",
    ],
    "UE_AUTHENTICATION_FAILURE": [
        "해당 IMSI SIM 카드 상태 확인",
        "인증 실패 반복 여부 확인 (동일 IMSI)",
        "MME 인증 벡터 캐시 초기화 검토",
        "SIM 교체 또는 재발급 검토",
    ],
    "RADIO_LINK_FAILURE": [
        "해당 eNB 커버리지 및 RF 상태 확인",
        "eNB 알람 현황 확인",
        "UE 이동 패턴 분석 (핸드오버 실패 연관성)",
        "간섭 여부 확인",
    ],
    "INITIAL_CONTEXT_SETUP_FAILURE": [
        "eNB 자원 사용률 확인 (PRB, UE 접속 수)",
        "eNB-MME S1 인터페이스 품질 확인",
        "eNB 소프트웨어 버전 및 알람 확인",
        "QoS 파라미터 설정 확인",
    ],
    "SESSION_CREATION_FAILURE": [
        "PGW APN 설정 확인",
        "SGW-PGW GTP 터널 상태 확인",
        "IP 주소 풀 고갈 여부 확인",
        "가입자 APN 구독 정보 확인",
    ],
    "SGW_PGW_UNREACHABLE": [
        "SGW/PGW 서버 상태 및 프로세스 확인",
        "MME-SGW S11 인터페이스 연결 확인",
        "GTP 터널 상태 확인",
        "라우팅 경로 확인",
    ],
    "SGW_PGW_CONTEXT_MISSING": [
        "SGW/PGW 세션 테이블 확인",
        "장애 이전 세션 정리 이력 확인",
        "SGW/PGW 재시작 이력 확인",
        "MME 재시작 후 세션 복구 절차 확인",
    ],
    "PDN_CONNECTIVITY_REJECTED": [
        "PGW PDN 연결 거부 원인 확인",
        "가입자 데이터 서비스 가입 여부 확인",
        "APN 설정 및 정책 확인",
        "PCRF 정책 설정 확인",
    ],
    "APN_OPERATOR_BARRED": [
        "PCRF/PGW APN barring 정책 적용 여부 확인",
        "해당 APN의 가입자 등급별 접속 제한 정책 확인",
        "장애 시간대 정책 배포 또는 APN 차단 이력 확인",
        "동일 APN 집중 실패 여부 확인",
    ],
    "APN_NOT_CONFIGURED_OR_UNKNOWN": [
        "HSS 가입자 APN subscription에 요청 APN 존재 여부 확인",
        "PGW APN 프로파일 및 DNS/APN selection 설정 확인",
        "동일 APN 오탈자 또는 비표준 APN 요청 집중 여부 확인",
        "최근 APN 설정 변경 및 배포 이력 확인",
    ],
    "PDN_SUBSCRIBER_AUTH_FAILED": [
        "APN별 AAA/RADIUS 인증 로그 확인",
        "가입자 credential 또는 APN 인증 프로파일 확인",
        "PGW와 AAA 간 연결 및 응답 코드 확인",
        "동일 IMSI 반복 인증 실패 여부 확인",
    ],
    "APN_SERVICE_NOT_SUBSCRIBED": [
        "HSS/UDR 가입자 APN 서비스 가입 상태 확인",
        "요청 APN과 허용 APN 리스트 불일치 여부 확인",
        "최근 상품/요금제 변경 이력 확인",
        "가입자 그룹별 정책 적용 범위 확인",
    ],
    "PGW_SGW_RESOURCE_OR_POLICY_REJECT": [
        "PGW/SGW 세션 생성 거부 로그 확인",
        "PGW IP pool 및 bearer/session 자원 사용률 확인",
        "SGW-PGW GTP 경로와 peer 상태 확인",
        "APN별 정책 또는 용량 제한 초과 여부 확인",
    ],
    "S1AP_INTERFACE_TIMEOUT": [
        "eNB-MME S1 링크 상태 확인",
        "SCTP association 상태 확인",
        "네트워크 경로 지연 측정",
        "MME S1 처리 부하 확인",
    ],
    "MME_INTERNAL_ERROR": [
        "MME 프로세스 상태 및 로그 확인",
        "MME 메모리/CPU 사용률 확인",
        "MME 소프트웨어 버전 및 알려진 버그 확인",
        "MME 재시작 필요 여부 검토",
    ],
    "UNKNOWN": [
        "전체 xDR 로그 원본 재검토",
        "관련 네트워크 장비 로그 수집",
        "타임스탬프 기반 연관 이벤트 분석",
        "운영팀 에스컬레이션",
    ],
}


def get_actions(root_cause: str) -> List[str]:
    """root_cause → 조치 가이드 반환. 없으면 UNKNOWN 반환."""
    return ACTIONS.get(root_cause, ACTIONS["UNKNOWN"])
