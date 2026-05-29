import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { PromptDebug, Reference } from '../types';

interface Props {
  role: 'user' | 'assistant';
  content: string;
  references?: Reference[];
  debugPrompts?: PromptDebug[];
}

function CodeBlock({ language, children }: { language: string; children: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(children);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="code-block">
      <div className="code-block-header">
        <span className="code-language">{language}</span>
        <button className="copy-btn" onClick={handleCopy}>
          {copied ? '복사됨' : '복사'}
        </button>
      </div>
      <SyntaxHighlighter style={oneDark} language={language} PreTag="div">
        {children}
      </SyntaxHighlighter>
    </div>
  );
}

function formatTokenEstimate(tokens?: number) {
  if (!tokens) return '';
  return tokens >= 1000 ? `~${(tokens / 1000).toFixed(1)}k` : `~${tokens}`;
}

export default function ChatMessage({ role, content, references, debugPrompts }: Props) {
  const [activePrompt, setActivePrompt] = useState<number | null>(null);
  const hasPrompt = role === 'assistant' && debugPrompts && debugPrompts.length > 0;

  return (
    <div className={`message ${role}`}>
      <div className="message-avatar">
        {role === 'user'
          ? <img src="/send_icon.svg" alt="User" className="avatar-icon" />
          : <img src="/ai_icon.svg" alt="AI" className="avatar-icon" />}
      </div>
      <div className="message-content">
        {hasPrompt && (
          <div className="prompt-debug-actions">
            {debugPrompts.map((prompt, idx) => (
              <button
                key={`${prompt.call_index}-${idx}`}
                className="prompt-debug-btn"
                onClick={() => setActivePrompt((prev) => prev === idx ? null : idx)}
              >
                {prompt.label || `LLM Call #${prompt.call_index || idx + 1}`} {activePrompt === idx ? 'Hide Prompt' : 'View Prompt'}
                {prompt.estimated_tokens ? ` • ${formatTokenEstimate(prompt.estimated_tokens)} tokens` : ''}
              </button>
            ))}
          </div>
        )}
        {hasPrompt && activePrompt !== null && (
          <textarea
            className="prompt-debug-viewer"
            value={debugPrompts[activePrompt]?.final_prompt || ''}
            readOnly
          />
        )}
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            code({ node, className, children, ...props }) {
              const match = /language-(\w+)/.exec(className || '');
              const inline = !match && !String(children).includes('\n');
              if (inline) {
                return <code className="inline-code" {...props}>{children}</code>;
              }
              return (
                <CodeBlock language={match ? match[1] : 'text'}>
                  {String(children).replace(/\n$/, '')}
                </CodeBlock>
              );
            },
            table({ children }) {
              return (
                <div className="table-wrapper">
                  <table>{children}</table>
                </div>
              );
            },
          }}
        >
          {content}
        </ReactMarkdown>
        {references && references.length > 0 && (
          <div className="references">
            <span className="references-label">참조 문서</span>
            {references.map((ref, idx) => (
              <span key={idx} className="reference-chip">
                {ref.filename}
                <span className="reference-score">{Math.round(ref.score * 100)}%</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
