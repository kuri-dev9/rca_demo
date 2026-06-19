"""
RCA STEP 출력 후처리 금지어 검증.
이 데이터셋의 입력 vocabulary에 존재하지 않는 통신 지식 용어/표현을
정적 목록으로 차단해 STEP 2~4 환각을 줄인다.
"""
from __future__ import annotations

GLOBAL_FORBIDDEN_TERMS: list[str] = [
    "RADIO_CONTEXT_REJECT",
    "No_Service",
    "GTP-U",
    "S5/S8",
    "GUTI",
    "AV 제공 지연",
    "부하분산",
    "이중화",
    "KPI 대시보드",
    "CPU/Memory",
    "Congestion",
    "Cell_Reselection",
    "PDP context",
    "Create Session Response",
]

STEP2_FORBIDDEN_TERMS: list[str] = [
    "Based on",
    "Procedural Links",
    "Root Cause Origin",
    "Not_Subscribed / Barred",
    "CREATE_SESSION(Timeout) → PDN_REJECT(Not_Subscribed / Barred)",
    "AIR_AIA(Unassigned) → AUTH(Synch_failure)",
]

STEP3_FORBIDDEN_TERMS: list[str] = [
    "GTP-U 경로 오류",
    "Create Session Response 실패",
    "Cell_Reselection_Failure",
    "무선 구간 문제는 배제",
    "코어 네트워크 전반의 프로토콜 처리 오류",
    "대량 세션 요청",
    "CPU/Memory 부하",
]

STEP4_FORBIDDEN_TERMS: list[str] = [
    "HSS 부하분산",
    "HSS 이중화",
    "PCRF",
    "GUTI 매칭 실패",
    "AV 제공 지연",
    "GTP-U 경로 점검",
    "S5/S8 점검",
    "KPI 대시보드 구축",
    "CPU/Memory 부하 점검",
    "Congestion 점검",
    "특정 핵심 노드(MME)를 중심으로",
    "인증 서버 가용성 증대",
    "중앙 데이터베이스",
    "인터페이스 신뢰도 문제",
    "서비스 품질 저하",
    "연결 실패 사례",
    "근본 원인으로 판단됩니다",
]

_STEP_TERMS: dict[str, list[str]] = {
    "step2": STEP2_FORBIDDEN_TERMS,
    "step3": STEP3_FORBIDDEN_TERMS,
    "step4": STEP4_FORBIDDEN_TERMS,
}


def find_forbidden_terms(step_name: str, text: str) -> list[str]:
    """text에 등장한 금지어(전역 + STEP별)를 그대로 반환한다."""
    if not text:
        return []
    candidates = GLOBAL_FORBIDDEN_TERMS + _STEP_TERMS.get(step_name, [])
    return [term for term in candidates if term in text]


def build_retry_instruction(violations: list[str]) -> str:
    joined = ", ".join(violations)
    return (
        "위 출력에는 입력 데이터에 없는 명칭/표현이 포함되었으므로 제거하고 다시 작성하라.\n"
        f"발견된 금지 표현: {joined}\n"
        "입력 데이터에 존재하는 call_type, interface, message, stage, cause 명칭만 사용하고,\n"
        "지정된 출력 구조를 그대로 유지하라."
    )
