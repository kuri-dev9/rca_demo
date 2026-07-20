import React, { useMemo, useState } from 'react';
import { RcaLabJudge } from '../api';

interface Props {
  judges: RcaLabJudge[];
  evaluating: Record<string, boolean>;
  onEvaluate: (type: 'LOCAL' | 'CLAUDE') => void;
}

interface JudgeView {
  type: 'LOCAL' | 'CLAUDE';
  status: string;
  total?: number | null;
  scores: { label: string; value?: number | null; comment?: string | null }[];
  summary?: string | null;
  error?: string | null;
  raw?: unknown;
  evaluator?: string | null;
  updatedAt?: string;
}

const scoreFields = [
  ['Accuracy', 'accuracy_score', 'accuracy_comment'],
  ['Reasoning', 'reasoning_score', 'reasoning_comment'],
  ['Evidence', 'evidence_score', 'evidence_comment'],
  ['Actionability', 'actionability_score', 'actionability_comment'],
] as const;

function safeRaw(value: unknown) {
  if (typeof value !== 'string') return value;
  try { return JSON.parse(value); } catch { return value; }
}

function normalizeJudgeResult(type: 'LOCAL' | 'CLAUDE', judge?: RcaLabJudge): JudgeView {
  if (!judge) return { type, status: '미실행', scores: scoreFields.map(([label]) => ({ label })) };
  const raw = safeRaw(judge.raw_response);
  const rawObject = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {};
  const nestedScores = rawObject.scores && typeof rawObject.scores === 'object' ? rawObject.scores as Record<string, unknown> : {};
  const nestedComments = rawObject.comments && typeof rawObject.comments === 'object' ? rawObject.comments as Record<string, unknown> : {};
  const value = (key: keyof RcaLabJudge) => {
    const baseKey = String(key).replace(/_(score|comment)$/, '');
    return judge[key] ?? rawObject[key] ?? (String(key).endsWith('_score') ? nestedScores[baseKey] : nestedComments[baseKey]);
  };
  return {
    type,
    status: judge.status || 'PENDING',
    total: value('total_score') as number | null | undefined,
    scores: scoreFields.map(([label, score, comment]) => ({
      label,
      value: value(score) as number | null | undefined,
      comment: value(comment) as string | null | undefined,
    })),
    summary: judge.judge_comment,
    error: judge.error_message || (judge.status === 'FAILED' ? judge.judge_comment : null),
    raw,
    evaluator: judge.evaluator,
    updatedAt: judge.update_dt,
  };
}

const displayScore = (value?: number | null) => {
  const numeric = Number(value);
  return value == null || !Number.isFinite(numeric) ? '-' : numeric.toFixed(1);
};

export default function RcaJudgeResults({ judges, evaluating, onEvaluate }: Props) {
  const [detail, setDetail] = useState<JudgeView | null>(null);
  const rows = useMemo(() => {
    const latest = new Map<string, RcaLabJudge>();
    judges.forEach((judge) => { if (!latest.has(judge.judge_type)) latest.set(judge.judge_type, judge); });
    return (['CLAUDE', 'LOCAL'] as const).map((type) => normalizeJudgeResult(type, latest.get(type)));
  }, [judges]);

  return <>
    <div className="rca-judge-cards">
      {rows.map((judge) => {
        const failed = judge.status === 'FAILED';
        const running = evaluating[judge.type] || judge.status === 'RUNNING' || judge.status === 'PENDING';
        return <article className={`rca-judge-card ${failed ? 'failed' : ''}`} key={judge.type}>
          <header><div><h4>{judge.type}</h4><span className={`rca-judge-status ${judge.status.toLowerCase()}`}>{running ? 'PENDING' : judge.status}</span></div><div className="rca-judge-total"><small>종합 점수</small><strong>{displayScore(judge.total)}</strong></div></header>
          {failed ? <p className="rca-judge-failure">Judge 실행 중 내부 오류가 발생했습니다.</p> : <div className="rca-judge-score-list">{judge.scores.map((score) => <div key={score.label}><span>{score.label}</span><strong>{displayScore(score.value)}</strong></div>)}</div>}
          <div className="rca-judge-actions"><button onClick={() => setDetail(judge)}>{failed ? '에러 상세보기' : '상세보기'}</button><button className="primary" disabled={running} onClick={() => onEvaluate(judge.type)}>{running ? '평가 중…' : '재평가'}</button></div>
        </article>;
      })}
    </div>
    {detail && <div className="rca-modal-backdrop" onMouseDown={() => setDetail(null)}><div className="rca-pipeline-modal rca-judge-modal" onMouseDown={(event) => event.stopPropagation()}>
      <header><div><h2>{detail.type} Judge 상세</h2><span className={`rca-judge-status ${detail.status.toLowerCase()}`}>{detail.status}</span></div><button onClick={() => setDetail(null)}>×</button></header>
      <div><div className="rca-judge-detail-meta"><span>종합 점수 <b>{displayScore(detail.total)}</b></span><span>Evaluator <b>{detail.evaluator || '-'}</b></span><span>실행 시각 <b>{detail.updatedAt ? new Date(detail.updatedAt).toLocaleString() : '-'}</b></span></div>
        <div className="rca-judge-detail-scores">{detail.scores.map((score) => <section key={score.label}><header><h3>{score.label}</h3><strong>{displayScore(score.value)}</strong></header><p>{score.comment || '코멘트가 없습니다.'}</p></section>)}</div>
        <section className="rca-judge-detail-section"><h3>전체 평가 코멘트</h3><pre>{detail.summary || '-'}</pre></section>
        {detail.error && <section className="rca-judge-detail-section error"><h3>에러 정보</h3><pre>{detail.error}</pre></section>}
        {detail.raw != null && <section className="rca-judge-detail-section"><h3>원본 Judge 응답</h3><pre>{typeof detail.raw === 'string' ? detail.raw : JSON.stringify(detail.raw, null, 2)}</pre></section>}
      </div>
    </div></div>}
  </>;
}
