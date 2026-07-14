import { PromptDebug, Reference, SearchResult } from './types';

const API_BASE = '/api';

export async function fetchConversations() {
  const res = await fetch(`${API_BASE}/conversations`);
  return res.json();
}

export async function createConversation(title: string, model: string, system_prompt?: string | null) {
  const res = await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, model, system_prompt: system_prompt || null }),
  });
  return res.json();
}

export async function fetchConversation(id: number) {
  const res = await fetch(`${API_BASE}/conversations/${id}`);
  return res.json();
}

export async function updateConversation(id: number, data: { title?: string; model?: string; system_prompt?: string | null }) {
  const res = await fetch(`${API_BASE}/conversations/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return res.json();
}

export async function deleteConversation(id: number) {
  await fetch(`${API_BASE}/conversations/${id}`, { method: 'DELETE' });
}

export async function fetchModels() {
  const res = await fetch(`${API_BASE}/models`);
  return res.json();
}

export async function uploadAttachment(conversationId: number, file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/conversations/${conversationId}/attachments`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '파일 업로드 실패');
  }
  return res.json();
}

export async function fetchAttachments(conversationId: number) {
  const res = await fetch(`${API_BASE}/conversations/${conversationId}/attachments`);
  return res.json();
}

export async function deleteAttachment(conversationId: number, attachmentId: number) {
  await fetch(`${API_BASE}/conversations/${conversationId}/attachments/${attachmentId}`, {
    method: 'DELETE',
  });
}

// Knowledge Base
export async function fetchKnowledgeDocs() {
  const res = await fetch(`${API_BASE}/knowledge`);
  return res.json();
}

export async function uploadKnowledgeDoc(file: File) {
  const formData = new FormData();
  formData.append('file', file);
  const res = await fetch(`${API_BASE}/knowledge/upload`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '파일 업로드 실패');
  }
  return res.json();
}

export async function deleteKnowledgeDoc(id: number) {
  await fetch(`${API_BASE}/knowledge/${id}`, { method: 'DELETE' });
}

export async function fetchKnowledgeDocStatus(id: number) {
  const res = await fetch(`${API_BASE}/knowledge/${id}/status`);
  return res.json();
}

// Search
export async function searchConversations(query: string): Promise<SearchResult[]> {
  const res = await fetch(`${API_BASE}/conversations/search?q=${encodeURIComponent(query)}`);
  if (!res.ok) return [];
  return res.json();
}

// Export
export async function exportConversation(id: number, format: 'json' | 'markdown' = 'json') {
  const res = await fetch(`${API_BASE}/conversations/${id}/export?format=${format}`);
  if (!res.ok) throw new Error('내보내기 실패');
  const blob = await res.blob();
  const ext = format === 'json' ? 'json' : 'md';
  const contentDisposition = res.headers.get('Content-Disposition');
  let filename = `conversation.${ext}`;
  if (contentDisposition) {
    const match = contentDisposition.match(/filename\*?=(?:UTF-8'')?(.+)/);
    if (match) filename = decodeURIComponent(match[1]);
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

// Import
export async function importConversation(file: File) {
  const text = await file.text();
  const data = JSON.parse(text);
  const res = await fetch(`${API_BASE}/conversations/import`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || '가져오기 실패');
  }
  return res.json();
}

// ── RCA ──────────────────────────────────────────────────────────────────────

export interface RcaResult {
  parse_stats: { total_lines: number; raw_rows: number; parsed: number; skipped: number };
  summary: {
    total_records: number;
    attempt_count: number;
    success_count: number;
    failure_count: number;
    failure_rate: number;
  };
  primary_root_cause: {
    root_cause: string;
    count: number;
    confidence: number;
    category: string;
    subcategory: string;
    severity: string;
    description: string;
  };
  top_root_causes: Array<{ root_cause: string; count: number; category: string; severity: string; confidence: number }>;
  failure_chains: Array<{
    procedure: string;
    call_type_code: number;
    call_type: string;
    failure_point: string;
    failure_interface: string;
    failure_message: string;
    failure_cause: number;
    failure_cause_name: string;
    failure_semantic: string;
    chain: string[];
    confidence: number;
    root_cause: string;
    root_cause_category: string;
    root_cause_severity: string;
  }>;
  impacted_nodes: { mme_count: number; enb_count: number; apn_count: number; affected_users: number };
  time_distribution: Record<string, number>;
  burst_detected: boolean;
  burst_window: string | null;
  interface_distribution: Record<string, number>;
  repeated_failure_count: number;
  recommended_actions: string[];
  conversation_id: number;
  assistant_message: string;
}

export async function uploadXdrFile(file: File, model: string, loopMode = false): Promise<RcaResult> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('model', model);
  formData.append('loop_mode', String(loopMode));
  const res = await fetch(`${API_BASE}/rca/analyze`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '알 수 없는 오류' }));
    throw new Error(err.detail || 'RCA 분석 실패');
  }
  return res.json();
}

export async function analyzeSampleXdr(model: string, loopMode = false): Promise<RcaResult> {
  const formData = new FormData();
  formData.append('model', model);
  formData.append('loop_mode', String(loopMode));
  const res = await fetch(`${API_BASE}/v1/analysis/sample`, {
    method: 'POST',
    body: formData,
  });
  const data = await res.json().catch(() => ({ detail: '알 수 없는 오류' }));
  if (!res.ok || data.success === false) {
    throw new Error(data.message || data.detail || '샘플 RCA 분석 실패');
  }
  return data;
}

export function streamRcaReport(
  convId: number,
  onToken: (token: string) => void,
  onDone: () => void,
  onError: (err: string) => void,
  onPromptDebug?: (prompt: PromptDebug) => void,
): AbortController {
  const controller = new AbortController();

  fetch(`${API_BASE}/rca/conversations/${convId}/report`, {
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'LLM 보고서 생성 실패' }));
      onError(err.detail || 'LLM 보고서 생성 실패');
      return;
    }
    const reader = response.body?.getReader();
    if (!reader) {
      onError('응답 스트림을 열 수 없습니다');
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.token) onToken(data.token);
            if (data.done) onDone();
            if (data.error) onError(data.error);
            if (data.prompt_debug) onPromptDebug?.(data.prompt_debug);
          } catch {}
        }
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') onError(err.message);
  });

  return controller;
}

// ── RCA Lab ──────────────────────────────────────────────────────────────────

export interface RcaLabInput {
  input_id: number;
  input_name: string;
  description: string;
  record_count?: number | null;
  status: string;
  hash: string;
  priority: number;
  update_dt: string;
  text_length: number;
  text?: string;
}

export interface RcaLabPrompt {
  prompt_id: number;
  prompt_name: string;
  version: string;
  parent_prompt?: string | null;
  status: string;
  hash: string;
  priority: number;
  update_dt: string;
  execution_count?: number;
  average_score?: number | null;
  best_score?: number | null;
  worst_score?: number | null;
  text_preview?: string;
  text?: string;
}

export interface RcaLabExperiment {
  experiment_id: number;
  run_id: number;
  step_id: number;
  run_mode: string;
  input_id: number;
  input_name: string;
  prompt_id: number;
  prompt_name: string;
  result_id?: number | null;
  model: string;
  run_count: number;
  status: string;
  score?: number | null;
  update_dt: string;
}

export interface RcaLabResult {
  step_id?: number;
  input_id?: number;
  input_name?: string;
  prompt_id?: number;
  prompt_name?: string;
  result_id: number;
  score?: number | null;
  accuracy_score?: number | null;
  reasoning_score?: number | null;
  evidence_score?: number | null;
  actionability_score?: number | null;
  accuracy_comment?: string | null;
  reasoning_comment?: string | null;
  evidence_comment?: string | null;
  actionability_comment?: string | null;
  evaluation_comment?: string | null;
  result_preview?: string;
  text?: string;
  update_dt: string;
}

async function jsonOrThrow(res: Response, fallback: string) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data.detail || data.message || fallback);
  }
  return data;
}

export async function fetchRcaLabInputs(): Promise<RcaLabInput[]> {
  const res = await fetch(`${API_BASE}/rca/lab/inputs`);
  return jsonOrThrow(res, 'RCA Lab INPUT 조회 실패');
}

export async function fetchRcaLabInput(id: number): Promise<RcaLabInput> {
  const res = await fetch(`${API_BASE}/rca/lab/inputs/${id}`);
  return jsonOrThrow(res, 'RCA Lab INPUT 상세 조회 실패');
}

export async function importRcaLabSample(chunkSize = 10000) {
  const res = await fetch(`${API_BASE}/rca/lab/inputs/import-sample`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chunk_size: chunkSize }),
  });
  return jsonOrThrow(res, '샘플 INPUT 생성 실패');
}

export async function importRcaLabFile(file: File, chunkSize = 10000, inputName?: string) {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('chunk_size', String(chunkSize));
  if (inputName) formData.append('input_name', inputName);
  const res = await fetch(`${API_BASE}/rca/input/import`, {
    method: 'POST',
    body: formData,
  });
  return jsonOrThrow(res, 'RCA INPUT 파일 생성 실패');
}

export async function deleteRcaLabInput(id: number) {
  const res = await fetch(`${API_BASE}/rca/lab/inputs/${id}`, { method: 'DELETE' });
  return jsonOrThrow(res, 'RCA Lab INPUT 삭제 실패');
}

export async function fetchRcaLabPrompts(): Promise<RcaLabPrompt[]> {
  const res = await fetch(`${API_BASE}/rca/lab/prompts`);
  return jsonOrThrow(res, 'RCA Lab Prompt 조회 실패');
}

export async function fetchRcaLabPrompt(id: number): Promise<RcaLabPrompt> {
  const res = await fetch(`${API_BASE}/rca/lab/prompts/${id}`);
  return jsonOrThrow(res, 'RCA Lab Prompt 상세 조회 실패');
}

export async function createRcaLabPrompt(text: string) {
  const res = await fetch(`${API_BASE}/rca/lab/prompts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  return jsonOrThrow(res, 'RCA Lab Prompt 등록 실패');
}

export async function updateRcaLabPrompt(id: number, text: string) {
  const res = await fetch(`${API_BASE}/rca/lab/prompts/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  });
  return jsonOrThrow(res, 'RCA Lab Prompt 수정 실패');
}

export async function deleteRcaLabPrompt(id: number) {
  const res = await fetch(`${API_BASE}/rca/lab/prompts/${id}`, { method: 'DELETE' });
  return jsonOrThrow(res, 'RCA Lab Prompt 삭제 실패');
}

export async function runRcaLabExperiment(inputId: number, promptId: number, model: string, count: number) {
  const res = await fetch(`${API_BASE}/rca/lab/experiments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ input_id: inputId, prompt_id: promptId, model, count }),
  });
  return jsonOrThrow(res, 'RCA Lab Experiment 실행 실패');
}

export async function fetchRcaLabExperiments(): Promise<RcaLabExperiment[]> {
  const res = await fetch(`${API_BASE}/rca/lab/experiments`);
  return jsonOrThrow(res, 'RCA Lab Experiment 이력 조회 실패');
}

export async function fetchRcaLabResults(inputId?: number): Promise<RcaLabResult[]> {
  const query = inputId ? `?input_id=${inputId}` : '';
  const res = await fetch(`${API_BASE}/rca/lab/results/compare${query}`);
  return jsonOrThrow(res, 'RCA Lab Result 비교 조회 실패');
}

export async function fetchRcaLabResult(id: number): Promise<RcaLabResult> {
  const res = await fetch(`${API_BASE}/rca/lab/results/${id}`);
  return jsonOrThrow(res, 'RCA Lab Result 상세 조회 실패');
}

export async function createRcaLabHumanEvaluation(resultId: number, rating: string, comment: string) {
  const res = await fetch(`${API_BASE}/rca/lab/results/${resultId}/human-evaluation`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ rating, comment }),
  });
  return jsonOrThrow(res, 'Human 평가 저장 실패');
}

export function streamRcaReasoning(
  convId: number,
  hallucinationStep2: boolean,
  hallucinationStep3: boolean,
  hallucinationProvider: 'claude' | 'gemini',
  onToken: (token: string) => void,
  onDone: () => void,
  onError: (err: string) => void,
  onPromptDebug?: (prompt: PromptDebug) => void,
  onStepDone?: () => void,
): AbortController {
  const controller = new AbortController();
  const params = new URLSearchParams();
  if (hallucinationStep2) params.append('hallucination_step2', 'true');
  if (hallucinationStep3) params.append('hallucination_step3', 'true');
  if (hallucinationStep2 || hallucinationStep3) params.append('hallucination_provider', hallucinationProvider);
  const query = params.toString();
  const url = `${API_BASE}/rca/conversations/${convId}/reasoning${query ? `?${query}` : ''}`;

  fetch(url, {
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: 'RCA reasoning 실패' }));
      onError(err.detail || 'RCA reasoning 실패');
      return;
    }
    const reader = response.body?.getReader();
    if (!reader) {
      onError('응답 스트림을 열 수 없습니다');
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.token) onToken(data.token);
            if (data.warning) onToken(`\n\n*${data.warning}*\n\n`);
            if (data.done) onDone();
            if (data.error) onError(data.error);
            if (data.prompt_debug) onPromptDebug?.(data.prompt_debug);
            if (data.step_done) onStepDone?.();
          } catch {}
        }
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') onError(err.message);
  });

  return controller;
}

// ── Chat ─────────────────────────────────────────────────────────────────────

export function streamChat(
  conversationId: number,
  message: string,
  agentMode: boolean,
  onToken: (token: string) => void,
  onDone: (title?: string, references?: Reference[]) => void,
  onError: (err: string) => void,
  onThinking?: (token: string) => void,
  onPromptDebug?: (prompt: PromptDebug) => void,
) {
  const controller = new AbortController();

  fetch(`${API_BASE}/conversations/${conversationId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, agent_mode: agentMode }),
    signal: controller.signal,
  }).then(async (response) => {
    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: '채팅 요청 실패' }));
      onError(err.detail || '채팅 요청 실패');
      return;
    }
    const reader = response.body?.getReader();
    if (!reader) {
      onError('응답 스트림을 열 수 없습니다');
      return;
    }

    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            if (data.thinking && onThinking) onThinking(data.thinking);
            if (data.token) onToken(data.token);
            if (data.done) onDone(data.title || undefined, data.references || undefined);
            if (data.error) onError(data.error);
            if (data.prompt_debug) onPromptDebug?.(data.prompt_debug);
          } catch {}
        }
      }
    }
  }).catch((err) => {
    if (err.name !== 'AbortError') onError(err.message);
  });

  return controller;
}
