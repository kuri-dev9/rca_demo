import React, { useState, useRef } from 'react';
import { Conversation, SearchResult } from '../types';
import { searchConversations } from '../api';

interface Props {
  conversations: Conversation[];
  activeId: number | null;
  onSelect: (id: number) => void;
  onCreate: () => void;
  onDelete: (id: number) => void;
  onRename: (id: number, title: string) => void;
  onExport: (id: number, format: 'json' | 'markdown') => void;
  onImport: (file: File) => void;
}

export default function Sidebar({ conversations, activeId, onSelect, onCreate, onDelete, onRename, onExport, onImport }: Props) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [showExportMenu, setShowExportMenu] = useState<number | null>(null);
  const importRef = useRef<HTMLInputElement>(null);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const startEditing = (conv: Conversation) => {
    setEditingId(conv.id);
    setEditTitle(conv.title);
  };

  const confirmEdit = () => {
    if (editingId && editTitle.trim()) {
      onRename(editingId, editTitle.trim());
    }
    setEditingId(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') confirmEdit();
    if (e.key === 'Escape') setEditingId(null);
  };

  const handleSearch = (query: string) => {
    setSearchQuery(query);
    if (searchTimer.current) clearTimeout(searchTimer.current);
    if (!query.trim()) {
      setSearchResults([]);
      setSearching(false);
      return;
    }
    setSearching(true);
    searchTimer.current = setTimeout(async () => {
      const results = await searchConversations(query.trim());
      setSearchResults(results);
      setSearching(false);
    }, 300);
  };

  const handleImportFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onImport(file);
      e.target.value = '';
    }
  };

  return (
    <aside className="sidebar">
      <button className="new-chat-btn" onClick={onCreate}>
        + 새 대화
      </button>
      <div className="sidebar-actions">
        <button className="sidebar-action-btn" onClick={() => importRef.current?.click()} title="대화 가져오기 (JSON)">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          가져오기
        </button>
        <input
          ref={importRef}
          type="file"
          accept=".json"
          className="file-input-hidden"
          onChange={handleImportFile}
        />
      </div>
      <div className="search-bar">
        <input
          className="search-input"
          type="text"
          placeholder="대화 검색..."
          value={searchQuery}
          onChange={(e) => handleSearch(e.target.value)}
        />
        {searchQuery && (
          <button className="search-clear" onClick={() => handleSearch('')}>×</button>
        )}
      </div>
      {searchQuery ? (
        <div className="conversation-list">
          {searching && <div className="search-status">검색 중...</div>}
          {!searching && searchResults.length === 0 && (
            <div className="search-status">검색 결과가 없습니다</div>
          )}
          {searchResults.map((r, i) => (
            <div
              key={`${r.message_id}-${i}`}
              className="search-result-item"
              onClick={() => {
                onSelect(r.conversation_id);
                setSearchQuery('');
                setSearchResults([]);
              }}
            >
              <div className="search-result-title">{r.conversation_title}</div>
              <div className="search-result-snippet">
                <span className="search-result-role">{r.role === 'user' ? '사용자' : 'AI'}: </span>
                {r.content_snippet}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="conversation-list">
          {conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${conv.id === activeId ? 'active' : ''}`}
              onClick={() => onSelect(conv.id)}
            >
              {editingId === conv.id ? (
                <input
                  className="rename-input"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  onKeyDown={handleKeyDown}
                  onBlur={confirmEdit}
                  onClick={(e) => e.stopPropagation()}
                  autoFocus
                />
              ) : (
                <span
                  className="conversation-title"
                  onDoubleClick={(e) => {
                    e.stopPropagation();
                    startEditing(conv);
                  }}
                >
                  {conv.title}
                </span>
              )}
              <div className="conversation-actions">
                <div className="export-wrapper">
                  <button
                    className="action-icon-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      setShowExportMenu(showExportMenu === conv.id ? null : conv.id);
                    }}
                    title="내보내기"
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                  </button>
                  {showExportMenu === conv.id && (
                    <div className="export-menu" onClick={(e) => e.stopPropagation()}>
                      <button onClick={() => { onExport(conv.id, 'json'); setShowExportMenu(null); }}>JSON</button>
                      <button onClick={() => { onExport(conv.id, 'markdown'); setShowExportMenu(null); }}>Markdown</button>
                    </div>
                  )}
                </div>
                <button
                  className="delete-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(conv.id);
                  }}
                >
                  ×
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
