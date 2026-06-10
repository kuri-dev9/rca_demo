import React, { useState, useRef, useEffect } from 'react';
import { Attachment } from '../types';

interface Props {
  onSend: (message: string, agentMode: boolean) => void;
  onCancel: () => void;
  onFileUpload: (file: File) => Promise<void>;
  onFileRemove: (id: number) => void;
  attachments: Attachment[];
  disabled: boolean;
  streaming: boolean;
}

export default function ChatInput({ onSend, onCancel, onFileUpload, onFileRemove, attachments, disabled, streaming }: Props) {
  const [input, setInput] = useState('');
  const [uploading, setUploading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [input]);

  const handleSubmit = () => {
    if (!input.trim() || disabled) return;
    onSend(input.trim(), false);
    setInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await onFileUpload(file);
    } catch (err: any) {
      alert(err.message || '파일 업로드 실패');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  return (
    <div className="chat-input-wrapper">
      {attachments.length > 0 && (
        <div className="attachments-bar">
          {attachments.map((att) => (
            <div key={att.id} className="attachment-chip">
              <span className="attachment-icon">📎</span>
              <span className="attachment-name">{att.filename}</span>
              <span className="attachment-size">({formatSize(att.file_size)})</span>
              <button
                className="attachment-remove"
                onClick={() => onFileRemove(att.id)}
                disabled={disabled}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <div className="chat-input-container">
        <button
          className="attach-btn"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || uploading}
          title="파일 첨부"
        >
          {uploading ? '⏳' : '📎'}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="file-input-hidden"
          onChange={handleFileChange}
          accept=".txt,.md,.py,.js,.ts,.jsx,.tsx,.json,.csv,.html,.css,.xml,.yaml,.yml,.pdf,.docx,.xlsx,.xls,.hwp,.hwpx,.log,.sh,.sql,.java,.c,.cpp,.h,.go,.rs"
        />
        <textarea
          ref={textareaRef}
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="메시지를 입력하세요... (Shift+Enter로 줄바꿈)"
          disabled={disabled}
          rows={1}
        />
        {streaming ? (
          <button className="cancel-btn" onClick={onCancel}>
            중지
          </button>
        ) : (
          <button className="send-btn" onClick={handleSubmit} disabled={disabled || !input.trim()}>
            전송
          </button>
        )}
      </div>
    </div>
  );
}
