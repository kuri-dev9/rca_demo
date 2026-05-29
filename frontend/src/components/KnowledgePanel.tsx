import React, { useState, useRef, useEffect } from 'react';
import { KnowledgeDoc } from '../types';
import { fetchKnowledgeDocs, uploadKnowledgeDoc, deleteKnowledgeDoc, fetchKnowledgeDocStatus } from '../api';

interface Props {
  visible: boolean;
  onClose: () => void;
}

export default function KnowledgePanel({ visible, onClose }: Props) {
  const [docs, setDocs] = useState<KnowledgeDoc[]>([]);
  const [uploading, setUploading] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (visible) loadDocs();
  }, [visible]);

  useEffect(() => {
    const processing = docs.filter((d) => d.status === 'processing');
    if (processing.length === 0) return;

    const interval = setInterval(async () => {
      let updated = false;
      const newDocs = [...docs];
      for (const doc of processing) {
        try {
          const status = await fetchKnowledgeDocStatus(doc.id);
          const idx = newDocs.findIndex((d) => d.id === doc.id);
          if (idx >= 0 && status.status !== 'processing') {
            newDocs[idx] = { ...newDocs[idx], ...status };
            updated = true;
          }
        } catch {}
      }
      if (updated) setDocs(newDocs);
    }, 3000);

    return () => clearInterval(interval);
  }, [docs]);

  const loadDocs = async () => {
    const data = await fetchKnowledgeDocs();
    setDocs(data);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const doc = await uploadKnowledgeDoc(file);
      setDocs((prev) => [doc, ...prev]);
    } catch (err: any) {
      alert(err.message || '업로드 실패');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleDelete = async (id: number) => {
    if (!window.confirm('이 문서를 지식 저장소에서 삭제하시겠습니까?')) return;
    await deleteKnowledgeDoc(id);
    setDocs((prev) => prev.filter((d) => d.id !== id));
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes}B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
  };

  const statusLabel = (doc: KnowledgeDoc) => {
    switch (doc.status) {
      case 'processing': return '처리 중...';
      case 'ready': return `${doc.chunk_count}개 청크`;
      case 'error': return `오류: ${doc.error_message || '알 수 없음'}`;
    }
  };

  if (!visible) return null;

  return (
    <div className="knowledge-overlay" onClick={onClose}>
      <div className="knowledge-panel" onClick={(e) => e.stopPropagation()}>
        <div className="knowledge-header">
          <h3>지식 저장소</h3>
          <button className="knowledge-close" onClick={onClose}>×</button>
        </div>
        <p className="knowledge-desc">
          문서를 업로드하면 모든 대화에서 자동으로 참조됩니다.
        </p>
        <div className="knowledge-upload">
          <button
            className="knowledge-upload-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
          >
            {uploading ? '업로드 중...' : '+ 문서 업로드'}
          </button>
          <input
            ref={fileInputRef}
            type="file"
            className="file-input-hidden"
            onChange={handleUpload}
            accept=".txt,.md,.py,.js,.ts,.json,.csv,.html,.css,.xml,.yaml,.yml,.pdf,.docx,.xlsx,.xls,.hwp,.hwpx,.log,.sh,.sql,.java,.c,.cpp,.h,.go,.rs"
          />
        </div>
        <div className="knowledge-list">
          {docs.length === 0 && (
            <p className="knowledge-empty">등록된 문서가 없습니다.</p>
          )}
          {docs.map((doc) => (
            <div key={doc.id} className="knowledge-item-wrapper">
              <div className="knowledge-item">
                <div
                  className="knowledge-item-info"
                  onClick={() => setExpandedId(expandedId === doc.id ? null : doc.id)}
                  style={{ cursor: doc.summary ? 'pointer' : 'default' }}
                >
                  <span className="knowledge-item-name">
                    {doc.summary && (
                      <span className="knowledge-expand-icon">
                        {expandedId === doc.id ? '▾' : '▸'}
                      </span>
                    )}
                    {doc.filename}
                  </span>
                  <span className="knowledge-item-meta">
                    {formatSize(doc.file_size)} · {statusLabel(doc)}
                    {doc.summary && ' · 요약 있음'}
                  </span>
                </div>
                <button
                  className="knowledge-item-delete"
                  onClick={() => handleDelete(doc.id)}
                >
                  삭제
                </button>
              </div>
              {expandedId === doc.id && doc.summary && (
                <div className="knowledge-summary">
                  {doc.summary}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
