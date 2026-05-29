# Ollama Chat Demo

Ollama 로컬 LLM을 활용한 웹 기반 채팅 애플리케이션입니다.

## 주요 기능

- **멀티 세션 대화** — 여러 대화방 생성/삭제/전환, 대화 이력 DB 저장
- **실시간 스트리밍** — 토큰 단위 SSE 스트리밍 응답, thinking 상태 표시
- **모델 선택** — Ollama에 설치된 모든 모델 조회 및 전환
- **마크다운 렌더링** — 코드 블록(구문 강조 + 복사), 테이블, 리스트 등
- **파일 첨부** — 문서를 업로드하면 내용을 컨텍스트로 활용하여 대화
- **지식 저장소 (RAG)** — 문서를 글로벌 지식으로 등록, 이후 모든 대화에서 관련 내용 자동 참조
- **자동 제목 생성** — 첫 대화 내용 기반 LLM 자동 요약, 더블클릭으로 수동 편집
- **응답 중지** — 스트리밍 중 중지 버튼으로 응답 취소
- **다크/라이트 테마** — 토글 버튼으로 전환

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | Python, FastAPI, SQLAlchemy (async), httpx |
| Frontend | React, TypeScript, react-markdown, react-syntax-highlighter |
| Database | MySQL 8.4 (Docker) |
| LLM | Ollama (로컬 서빙) |
| 검색/RAG | BM25 (rank_bm25) + TF-IDF (scikit-learn) 하이브리드 |
| 통신 | REST API + SSE (Server-Sent Events) |

## 프로젝트 구조

```
chat-demo/
├── backend/
│   ├── .env                          # 환경변수 (DB URL, Ollama URL)
│   ├── requirements.txt
│   └── app/
│       ├── main.py                   # FastAPI 엔트리포인트, CORS, 라우터 등록
│       ├── config.py                 # 환경설정 (pydantic-settings)
│       ├── database.py               # SQLAlchemy async 엔진/세션
│       ├── models.py                 # DB 모델 (Conversation, Message, Attachment, KnowledgeDocument)
│       ├── schemas.py                # Pydantic 스키마
│       ├── file_parser.py            # 파일 텍스트 추출 (PDF, DOCX, HWP, HWPX, Excel 등)
│       ├── chunker.py                # 텍스트 청크 분할 (단락 인식, 오버랩)
│       ├── vector_store.py           # BM25+TF-IDF 하이브리드 검색 엔진
│       └── routes/
│           ├── conversations.py      # 대화방 CRUD
│           ├── chat.py               # SSE 스트리밍 채팅, RAG 통합, 자동 제목 생성
│           ├── models.py             # Ollama 모델 목록
│           ├── attachments.py        # 파일 업로드/조회/삭제
│           └── knowledge.py          # 지식 저장소 문서 관리
├── frontend/
│   ├── package.json
│   └── src/
│       ├── App.tsx                   # 메인 앱 (상태 관리, 이벤트 핸들링)
│       ├── App.css                   # 전체 스타일 (다크/라이트 테마)
│       ├── api.ts                    # 백엔드 API 호출 함수
│       ├── types.ts                  # TypeScript 타입 정의
│       └── components/
│           ├── Sidebar.tsx           # 대화 목록, 생성/삭제/이름 편집
│           ├── ChatMessage.tsx       # 메시지 렌더링 (마크다운, 코드 복사)
│           ├── ChatInput.tsx         # 입력창, 파일 첨부, 전송/중지 버튼
│           ├── ModelSelector.tsx     # 모델 선택 드롭다운
│           ├── ThemeToggle.tsx       # 다크/라이트 토글
│           └── KnowledgePanel.tsx    # 지식 저장소 관리 모달
└── scripts/
    ├── start-backend.sh
    └── start-frontend.sh
```

## 사전 요구사항

- **Python** 3.10+
- **Node.js** 18+, npm
- **Docker** (MySQL 컨테이너)
- **Ollama** (로컬 설치, 모델 다운로드 완료)

## 설치 및 실행

### 1. MySQL 준비

```bash
# Docker MySQL이 실행 중이어야 합니다
docker ps | grep mysql

# chat_demo 데이터베이스 생성
docker exec <컨테이너명> mysql -uroot -p<비밀번호> \
  -e "CREATE DATABASE IF NOT EXISTS chat_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
```

### 2. 백엔드 설정

```bash
cd backend

# 가상환경 생성 및 활성화
python3 -m venv venv
source venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정 (.env 파일 수정)
# DATABASE_URL=mysql+aiomysql://<user>:<password>@localhost:3306/chat_demo
# OLLAMA_BASE_URL=http://localhost:11434
```

### 3. 프론트엔드 설정

```bash
cd frontend
npm install
```

### 4. 실행

터미널 2개에서 각각 실행합니다.

```bash
# 터미널 1: 백엔드 (포트 8000)
./scripts/start-backend.sh

# 터미널 2: 프론트엔드 (포트 3000)
./scripts/start-frontend.sh
```

브라우저에서 **http://localhost:3000** 으로 접속합니다.

## 지원 첨부파일 형식

| 분류 | 확장자 |
|------|--------|
| 문서 | `.pdf`, `.docx`, `.hwp`, `.hwpx` |
| 스프레드시트 | `.xlsx`, `.xls`, `.csv` |
| 코드 | `.py`, `.js`, `.ts`, `.jsx`, `.tsx`, `.java`, `.c`, `.cpp`, `.go`, `.rs`, `.sql`, `.sh` |
| 웹/마크업 | `.html`, `.css`, `.xml`, `.yaml`, `.yml`, `.json`, `.md` |
| 텍스트 | `.txt`, `.log` |

## API 엔드포인트

| Method | URL | 설명 |
|--------|-----|------|
| GET | `/api/health` | 헬스체크 |
| GET | `/api/models` | Ollama 모델 목록 |
| GET | `/api/conversations` | 대화 목록 |
| POST | `/api/conversations` | 대화 생성 |
| GET | `/api/conversations/:id` | 대화 상세 (메시지 포함) |
| PATCH | `/api/conversations/:id` | 대화 수정 (제목, 모델) |
| DELETE | `/api/conversations/:id` | 대화 삭제 |
| POST | `/api/conversations/:id/chat` | 채팅 (SSE 스트리밍) |
| GET | `/api/conversations/:id/attachments` | 첨부파일 목록 |
| POST | `/api/conversations/:id/attachments` | 파일 업로드 |
| DELETE | `/api/conversations/:id/attachments/:aid` | 첨부파일 삭제 |
| GET | `/api/knowledge` | 지식 문서 목록 |
| POST | `/api/knowledge/upload` | 지식 문서 업로드 |
| GET | `/api/knowledge/:id/status` | 문서 처리 상태 조회 |
| DELETE | `/api/knowledge/:id` | 지식 문서 삭제 |

## 지식 저장소 (RAG)

헤더의 **📚 지식 저장소** 버튼으로 문서를 글로벌 지식으로 등록할 수 있습니다.

**동작 원리:**
1. 문서 업로드 → 텍스트 추출 → 500자 단위 청크 분할 (50자 오버랩)
2. 청크를 BM25 + TF-IDF 하이브리드 인덱스에 저장
3. 사용자가 질문하면 BM25(0.5) + TF-IDF 코사인 유사도(0.5)로 관련 청크 검색
4. 검색 결과를 시스템 프롬프트에 포함하여 LLM이 참조

**특징:**
- 별도 임베딩 모델 불필요 (BM25 + TF-IDF만 사용)
- 업로드된 문서는 모든 대화에서 자동 참조
- 백그라운드 비동기 처리 (대용량 문서도 UI 블로킹 없음)

## 환경변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DATABASE_URL` | `mysql+aiomysql://root:root@localhost:3306/chat_demo` | MySQL 접속 URL |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama API URL |
