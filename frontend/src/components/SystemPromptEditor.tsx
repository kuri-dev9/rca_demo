import React, { useState, useEffect } from 'react';

interface Props {
  visible: boolean;
  systemPrompt: string;
  onSave: (prompt: string) => void;
  onClose: () => void;
}

const PRESETS: { label: string; prompt: string }[] = [
  { label: '직접 입력', prompt: '' },
  { label: '한영 번역가', prompt: '너는 전문 한영 번역가야. 사용자가 한국어를 입력하면 영어로, 영어를 입력하면 한국어로 번역해. 번역만 출력하고 부가 설명은 하지 마.' },
  { label: '코드 리뷰어', prompt: '너는 시니어 소프트웨어 엔지니어야. 사용자가 코드를 보여주면 버그, 성능 문제, 가독성 개선점을 찾아서 구체적으로 피드백해줘. 코드 예시를 포함해서 답변해.' },
  { label: '영어 선생님', prompt: '너는 친절한 영어 선생님이야. 한국어로 설명하되, 예문과 핵심 표현은 영어로 제공해. 학생의 수준에 맞춰 쉽게 설명해줘.' },
  { label: '요약 전문가', prompt: '너는 텍스트 요약 전문가야. 사용자가 긴 글을 주면 핵심 내용을 3~5개 항목으로 간결하게 요약해줘. 불필요한 수식어는 제거하고 사실 중심으로 정리해.' },
  { label: '글쓰기 도우미', prompt: '너는 글쓰기 도우미야. 사용자의 글을 다듬고, 문법 오류를 수정하며, 더 자연스러운 표현을 제안해줘. 원문의 의도는 유지하면서 개선해.' },
  { label: '이동통신 네트워크 운영 전문가', prompt: '너는 이동통신 네트워크 운영 전문가야. 4G LTE, 5G NSA/SA, RAN, Core(AMF, SMF, UPF), 전송망, 기지국 운영, 장애 분석, KPI 관리, 최적화에 대해 깊이 있는 지식을 갖고 있어. 기술적 질문에 정확하고 실무적인 답변을 제공하고, 필요시 3GPP 표준이나 네트워크 구성도를 참고하여 설명해줘.' },
];

export default function SystemPromptEditor({ visible, systemPrompt, onSave, onClose }: Props) {
  const [text, setText] = useState(systemPrompt);
  const [selectedPreset, setSelectedPreset] = useState(0);

  useEffect(() => {
    setText(systemPrompt);
    const idx = PRESETS.findIndex((p) => p.prompt === systemPrompt);
    setSelectedPreset(idx >= 0 ? idx : 0);
  }, [systemPrompt, visible]);

  if (!visible) return null;

  const handlePresetChange = (index: number) => {
    setSelectedPreset(index);
    if (index > 0) {
      setText(PRESETS[index].prompt);
    }
  };

  const handleSave = () => {
    onSave(text.trim());
    onClose();
  };

  const handleReset = () => {
    setText('');
    setSelectedPreset(0);
  };

  return (
    <div className="knowledge-overlay" onClick={onClose}>
      <div className="system-prompt-panel" onClick={(e) => e.stopPropagation()}>
        <div className="knowledge-header">
          <h3>시스템 프롬프트 설정</h3>
          <button className="knowledge-close" onClick={onClose}>×</button>
        </div>
        <p className="knowledge-desc">
          AI의 역할과 행동 방식을 지정합니다. 이 대화에서 AI가 어떻게 응답할지 커스터마이징할 수 있습니다.
        </p>
        <div className="system-prompt-body">
          <div className="system-prompt-presets">
            <label className="system-prompt-label">프리셋</label>
            <div className="preset-chips">
              {PRESETS.map((preset, idx) => (
                <button
                  key={idx}
                  className={`preset-chip ${selectedPreset === idx ? 'active' : ''}`}
                  onClick={() => handlePresetChange(idx)}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>
          <div className="system-prompt-editor">
            <label className="system-prompt-label">프롬프트 내용</label>
            <textarea
              className="system-prompt-textarea"
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setSelectedPreset(0);
              }}
              placeholder="예: 너는 전문 번역가야. 한국어를 영어로 번역해줘..."
              rows={6}
            />
          </div>
          <div className="system-prompt-actions">
            <button className="system-prompt-reset" onClick={handleReset}>초기화</button>
            <button className="system-prompt-save" onClick={handleSave}>저장</button>
          </div>
        </div>
      </div>
    </div>
  );
}
