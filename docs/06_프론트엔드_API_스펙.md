# 6. 프론트엔드 기능별 Backend API 호출 스펙

## 6.1 API 공통 사항

### 6.1.1 Base URL 구성

| 환경 | URL |
|------|-----|
| 개발 | `http://localhost:8000/api` |

> API Base URL은 `frontend/src/api.ts`의 `API_BASE` 상수에 정의되어 있습니다.

### 6.1.2 HTTP 공통 헤더

| 헤더 | 값 | 설명 |
|------|-----|------|
| Content-Type | `application/json` | JSON 요청 시 |
| Content-Type | `multipart/form-data` | 파일 업로드 시 (자동 설정) |

### 6.1.3 공통 응답 구조

별도의 공통 래퍼 없이 직접 데이터를 반환합니다.

**에러 응답:**

```json
{
  "detail": "에러 메시지"
}
```

| HTTP Status | 의미 |
|-------------|------|
| 200 | 성공 |
| 201 | 생성 성공 |
| 204 | 삭제 성공 (No Content) |
| 404 | 리소스 없음 |
| 413 | 파일 크기 초과 |
| 422 | 요청 검증 실패 |

---

## 6.2 대화 관리 (Sidebar.tsx + App.tsx)

> **React:** `App.tsx`, `Sidebar.tsx`
> **Backend:** `routes/conversations.py`

### 6.2.1 대화 목록 조회

```
App.tsx → loadConversations() → fetchConversations()
```

| 항목 | 값 |
|------|-----|
| Method | GET |
| Path | `/api/conversations` |
| 호출 시점 | 앱 초기 로딩 (useEffect), 대화 생성/삭제 후 |
| 응답 | `Conversation[]` (updated_at DESC 정렬) |

---

### 6.2.2 대화 생성

```
App.tsx → handleCreateConversation() → createConversation()
App.tsx → handleSend() → createConversation()   (대화 없을 때 자동 생성)
App.tsx → handleFileUpload() → createConversation()   (대화 없을 때 자동 생성)
App.tsx → handleSystemPromptSave() → createConversation()   (대화 없을 때 자동 생성)
```

| 항목 | 값 |
|------|-----|
| Method | POST |
| Path | `/api/conversations` |
| Body | `{ title: "새 대화", model: selectedModel, system_prompt: currentSystemPrompt \| null }` |
| 응답 | `ConversationResponse` (201) |

---

### 6.2.3 대화 상세 조회

```
App.tsx → handleSelectConversation() → fetchConversation()
```

| 항목 | 값 |
|------|-----|
| Method | GET |
| Path | `/api/conversations/{id}` |
| 호출 시점 | 사이드바에서 대화 클릭 시 |
| 응답 | `ConversationDetailResponse` (messages 포함) |
| 후처리 | messages 설정, model 동기화, system_prompt 로드 |

---

### 6.2.4 대화 수정

```
App.tsx → handleRenameConversation() → updateConversation({ title })
App.tsx → handleModelChange() → updateConversation({ model })
App.tsx → handleSystemPromptSave() → updateConversation({ system_prompt })
```

| 항목 | 값 |
|------|-----|
| Method | PATCH |
| Path | `/api/conversations/{id}` |
| Body | `{ title?, model?, system_prompt? }` (변경된 필드만) |
| 응답 | `ConversationResponse` |

---

### 6.2.5 대화 삭제

```
App.tsx → handleDeleteConversation() → deleteConversation()
```

| 항목 | 값 |
|------|-----|
| Method | DELETE |
| Path | `/api/conversations/{id}` |
| 응답 | 204 No Content |
| 후처리 | 목록에서 제거, 활성 대화면 초기화 |

---

### 6.2.6 대화 검색

```
Sidebar.tsx → handleSearch() → searchConversations()
```

| 항목 | 값 |
|------|-----|
| Method | GET |
| Path | `/api/conversations/search?q={keyword}` |
| 호출 시점 | 검색 입력 후 300ms 디바운스 |
| 응답 | `SearchResult[]` |
| 후처리 | 검색 결과 목록 표시, 클릭 시 해당 대화로 이동 |

---

### 6.2.7 대화 내보내기

```
Sidebar.tsx → 내보내기 메뉴 클릭
App.tsx → handleExport() → exportConversation()
```

| 항목 | 값 |
|------|-----|
| Method | GET |
| Path | `/api/conversations/{id}/export?format={json\|markdown}` |
| 응답 | Blob (파일 다운로드) |
| 후처리 | Content-Disposition에서 파일명 추출 → Blob URL 생성 → 다운로드 트리거 |

---

### 6.2.8 대화 가져오기

```
Sidebar.tsx → 가져오기 버튼 클릭 → 파일 선택
App.tsx → handleImport() → importConversation()
```

| 항목 | 값 |
|------|-----|
| Method | POST |
| Path | `/api/conversations/import` |
| 요청 | 파일을 클라이언트에서 JSON.parse → Body로 전송 |
| 응답 | `ConversationResponse` (201) |
| 후처리 | 목록에 추가, 가져온 대화 선택, 메시지/모델/프롬프트 로드 |

---

## 6.3 채팅 (App.tsx + ChatInput.tsx + ChatMessage.tsx)

> **React:** `App.tsx`, `ChatInput.tsx`, `ChatMessage.tsx`
> **Backend:** `routes/chat.py`

### 6.3.1 채팅 메시지 전송 (SSE 스트리밍)

```
ChatInput.tsx → handleSubmit() → onSend()
App.tsx → handleSend() → sendMessage() → streamChat()
```

| 항목 | 값 |
|------|-----|
| Method | POST |
| Path | `/api/conversations/{id}/chat` |
| Body | `{ message: "사용자 메시지" }` |
| 응답 | SSE 스트리밍 (text/event-stream) |

#### 프론트엔드 SSE 처리 흐름

```
1. fetch() 호출 → ReadableStream 획득
2. TextDecoder로 청크 디코딩
3. "data: " 접두어 파싱 → JSON.parse
4. thinking 이벤트 → thinkingContent 상태 업데이트
5. token 이벤트 → streamingContent 상태 업데이트 (실시간 렌더링)
6. done 이벤트 → 최종 Message 객체 생성, messages 배열에 추가
   → title이 있으면 대화 목록 제목 업데이트
   → references가 있으면 메시지에 참조 정보 저장
7. error 이벤트 → alert 표시
```

#### 응답 중지 (AbortController)

```
App.tsx → handleCancel()
  → abortRef.current.abort()  (fetch 중단)
  → 현재 streamingContent를 "*(응답이 중단되었습니다)*" 메시지와 함께 저장
  → streaming 상태 해제
```

---

## 6.4 파일 첨부 (ChatInput.tsx + App.tsx)

> **React:** `App.tsx`, `ChatInput.tsx`
> **Backend:** `routes/attachments.py`

### 6.4.1 파일 업로드

```
ChatInput.tsx → handleFileChange() → onFileUpload()
App.tsx → handleFileUpload() → uploadAttachment()
```

| 항목 | 값 |
|------|-----|
| Method | POST |
| Path | `/api/conversations/{conv_id}/attachments` |
| Body | FormData (file) |
| 응답 | 첨부파일 정보 JSON |
| 특이사항 | 대화가 없으면 자동 생성 후 업로드 |

---

### 6.4.2 첨부파일 목록 조회

```
App.tsx → loadAttachments() → fetchAttachments()
```

| 항목 | 값 |
|------|-----|
| Method | GET |
| Path | `/api/conversations/{conv_id}/attachments` |
| 호출 시점 | activeConvId 변경 시 (useEffect) |

---

### 6.4.3 첨부파일 삭제

```
ChatInput.tsx → attachment-remove 버튼 클릭
App.tsx → handleFileRemove() → deleteAttachment()
```

| 항목 | 값 |
|------|-----|
| Method | DELETE |
| Path | `/api/conversations/{conv_id}/attachments/{att_id}` |
| 응답 | 204 No Content |

---

## 6.5 모델 관리 (ModelSelector.tsx + App.tsx)

> **React:** `App.tsx`, `ModelSelector.tsx`
> **Backend:** `routes/models.py`

### 6.5.1 모델 목록 조회

```
App.tsx → loadModels() → fetchModels()
```

| 항목 | 값 |
|------|-----|
| Method | GET |
| Path | `/api/models` |
| 호출 시점 | 앱 초기 로딩 |
| 후처리 | 현재 선택 모델이 목록에 없으면 첫 번째 모델로 변경 |

---

### 6.5.2 모델 변경

```
ModelSelector.tsx → onChange
App.tsx → handleModelChange() → updateConversation({ model })
```

| 항목 | 값 |
|------|-----|
| Method | PATCH |
| Path | `/api/conversations/{id}` |
| Body | `{ model: "선택된모델명" }` |
| 호출 시점 | 모델 드롭다운 변경 시 (활성 대화가 있을 때만) |

---

## 6.6 지식 저장소 (KnowledgePanel.tsx)

> **React:** `KnowledgePanel.tsx`
> **Backend:** `routes/knowledge.py`

### 6.6.1 지식 문서 목록 조회

```
KnowledgePanel.tsx → loadDocs() → fetchKnowledgeDocs()
```

| 항목 | 값 |
|------|-----|
| Method | GET |
| Path | `/api/knowledge` |
| 호출 시점 | 패널 visible 변경 시 |

---

### 6.6.2 지식 문서 업로드

```
KnowledgePanel.tsx → handleUpload() → uploadKnowledgeDoc()
```

| 항목 | 값 |
|------|-----|
| Method | POST |
| Path | `/api/knowledge/upload` |
| Body | FormData (file) |
| 후처리 | 목록 앞에 추가, 상태 폴링 시작 |

---

### 6.6.3 문서 처리 상태 폴링

```
KnowledgePanel.tsx → useEffect (3초 간격 setInterval)
  → processing 상태 문서 대상
  → fetchKnowledgeDocStatus()
```

| 항목 | 값 |
|------|-----|
| Method | GET |
| Path | `/api/knowledge/{id}/status` |
| 폴링 간격 | 3000ms |
| 종료 조건 | 모든 문서가 processing이 아닐 때 |

---

### 6.6.4 지식 문서 삭제

```
KnowledgePanel.tsx → handleDelete() → deleteKnowledgeDoc()
```

| 항목 | 값 |
|------|-----|
| Method | DELETE |
| Path | `/api/knowledge/{id}` |
| 확인 | window.confirm 다이얼로그 |
| 응답 | 204 No Content |

---

## 6.7 시스템 프롬프트 (SystemPromptEditor.tsx + App.tsx)

> **React:** `App.tsx`, `SystemPromptEditor.tsx`
> **Backend:** `routes/conversations.py`

### 6.7.1 시스템 프롬프트 저장

```
SystemPromptEditor.tsx → handleSave() → onSave()
App.tsx → handleSystemPromptSave()
  → 활성 대화가 있으면: updateConversation({ system_prompt })
  → 활성 대화가 없으면: createConversation() (새 대화 생성)
```

| 항목 | 값 |
|------|-----|
| Method | PATCH (기존 대화) 또는 POST (새 대화) |
| Path | `/api/conversations/{id}` 또는 `/api/conversations` |
| Body | `{ system_prompt: "프롬프트 내용" }` |
| 특이사항 | 빈 문자열은 서버에서 null로 변환하여 저장 |

### 프롬프트 로딩

```
App.tsx → handleSelectConversation()
  → fetchConversation(id)
  → data.system_prompt → setCurrentSystemPrompt()
```

대화 전환 시 서버에서 system_prompt를 로드하여 UI 상태를 동기화합니다.
