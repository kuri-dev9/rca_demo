# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Ollama 로컬 LLM 기반 웹 채팅 애플리케이션. FastAPI 백엔드 + React 프론트엔드로 구성되며, BM25+TF-IDF 하이브리드 RAG, SSE 스트리밍, 멀티 세션 대화, 파일 첨부, 지식 저장소를 지원한다.

## Common Commands

### Backend

```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend

```bash
cd frontend
npm start          # dev server on port 3000
npm run build      # production build
npx tsc --noEmit   # type check without emitting
```

### Startup Scripts

```bash
./scripts/start-backend.sh    # activates venv + starts uvicorn
./scripts/start-frontend.sh   # PORT=3000 npm start
```

### Database (MySQL 8.4 via Docker)

```bash
docker exec mysql84 mysql -uroot -p<password> -e "CREATE DATABASE IF NOT EXISTS chat_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

테이블은 앱 시작 시 SQLAlchemy `metadata.create_all()`로 자동 생성된다. 컬럼 추가 시 `ALTER TABLE`을 직접 실행해야 한다 (Alembic 미사용).

### Backend Import Check

```bash
cd backend && python -c "from app.models import *; from app.schemas import *; print('OK')"
```

## Architecture

### Backend (FastAPI, Python 3.10+)

- `app/main.py` — 앱 생성, CORS (`localhost:3000`), 라우터 등록, lifespan에서 DB 테이블 생성
- `app/config.py` — `pydantic-settings`로 `.env` 파일에서 `DATABASE_URL`, `OLLAMA_BASE_URL` 로드
- `app/database.py` — SQLAlchemy async 엔진, `get_db()` 의존성
- `app/models.py` — ORM: `Conversation`(system_prompt 포함), `Message`(references JSON), `Attachment`, `KnowledgeDocument`(summary 포함)
- `app/schemas.py` — Pydantic v2 요청/응답 스키마, 검색/내보내기/가져오기 타입 포함

**Routes:**
- `routes/chat.py` — 핵심 채팅 로직. SSE 스트리밍, 2단계 RAG(요약 매칭 → 청크 검색), 첨부파일 컨텍스트, 시스템 프롬프트 조합, 자동 제목 생성
- `routes/conversations.py` — CRUD + 전문 검색(`/search?q=`), JSON/Markdown 내보내기, JSON 가져오기
- `routes/knowledge.py` — 지식 문서 업로드 시 `BackgroundTasks`로 비동기 처리 (텍스트 추출 → LLM 요약 생성 → 청킹 → 인덱싱)
- `routes/attachments.py` — 대화별 파일 업로드/삭제

**RAG Pipeline (2단계):**
1. **문서 요약 매칭** (`chat.py:_compute_summary_similarity`): 질문과 각 문서의 LLM 생성 요약 간 TF-IDF 코사인 유사도 계산. 임계값 0.01 이상이면 우선 문서로 선정
2. **청크 검색** (`vector_store.py`): BM25Okapi + TF-IDF 코사인 유사도 하이브리드 (가중치 0.5/0.5). 우선 문서의 청크를 상위 배치하고 해당 문서 요약도 컨텍스트에 포함. pickle로 `knowledge_data/index.pkl`에 영속화

**파일 처리:**
- `file_parser.py` — PDF, DOCX, HWP/HWPX(한글), Excel, 코드 등 텍스트 추출
- `chunker.py` — 단락 인식 분할, 500자 청크, 50자 오버랩

### Frontend (React 19, TypeScript)

- `App.tsx` — 전체 상태 관리 허브. conversations, messages, streaming, systemPrompt 등 모든 상태를 useState로 관리
- `api.ts` — REST 호출 + `streamChat()` SSE 클라이언트. `AbortController`로 스트리밍 취소 지원. API_BASE는 `http://localhost:8000/api`로 하드코딩
- `types.ts` — `Conversation`, `Message`, `SearchResult`, `KnowledgeDoc` 등 인터페이스

**Components:**
- `Sidebar.tsx` — 대화 목록 + 디바운스 검색 (300ms) + 내보내기 드롭다운(JSON/Markdown) + 가져오기 버튼
- `ChatMessage.tsx` — react-markdown + remark-gfm + react-syntax-highlighter(Prism) 렌더링, RAG 참조 칩 표시
- `ChatInput.tsx` — 동적 높이 textarea, 파일 첨부 칩, 전송/중지 버튼
- `SystemPromptEditor.tsx` — 모달, 7개 프리셋 템플릿 (번역가, 코드 리뷰어, 영어 선생님, 이동통신 전문가 등) + 직접 편집. 시스템 프롬프트는 대화별로 DB에 영속 저장
- `KnowledgePanel.tsx` — 지식 문서 업로드/삭제 모달, 3초 간격 상태 폴링, 문서 요약 펼침/접기 표시

### Data Flow: Chat Request

1. 프론트엔드 `streamChat()` → `POST /api/conversations/{id}/chat` (SSE)
2. 백엔드에서 대화 로드 (messages + attachments)
3. **1단계 RAG — 요약 매칭**: `KnowledgeDocument.summary`가 있는 문서들의 요약과 질문 간 TF-IDF 코사인 유사도 비교 → 우선 문서 선정
4. **2단계 RAG — 청크 검색**: `vector_store.search()` → 우선 문서 청크를 상위 배치, 요약 컨텍스트도 포함 (최대 7개 청크)
5. 시스템 프롬프트 조합: `[사용자 시스템 프롬프트] + [RAG 컨텍스트(요약+청크)] + [첨부파일 컨텍스트]`
6. Ollama `/api/chat` 스트리밍 호출, 토큰/thinking 이벤트를 SSE로 전달
7. 완료 시 assistant 메시지 DB 저장 (참조 문서에 `matched_summary` 플래그 포함), 첫 메시지면 자동 제목 생성

### Styling

CSS 변수 기반 다크/라이트 테마. `document.documentElement`에 `data-theme` 속성으로 전환. 모든 스타일은 `App.css` 단일 파일에 관리.

## Key Conventions

- 백엔드 전체가 async/await (SQLAlchemy async, httpx async)
- DB 마이그레이션 도구 없음 — 컬럼 추가 시 `ALTER TABLE` SQL 직접 실행 필요
- 프론트엔드 상태는 App.tsx에 집중 (Redux/Zustand 미사용)
- 한국어 UI/UX — 에러 메시지, 프리셋 템플릿, 자동 제목 생성 모두 한국어
- 한글 파일명 내보내기 시 `urllib.parse.quote`로 URL 인코딩 필요 (latin-1 헤더 제약)
- Ollama API: 모델 목록 `/api/tags`, 채팅 `/api/chat`, 단일 생성 `/api/generate`
- 요약 유사도 계산 시 BM25는 문서 1개일 때 음수를 반환할 수 있으므로 TF-IDF 코사인 유사도 단독 사용 (`_compute_summary_similarity`)
- 지식 문서 요약은 업로드 시 Ollama `gemma4:26b`로 생성 (텍스트 앞 4000자 기반, 3~5문장)

## Ports

| Service  | Port  |
|----------|-------|
| Frontend | 3000  |
| Backend  | 8000  |
| MySQL    | 3306  |
| Ollama   | 11434 |
