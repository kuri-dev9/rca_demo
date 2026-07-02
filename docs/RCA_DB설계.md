RCA Experiment Platform DB 설계 v1.0

1. 개요

기존 RCA 시스템은 단일 입력 데이터에 대해 단일 프롬프트를 수행하고 결과를 반환하는 구조이다.

향후 목표는 단순 RCA 수행이 아니라 다음과 같은 실험 플랫폼 구축이다.

* 동일 입력 데이터에 대해 여러 프롬프트 비교
* RCA Loop Mode 실험
* Prompt 변경 이력 관리
* 결과 저장 및 재분석
* LLM 기반 품질 평가
* Prompt Evolution 자동화 기반 확보

이를 위해 RCA 수행 과정 전체를 DB에 저장하고, 반복 실행 및 비교 분석이 가능한 구조로 설계한다.

⸻

2. 설계 원칙

2.1 입력 데이터와 결과 분리

동일한 입력 데이터에 대해 여러 Prompt를 수행할 수 있어야 한다.

INPUT A
 ├─ Prompt A
 ├─ Prompt B
 └─ Prompt C

따라서 Input, Prompt, Result는 각각 독립적으로 관리한다.

⸻

2.2 Loop 구조 고정 금지

현재 Loop Mode는 Step1 ~ Step4 구조이지만 향후 다음과 같이 변경될 수 있다.

Loop V1
 ├─ Step1
 ├─ Step2
 ├─ Step3
 └─ Step4
Loop V2
 ├─ Reflection
 ├─ Critic
 ├─ Judge
 └─ Final
Loop V3
 ├─ Domain Judge
 ├─ Confidence Judge
 ├─ RCA Builder
 └─ Final

따라서 DB에는 Step 개수를 고정하지 않고 Run-Step 구조로 설계한다.

⸻

2.3 Prompt는 역할을 갖지 않는다

Prompt는 단순 텍스트 데이터로 저장한다.

Prompt A
Prompt B
Prompt C

Prompt 자체에

STEP1
STEP2
NORMAL
LOOP

같은 역할을 부여하지 않는다.

어떤 역할로 사용되었는지는 Run-Step에서 관리한다.

⸻

3. 테이블 정의

3.1 PR_RCA_INPUT

RCA 수행 시 입력으로 사용되는 데이터 저장

실제 저장 데이터는 xDR 원본이 아니라 RCA 전처리 결과인 통계 데이터이다.

컬럼	설명
input_id	PK
text	RCA 입력 데이터
hash	중복 데이터 방지
priority	장기 기억 중요도
update_dt	수정일

⸻

3.2 PR_RCA_PROMPT

RCA 수행 시 사용되는 Prompt 저장

컬럼	설명
prompt_id	PK
text	Prompt 데이터
hash	중복 데이터 방지
priority	장기 기억 중요도
update_dt	수정일

⸻

3.3 PR_RCA_RUN

RCA 실행 단위

Normal Mode 또는 Loop Mode를 구분한다.

컬럼	설명
run_id	PK
run_mode	NORMAL / LOOP
update_dt	수정일

⸻

3.4 PR_RCA_STEP

Run 내부 수행 단계 저장

Normal Mode는 Step 1개,
Loop Mode는 Step 여러 개를 가진다.

컬럼	설명
step_id	PK
step_type	1, 2, 2-A, Reflection, Critic 등
run_id	Run ID
input_id	입력 데이터
prompt_id	사용 Prompt
result_id	수행 결과
priority	장기 기억 중요도
update_dt	수정일

⸻

3.5 PR_RCA_RESULT

LLM 수행 결과 저장

컬럼	설명
result_id	PK
text	RCA 결과
hallucination_score	환각 점수
over_confidence_score	과도한 단정 점수
evidence_missing_score	근거 부족 점수
domain_bias_score	도메인 편향 점수
evaluation_comment	평가 내용
priority	장기 기억 중요도
update_dt	수정일

⸻

4. 동작 예시

Normal Mode

RUN #100
STEP 1
 ├─ INPUT #1
 ├─ PROMPT #10
 └─ RESULT #1000

⸻

Loop Mode

RUN #200
STEP 1
 ├─ INPUT #1
 ├─ PROMPT #11
 └─ RESULT #2001
STEP 2
 ├─ INPUT #2001
 ├─ PROMPT #12
 └─ RESULT #2002
STEP 3
 ├─ INPUT #2002
 ├─ PROMPT #13
 └─ RESULT #2003
STEP 4
 ├─ INPUT #2003
 ├─ PROMPT #14
 └─ RESULT #2004

⸻

5. 향후 확장 계획

Phase 1

* DB 구축
* Prompt 저장
* Input 저장
* RCA 결과 저장

Phase 2

* Batch 실행 엔진
* 동일 Input 다중 Prompt 비교

Phase 3

* 통계 분석 엔진
* Prompt별 결과 비교

Phase 4

* LLM 평가기
* Hallucination 분석
* Bias 분석

Phase 5

* Prompt Evolution
* 자동 Prompt 개선
* 장기 학습 시스템