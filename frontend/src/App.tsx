import React, { useState, useEffect, useRef, useCallback } from 'react';
import Sidebar from './components/Sidebar';
import ChatMessage from './components/ChatMessage';
import ChatInput from './components/ChatInput';
import ModelSelector from './components/ModelSelector';
import ThemeToggle from './components/ThemeToggle';
import KnowledgePanel from './components/KnowledgePanel';
import SystemPromptEditor from './components/SystemPromptEditor';
import { Conversation, Message, OllamaModel, Attachment, PromptDebug } from './types';
import {
  fetchConversations,
  createConversation,
  fetchConversation,
  deleteConversation,
  updateConversation,
  fetchModels,
  streamChat,
  uploadAttachment,
  fetchAttachments,
  deleteAttachment,
  exportConversation,
  importConversation,
  uploadXdrFile,
  analyzeSampleXdr,
  streamRcaReport,
  streamRcaReasoning,
} from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConvId, setActiveConvId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [models, setModels] = useState<OllamaModel[]>([]);
  const [selectedModel, setSelectedModel] = useState('gemma4:26b');
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState('');
  const [thinkingContent, setThinkingContent] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [knowledgeOpen, setKnowledgeOpen] = useState(false);
  const [systemPromptOpen, setSystemPromptOpen] = useState(false);
  const [rcaLoading, setRcaLoading] = useState(false);
  const [streamingDebugPrompts, setStreamingDebugPrompts] = useState<PromptDebug[]>([]);
  const rcaFileInputRef = useRef<HTMLInputElement>(null);
  const [currentSystemPrompt, setCurrentSystemPrompt] = useState('');
  const [dark, setDark] = useState(true);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const activeConvIdRef = useRef<number | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const streamingDebugPromptsRef = useRef<PromptDebug[]>([]);

  useEffect(() => {
    activeConvIdRef.current = activeConvId;
  }, [activeConvId]);

  useEffect(() => {
    streamingDebugPromptsRef.current = streamingDebugPrompts;
  }, [streamingDebugPrompts]);

  const resetStreamingDebugPrompts = () => {
    streamingDebugPromptsRef.current = [];
    setStreamingDebugPrompts([]);
  };

  const appendStreamingDebugPrompt = (prompt: PromptDebug) => {
    const next = [...streamingDebugPromptsRef.current, prompt];
    streamingDebugPromptsRef.current = next;
    setStreamingDebugPrompts(next);
  };

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
  }, [dark]);

  useEffect(() => {
    loadConversations();
    loadModels();
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, streamingContent]);

  useEffect(() => {
    if (activeConvId) {
      loadAttachments(activeConvId);
    } else {
      setAttachments([]);
    }
  }, [activeConvId]);

  const loadConversations = async () => {
    const data = await fetchConversations();
    setConversations(data);
  };

  const loadModels = async () => {
    try {
      const data = await fetchModels();
      setModels(data);
      if (data.length > 0 && !data.find((m: OllamaModel) => m.name === selectedModel)) {
        setSelectedModel(data[0].name);
      }
    } catch {}
  };

  const loadAttachments = async (convId: number) => {
    try {
      const data = await fetchAttachments(convId);
      setAttachments(data);
    } catch {
      setAttachments([]);
    }
  };

  const handleSelectConversation = useCallback(async (id: number) => {
    if (streaming) return;
    setActiveConvId(id);
    setMessages([]);
    setStreamingContent('');
    setThinkingContent('');
    resetStreamingDebugPrompts();
    const data = await fetchConversation(id);
    if (activeConvIdRef.current === id) {
      setMessages(data.messages || []);
      setSelectedModel(data.model);
      setCurrentSystemPrompt(data.system_prompt || '');
    }
  }, [streaming]);

  const handleCreateConversation = async () => {
    if (streaming) return;
    const conv = await createConversation('새 대화', selectedModel);
    setConversations((prev) => [conv, ...prev]);
    setActiveConvId(conv.id);
    setMessages([]);
    setStreamingContent('');
    setThinkingContent('');
    setAttachments([]);
    setCurrentSystemPrompt('');
    resetStreamingDebugPrompts();
  };

  const handleDeleteConversation = async (id: number) => {
    if (streaming) return;
    await deleteConversation(id);
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (activeConvId === id) {
      setActiveConvId(null);
      setMessages([]);
      setAttachments([]);
      setCurrentSystemPrompt('');
      resetStreamingDebugPrompts();
    }
  };

  const handleRenameConversation = async (id: number, title: string) => {
    await updateConversation(id, { title });
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title } : c))
    );
  };

  const handleModelChange = async (model: string) => {
    setSelectedModel(model);
    if (activeConvId) {
      await updateConversation(activeConvId, { model });
    }
  };

  const handleSystemPromptSave = async (prompt: string) => {
    setCurrentSystemPrompt(prompt);
    if (activeConvId) {
      await updateConversation(activeConvId, { system_prompt: prompt || '' });
    } else {
      const conv = await createConversation('새 대화', selectedModel, prompt || null);
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      setMessages([]);
      setAttachments([]);
    }
  };

  const handleExport = async (id: number, format: 'json' | 'markdown') => {
    try {
      await exportConversation(id, format);
    } catch {
      alert('내보내기에 실패했습니다.');
    }
  };

  const handleRcaClick = () => {
    rcaFileInputRef.current?.click();
  };

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const startRcaReport = (convId: number) => {
    setStreaming(true);
    setStreamingContent('');
    setThinkingContent('');
    resetStreamingDebugPrompts();

    const controller = streamRcaReport(
      convId,
      (token) => {
        if (activeConvIdRef.current !== convId) return;
        setStreamingContent((prev) => prev + token);
      },
      () => {
        const promptSnapshot = [...streamingDebugPromptsRef.current];
        setStreamingContent((prev) => {
          if (prev || promptSnapshot.length > 0) {
            const assistantMsg: Message = {
              id: Date.now() + 1,
              conversation_id: convId,
              role: 'assistant',
              content: prev || '*(응답 없음)*',
              created_at: new Date().toISOString(),
              debug_prompts: promptSnapshot,
            };
            setMessages((msgs) => [...msgs, assistantMsg]);
          }
          return '';
        });
        setStreaming(false);
        setThinkingContent('');
        resetStreamingDebugPrompts();
        abortRef.current = null;
      },
      (err) => {
        const promptSnapshot = [...streamingDebugPromptsRef.current];
        if (promptSnapshot.length > 0) {
          const assistantMsg: Message = {
            id: Date.now() + 1,
            conversation_id: convId,
            role: 'assistant',
            content: `*(LLM 오류: ${err})*`,
            created_at: new Date().toISOString(),
            debug_prompts: promptSnapshot,
          };
          setMessages((msgs) => [...msgs, assistantMsg]);
        }
        setStreamingContent('');
        setThinkingContent('');
        setStreaming(false);
        resetStreamingDebugPrompts();
        abortRef.current = null;
        alert(`LLM 오류: ${err}`);
      },
      (prompt) => {
        appendStreamingDebugPrompt(prompt);
      }
    );
    abortRef.current = controller;
  };

  const startRcaReasoning = (convId: number) => {
    setStreaming(true);
    setStreamingContent('');
    setThinkingContent('');
    resetStreamingDebugPrompts();

    const controller = streamRcaReasoning(
      convId,
      (token) => {
        if (activeConvIdRef.current !== convId) return;
        setStreamingContent((prev) => prev + token);
      },
      () => {
        const promptSnapshot = [...streamingDebugPromptsRef.current];
        setStreamingContent((prev) => {
          if (prev || promptSnapshot.length > 0) {
            const assistantMsg: Message = {
              id: Date.now() + 1,
              conversation_id: convId,
              role: 'assistant',
              content: prev || '*(응답 없음)*',
              created_at: new Date().toISOString(),
              debug_prompts: promptSnapshot,
            };
            setMessages((msgs) => [...msgs, assistantMsg]);
          }
          return '';
        });
        setStreaming(false);
        setThinkingContent('');
        resetStreamingDebugPrompts();
        abortRef.current = null;
      },
      (err) => {
        const promptSnapshot = [...streamingDebugPromptsRef.current];
        if (promptSnapshot.length > 0) {
          const assistantMsg: Message = {
            id: Date.now() + 1,
            conversation_id: convId,
            role: 'assistant',
            content: `*(RCA reasoning 오류: ${err})*`,
            created_at: new Date().toISOString(),
            debug_prompts: promptSnapshot,
          };
          setMessages((msgs) => [...msgs, assistantMsg]);
        }
        setStreamingContent('');
        setThinkingContent('');
        setStreaming(false);
        resetStreamingDebugPrompts();
        abortRef.current = null;
        alert(`RCA reasoning 오류: ${err}`);
      },
      (prompt) => {
        appendStreamingDebugPrompt(prompt);
      }
    );
    abortRef.current = controller;
  };

  const showRcaResult = async (result: any, userContent: string) => {
    const convId = result.conversation_id;
    setActiveConvId(convId);
    activeConvIdRef.current = convId;
    setCurrentSystemPrompt('');
    setAttachments([]);
    setStreamingContent('');
    setThinkingContent('');
    resetStreamingDebugPrompts();
    setMessages([
      {
        id: Date.now() - 1,
        conversation_id: convId,
        role: 'user',
        content: userContent,
        created_at: new Date().toISOString(),
      },
      {
        id: Date.now(),
        conversation_id: convId,
        role: 'assistant',
        content: result.assistant_message,
        created_at: new Date().toISOString(),
      },
    ]);
    await loadConversations();
    startRcaReasoning(convId);
  };

  const handleRcaFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = '';
    setRcaLoading(true);
    try {
      const result = await uploadXdrFile(file, selectedModel);
      await showRcaResult(result, `xDR 파일 RCA 분석: ${file.name}`);
      setRcaLoading(false);
    } catch (err: any) {
      alert(`RCA 분석 실패: ${err.message}`);
      setRcaLoading(false);
    }
  };

  const handleSampleRca = async () => {
    if (rcaLoading || streaming) return;
    setRcaLoading(true);
    try {
      const result = await analyzeSampleXdr(selectedModel);
      await showRcaResult(result, 'xDR 샘플 RCA 분석');
      setRcaLoading(false);
    } catch (err: any) {
      alert(`RCA 분석 실패: ${err.message}`);
      setRcaLoading(false);
    }
  };

  const handleImport = async (file: File) => {
    try {
      const conv = await importConversation(file);
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      const data = await fetchConversation(conv.id);
      setMessages(data.messages || []);
      setSelectedModel(data.model);
      setCurrentSystemPrompt(data.system_prompt || '');
    } catch (err: any) {
      alert(`가져오기 실패: ${err.message}`);
    }
  };

  const handleFileUpload = async (file: File) => {
    let convId: number;
    if (!activeConvId) {
      const conv = await createConversation('새 대화', selectedModel, currentSystemPrompt || null);
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      setMessages([]);
      convId = conv.id;
    } else {
      convId = activeConvId;
    }
    const att = await uploadAttachment(convId, file);
    setAttachments((prev) => [...prev, att]);
  };

  const handleFileRemove = async (attachmentId: number) => {
    if (!activeConvId) return;
    await deleteAttachment(activeConvId, attachmentId);
    setAttachments((prev) => prev.filter((a) => a.id !== attachmentId));
  };

  const handleCancel = () => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    const promptSnapshot = [...streamingDebugPromptsRef.current];
    setStreamingContent((prev) => {
      if (prev || promptSnapshot.length > 0) {
        const assistantMsg: Message = {
          id: Date.now() + 1,
          conversation_id: activeConvId || 0,
          role: 'assistant',
          content: (prev || '') + '\n\n*(응답이 중단되었습니다)*',
          created_at: new Date().toISOString(),
          debug_prompts: promptSnapshot,
        };
        setMessages((msgs) => [...msgs, assistantMsg]);
      }
      return '';
    });
    setStreaming(false);
    setThinkingContent('');
    resetStreamingDebugPrompts();
  };

  const handleSend = async (message: string, agentMode = false) => {
    if (!activeConvId) {
      const conv = await createConversation('새 대화', selectedModel, currentSystemPrompt || null);
      setConversations((prev) => [conv, ...prev]);
      setActiveConvId(conv.id);
      setMessages([]);
      sendMessage(conv.id, message, agentMode);
    } else {
      sendMessage(activeConvId, message, agentMode);
    }
  };

  const sendMessage = (convId: number, message: string, agentMode = false) => {
    const userMsg: Message = {
      id: Date.now(),
      conversation_id: convId,
      role: 'user',
      content: message,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => {
      const filtered = prev.filter((m) => m.conversation_id === convId);
      return [...filtered, userMsg];
    });
    setStreaming(true);
    setStreamingContent('');
    setThinkingContent('');
    resetStreamingDebugPrompts();

    const controller = streamChat(
      convId,
      message,
      agentMode,
      (token) => {
        if (activeConvIdRef.current !== convId) return;
        setStreamingContent((prev) => prev + token);
      },
      (title, references) => {
        const promptSnapshot = [...streamingDebugPromptsRef.current];
        setStreamingContent((prev) => {
          if (prev || promptSnapshot.length > 0) {
            const assistantMsg: Message = {
              id: Date.now() + 1,
              conversation_id: convId,
              role: 'assistant',
              content: prev || '*(응답 없음)*',
              created_at: new Date().toISOString(),
              references,
              debug_prompts: promptSnapshot,
            };
            setMessages((msgs) => [...msgs, assistantMsg]);
          }
          return '';
        });
        setStreaming(false);
        setThinkingContent('');
        resetStreamingDebugPrompts();
        abortRef.current = null;
        if (title) {
          setConversations((prev) =>
            prev.map((c) => (c.id === convId ? { ...c, title } : c))
          );
        }
      },
      (err) => {
        const promptSnapshot = [...streamingDebugPromptsRef.current];
        if (promptSnapshot.length > 0) {
          const assistantMsg: Message = {
            id: Date.now() + 1,
            conversation_id: convId,
            role: 'assistant',
            content: `*(오류: ${err})*`,
            created_at: new Date().toISOString(),
            debug_prompts: promptSnapshot,
          };
          setMessages((msgs) => [...msgs, assistantMsg]);
        }
        setStreamingContent('');
        setThinkingContent('');
        setStreaming(false);
        resetStreamingDebugPrompts();
        abortRef.current = null;
        if (err !== 'AbortError') {
          alert(`오류: ${err}`);
        }
      },
      (thinking) => {
        if (activeConvIdRef.current !== convId) return;
        setThinkingContent((prev) => prev + thinking);
      },
      (prompt) => {
        if (activeConvIdRef.current !== convId) return;
        appendStreamingDebugPrompt(prompt);
      }
    );
    abortRef.current = controller;
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        activeId={activeConvId}
        onSelect={handleSelectConversation}
        onCreate={handleCreateConversation}
        onDelete={handleDeleteConversation}
        onRename={handleRenameConversation}
        onExport={handleExport}
        onImport={handleImport}
      />
      <main className="main">
        <header className="header">
          <ModelSelector models={models} selectedModel={selectedModel} onChange={handleModelChange} />
          <div className="header-actions">
            <button
              className={`system-prompt-btn ${currentSystemPrompt ? 'has-prompt' : ''}`}
              onClick={() => setSystemPromptOpen(true)}
              title="시스템 프롬프트"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
              {currentSystemPrompt ? '프롬프트 설정됨' : '시스템 프롬프트'}
            </button>
            <button
              className="knowledge-btn"
              onClick={handleRcaClick}
              disabled={rcaLoading || streaming}
              title="xDR RCA 분석"
              style={{ opacity: rcaLoading || streaming ? 0.6 : 1 }}
            >
              {rcaLoading ? '분석 중...' : 'RCA 분석'}
            </button>
            <button
              className="knowledge-btn"
              onClick={handleSampleRca}
              disabled={rcaLoading || streaming}
              title="서버 내부 sample.dat RCA 분석"
              style={{ opacity: rcaLoading || streaming ? 0.6 : 1 }}
            >
              샘플 분석
            </button>
            <input
              ref={rcaFileInputRef}
              type="file"
              accept=".dat"
              style={{ display: 'none' }}
              onChange={handleRcaFileChange}
            />
            <button className="knowledge-btn" onClick={() => setKnowledgeOpen(true)} title="지식 저장소">
              <img src="/document_icon.svg" alt="" className="btn-icon" /> 지식 저장소
            </button>
            <ThemeToggle dark={dark} onToggle={() => setDark(!dark)} />
          </div>
        </header>
        <div className="messages">
          {messages.length === 0 && !streaming && (
            <div className="empty-state">
              <h2>대화를 시작하세요</h2>
              <p>메시지를 입력하면 AI가 답변합니다.</p>
            </div>
          )}
          {messages.map((msg) => (
            <ChatMessage
              key={msg.id}
              role={msg.role}
              content={msg.content}
              references={msg.references}
              debugPrompts={msg.debug_prompts}
            />
          ))}
          {streaming && !streamingContent && thinkingContent && streamingDebugPrompts.length === 0 && (
            <div className="message assistant">
              <div className="message-avatar">
                <img src="/ai_icon.svg" alt="AI" className="avatar-icon" />
              </div>
              <div className="message-content thinking-indicator">
                <span className="thinking-label">생각 중...</span>
              </div>
            </div>
          )}
          {streaming && !streamingContent && streamingDebugPrompts.length > 0 && (
            <ChatMessage
              role="assistant"
              content={thinkingContent ? "*(생각 중...)*" : "*(응답 대기 중...)*"}
              debugPrompts={streamingDebugPrompts}
            />
          )}
          {streaming && streamingContent && (
            <ChatMessage role="assistant" content={streamingContent} debugPrompts={streamingDebugPrompts} />
          )}
          <div ref={messagesEndRef} />
        </div>
        <ChatInput
          onSend={handleSend}
          onCancel={handleCancel}
          onFileUpload={handleFileUpload}
          onFileRemove={handleFileRemove}
          attachments={attachments}
          disabled={streaming}
          streaming={streaming}
        />
      </main>
      <KnowledgePanel visible={knowledgeOpen} onClose={() => setKnowledgeOpen(false)} />
      <SystemPromptEditor
        visible={systemPromptOpen}
        systemPrompt={currentSystemPrompt}
        onSave={handleSystemPromptSave}
        onClose={() => setSystemPromptOpen(false)}
      />
    </div>
  );
}

export default App;
