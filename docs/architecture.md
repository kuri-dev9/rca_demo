현재 프로젝트는 범용 AI/RAG 플랫폼 방향을 중단하고,
실제 LTE xDR 기반 RCA 엔진으로 재구성한다.

이번 작업부터는 반드시 아래 실제 운영 데이터와 스펙 문서를 기준으로 구현한다.

-----------------------------------
[실제 입력 데이터]
-----------------------------------

1. LTE-CALL-KPI 실제 xDR 데이터
- LTE-CALL-KPI_R1_20260518_1100.dat

2. Cause 정의 문서
- XDR_Cause_v0.5.xlsx

3. MessageCode 정의 문서
- XDR_MessageCode_v0.6.xlsx

4. xDR 필드 스펙 문서
- XDR_Specification_s-probe_corr_20210729.xlsx

반드시 이 문서들을 직접 읽고 구현할 것.
임의 추정 금지.

-----------------------------------
[중요]
-----------------------------------

실제 xDR 데이터는 일반 문자열 구분자가 아니라
RS(0x1E) 기반 구분자일 가능성이 매우 높다.

즉 parser는 아래 방식 우선 검토:

line.split("\x1e")

기존 "^^" split 방식 고정 금지.

실제 데이터 구조를 먼저 분석하고 parser 구현할 것.

-----------------------------------
[프로젝트 목표]
-----------------------------------

"xDR 파일 기반 LTE RCA 자동 생성 시스템"

LLM은 RCA 판단 엔진이 아니다.

LLM 역할:
- 운영자용 보고서 생성
- 자연어 설명
- 장애 영향 요약
- 조치 설명

실제 RCA 판단은 deterministic engine 기반으로 구현.

-----------------------------------
[최종 아키텍처]
-----------------------------------

xDR Upload
→ Parser
→ Normalized Event
→ Procedure Analyzer
→ Failure Chain Builder
→ Root Cause Estimator
→ Action Recommendation
→ LLM Report Generator
→ Frontend Display

-----------------------------------
[유지할 기존 chat_demo 기능]
-----------------------------------

유지:

- FastAPI
- React UI
- SSE Streaming
- Ollama 연동
- Attachment 업로드
- Conversation 저장
- Model 선택

제거 또는 축소:

- 범용 RAG
- UCE
- DPE
- taxonomy evolution
- graph reasoning
- multi-agent
- 범용 observability 구조

-----------------------------------
[지원 LTE 절차]
-----------------------------------

초기 MVP 지원:

1. Attach
2. TAU
3. Service Request

절대 전체 LTE procedure 구현부터 시작하지 말 것.

-----------------------------------
[신규 디렉토리]
-----------------------------------

backend/app/rca/

생성.

-----------------------------------
[모듈 구조]
-----------------------------------

backend/app/rca/

- parser.py
- spec_loader.py
- code_mapper.py
- normalizer.py
- procedures.py
- chain_builder.py
- rules.py
- analyzer.py
- actions.py
- report_builder.py

-----------------------------------
[spec_loader.py]
-----------------------------------

역할:
xlsx specification/cause/messagecode 로딩.

필수 구현:

1. XDR field schema 로딩
2. MessageCode mapping 로딩
3. Cause mapping 로딩
4. internal dictionary 생성

예시:

MESSAGE_CODE_MAP = {
    1: "S6a_Diameter",
    2: "S1MME_S1AP"
}

CAUSE_MAP = {
    ("S1AP", 100): {
        "meaning": "Unspecified",
        "description": "..."
    }
}

-----------------------------------
[parser.py]
-----------------------------------

역할:
실제 LTE-CALL-KPI 데이터 parsing.

반드시:
- 실제 delimiter 자동 분석
- field count validation
- malformed row 처리

구현.

출력 객체:

class XdrRecord:
    call_type
    imsi
    mme
    enb
    apn

    first_error_interface
    first_error_code

    last_error_interface
    last_error_code

    start_time
    end_time

    result

field 위치는 반드시 specification 문서 기반으로 자동 매핑할 것.

하드코딩 최소화.

-----------------------------------
[code_mapper.py]
-----------------------------------

역할:
raw numeric code → protocol/interface/cause 의미 변환.

예시:

interface_code=1
→ S6a_Diameter

cause=5001
→ USER_UNKNOWN

반드시:
- MessageCode 문서 기반
- Cause 문서 기반

매핑 구현.

-----------------------------------
[normalizer.py]
-----------------------------------

역할:
raw event → semantic event 변환.

예시:

S6a + USER_UNKNOWN
→ S6A_USER_UNKNOWN

S11 + CONTEXT_NOT_FOUND
→ GTP_CONTEXT_NOT_FOUND

semantic event 기반으로 이후 RCA 수행.

-----------------------------------
[procedures.py]
-----------------------------------

LTE procedure template 정의.

예시:

ATTACH_FLOW = [
    "RRC_CONNECTION",
    "INITIAL_UE_MESSAGE",
    "AUTH_REQUEST",
    "AUTH_RESPONSE",
    "SECURITY_MODE",
    "UPDATE_LOCATION",
    "CREATE_SESSION",
    "INITIAL_CONTEXT_SETUP",
    "ATTACH_ACCEPT"
]

TAU_FLOW
SERVICE_REQUEST_FLOW
구현.

-----------------------------------
[chain_builder.py]
-----------------------------------

Expected Procedure vs Observed Procedure 비교 기반으로
Failure Chain 생성.

핵심 원칙:

- 마지막 에러 사용 금지
- 최초 실패 이벤트 사용
- Root Cause는 first failure 기준

예시:

AUTH_SUCCESS
→ UPDATE_LOCATION_FAIL
→ ATTACH_REJECT

결과:

{
  "procedure": "ATTACH",
  "failure_chain": [
    "AUTH_SUCCESS",
    "UPDATE_LOCATION_FAIL",
    "ATTACH_REJECT"
  ],
  "root_failure": "UPDATE_LOCATION_FAIL"
}

-----------------------------------
[rules.py]
-----------------------------------

Failure Event → Root Cause 매핑.

예시:

ROOT_CAUSE_RULES = {
    "S6A_USER_UNKNOWN": {
        "root_cause": "SUBSCRIBER_NOT_PROVISIONED",
        "category": "HSS",
        "severity": "HIGH",
        "confidence": 0.85
    }
}

-----------------------------------
[analyzer.py]
-----------------------------------

필수 통계:

- total_records
- success_count
- failure_count
- failure_rate
- affected_users
- interface_distribution
- error_distribution
- mme_distribution
- enb_distribution
- apn_distribution
- time_concentration

추가:

- IMSI grouping
- repeated failure detection
- burst detection

-----------------------------------
[actions.py]
-----------------------------------

Root Cause별 조치 가이드 생성.

예시:

ACTIONS = {
    "S6A_USER_UNKNOWN": [
        "HSS 가입자 상태 확인",
        "IMSI provisioning 여부 확인",
        "MME-HSS Diameter routing 확인",
        "최근 가입자 배포 이력 확인"
    ]
}

-----------------------------------
[report_builder.py]
-----------------------------------

LLM 입력용 RCA context 생성.

중요:
raw xDR 직접 전달 금지.

LLM에는 아래만 전달:

- RCA 결과
- statistics
- failure_chain
- root_cause
- actions
- affected_users
- impacted_nodes

예시:

{
  "procedure": "ATTACH",
  "failure_rate": 23.1,
  "primary_root_cause": "S6A_USER_UNKNOWN",
  "affected_users": 312,
  "failure_chain": [
    "AUTH_SUCCESS",
    "S6A_USER_UNKNOWN",
    "ATTACH_REJECT"
  ],
  "recommended_actions": [
    "HSS 가입자 상태 확인",
    "IMSI provisioning 확인"
  ]
}

-----------------------------------
[LLM 역할 제한]
-----------------------------------

LLM은:
- RCA 판단 금지
- Root Cause 계산 금지
- Failure Detection 금지

LLM 역할:
- 운영자 보고서 생성
- 자연어 설명
- 장애 영향 요약
- 조치 설명

-----------------------------------
[Frontend]
-----------------------------------

신규 버튼:

[RCA 분석]

추가.

출력 UI:

1. RCA Summary
2. Failure Chain
3. Recommended Actions
4. LLM Report

-----------------------------------
[개발 우선순위]
-----------------------------------

Phase 1:
- parser
- code mapping
- Attach RCA

Phase 2:
- Failure Chain
- Action Recommendation

Phase 3:
- TAU
- Service Request
- IMSI grouping
- burst detection

-----------------------------------
[중요 철학]
-----------------------------------

이 프로젝트는:

"LLM이 LTE를 분석"

하는 프로젝트가 아니다.

핵심은:

"LTE procedure 기반 deterministic RCA engine"

이다.

LLM은 explain layer만 담당한다.
