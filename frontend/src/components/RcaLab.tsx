import React, { useEffect, useMemo, useState } from 'react';
import {
  createRcaLabHumanEvaluation, evaluateRcaLabResult, fetchRcaLabEvaluation,
  fetchRcaLabExperiments, fetchRcaLabInputs, fetchRcaLabPrompt,
  fetchRcaLabPrompts, fetchRcaLabResult, fetchRcaLabResults, importRcaLabFile,
  importRcaLabSample, RcaLabEvaluationDetail, RcaLabExperiment, RcaLabInput,
  RcaLabPrompt, RcaLabResult, runRcaLabExperiment,
} from '../api';
import RcaJudgeResults from './RcaJudgeResults';

interface Props { models: { name: string }[]; selectedModel: string; }
type Mode = 'session' | 'create';
type ModalContent = { title: string; content: string } | null;

const formatDate = (value?: string) => value ? new Date(value).toLocaleString() : '-';
const formatScore = (value?: number | null) => value == null ? '-' : value.toFixed(1);

export default function RcaLab({ models, selectedModel }: Props) {
  const [mode, setMode] = useState<Mode>('session');
  const [inputs, setInputs] = useState<RcaLabInput[]>([]);
  const [prompts, setPrompts] = useState<RcaLabPrompt[]>([]);
  const [experiments, setExperiments] = useState<RcaLabExperiment[]>([]);
  const [results, setResults] = useState<RcaLabResult[]>([]);
  const [activeResultId, setActiveResultId] = useState<number | null>(null);
  const [evaluation, setEvaluation] = useState<RcaLabEvaluationDetail | null>(null);
  const [resultDetail, setResultDetail] = useState<RcaLabResult | null>(null);
  const [createInputId, setCreateInputId] = useState('');
  const [createPromptId, setCreatePromptId] = useState('');
  const [createPrompt, setCreatePrompt] = useState<RcaLabPrompt | null>(null);
  const [createModel, setCreateModel] = useState(selectedModel);
  const [createCount, setCreateCount] = useState(1);
  const [chunkSize, setChunkSize] = useState(10000);
  const [humanRating, setHumanRating] = useState('GOOD');
  const [humanComment, setHumanComment] = useState('');
  const [loading, setLoading] = useState(false);
  const [runState, setRunState] = useState<'READY' | 'RUNNING' | 'COMPLETED' | 'FAILED'>('READY');
  const [runMessage, setRunMessage] = useState('실행할 설정을 확인하세요.');
  const [message, setMessage] = useState('');
  const [evaluating, setEvaluating] = useState<Record<string, boolean>>({});
  const [mobileSessionsOpen, setMobileSessionsOpen] = useState(false);
  const [modal, setModal] = useState<ModalContent>(null);

  const activeExperiment = useMemo(() => experiments.find((item) => item.result_id === activeResultId), [experiments, activeResultId]);

  const refreshAll = async () => {
    const [nextInputs, nextPrompts, nextExperiments, nextResults] = await Promise.all([
      fetchRcaLabInputs(), fetchRcaLabPrompts(), fetchRcaLabExperiments(), fetchRcaLabResults(),
    ]);
    setInputs(nextInputs); setPrompts(nextPrompts); setExperiments(nextExperiments); setResults(nextResults);
    setCreateInputId((current) => current || (nextInputs[0] ? String(nextInputs[0].input_id) : ''));
    setCreatePromptId((current) => current || (nextPrompts[0] ? String(nextPrompts[0].prompt_id) : ''));
    setActiveResultId((current) => current && nextResults.some((row) => row.result_id === current) ? current : nextResults[0]?.result_id || null);
    return nextResults;
  };

  useEffect(() => { refreshAll().catch((error) => setMessage(error.message || 'RCA Lab 로딩 실패')); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setCreateModel(selectedModel); }, [selectedModel]);
  useEffect(() => {
    if (!activeResultId || mode !== 'session') return;
    setEvaluation(null); setResultDetail(null);
    Promise.all([fetchRcaLabEvaluation(activeResultId), fetchRcaLabResult(activeResultId)])
      .then(([detail, result]) => { setEvaluation(detail); setResultDetail(result); })
      .catch((error) => setMessage(error.message || 'Session 상세 조회 실패'));
  }, [activeResultId, mode]);
  useEffect(() => {
    if (!createPromptId || mode !== 'create') { setCreatePrompt(null); return; }
    fetchRcaLabPrompt(Number(createPromptId)).then(setCreatePrompt).catch(() => setCreatePrompt(null));
  }, [createPromptId, mode]);

  const selectSession = (id: number) => { setMode('session'); setActiveResultId(id); setMobileSessionsOpen(false); setMessage(''); };
  const openCreate = () => { setMode('create'); setMobileSessionsOpen(false); setRunState('READY'); setRunMessage('실행할 설정을 확인하세요.'); setMessage(''); };
  const showText = (title: string, content?: string | null) => setModal({ title, content: content || '내용이 없습니다.' });

  const importInput = async (file?: File) => {
    if (!file) return;
    setLoading(true); setMessage('');
    try { const created: any = await importRcaLabFile(file, chunkSize, file.name); await refreshAll(); if (created?.input_id) setCreateInputId(String(created.input_id)); setMessage('Input을 생성했습니다.'); }
    catch (error: any) { setMessage(error.message || 'Input 생성 실패'); }
    finally { setLoading(false); }
  };

  const importSample = async () => {
    setLoading(true); setMessage('');
    try { const created: any = await importRcaLabSample(chunkSize); await refreshAll(); if (created?.input_id) setCreateInputId(String(created.input_id)); setMessage('샘플 Input을 생성했습니다.'); }
    catch (error: any) { setMessage(error.message || '샘플 Input 생성 실패'); }
    finally { setLoading(false); }
  };

  const execute = async (inputId: number, promptId: number, model: string, count: number, reanalysis = false) => {
    setLoading(true); setRunState('RUNNING'); setRunMessage(reanalysis ? '동일한 설정으로 재분석 중입니다.' : 'Experiment와 Judge 평가를 실행 중입니다.'); setMessage('');
    try {
      const response: any = await runRcaLabExperiment(inputId, promptId, model, count);
      const nextResults = await refreshAll();
      const createdId = response?.result_ids?.[response.result_ids.length - 1] || nextResults[0]?.result_id;
      if (!createdId) throw new Error('생성된 Result를 확인할 수 없습니다.');
      setRunState('COMPLETED'); setRunMessage('실행이 완료되었습니다. 새 Session으로 이동합니다.');
      setCreateInputId(''); setCreatePromptId(''); setCreatePrompt(null); setCreateCount(1);
      setActiveResultId(Number(createdId)); setMode('session');
      requestAnimationFrame(() => document.querySelector('.rca-session-result')?.scrollIntoView({ behavior: 'smooth', block: 'start' }));
    } catch (error: any) { setRunState('FAILED'); setRunMessage(error.message || 'RCA 실행에 실패했습니다.'); }
    finally { setLoading(false); }
  };

  const reanalyze = () => {
    if (!evaluation) return;
    execute(evaluation.input.input_id, evaluation.prompt.prompt_id, evaluation.experiment.model, 1, true);
  };

  const evaluateJudge = async (type: 'LOCAL' | 'CLAUDE') => {
    if (!activeResultId || evaluating[type]) return;
    setEvaluating((current) => ({ ...current, [type]: true })); setMessage(`${type} Judge 평가 중...`);
    try { await evaluateRcaLabResult(activeResultId, type); setEvaluation(await fetchRcaLabEvaluation(activeResultId)); setMessage(`${type} Judge 평가가 완료되었습니다.`); }
    catch (error: any) { setMessage(error.message || `${type} Judge 평가 실패`); }
    finally { setEvaluating((current) => ({ ...current, [type]: false })); }
  };

  const saveReview = async () => {
    if (!activeResultId) return;
    setLoading(true); setMessage('');
    try { await createRcaLabHumanEvaluation(activeResultId, humanRating, humanComment); setEvaluation(await fetchRcaLabEvaluation(activeResultId)); setHumanComment(''); setMessage('Human Override를 저장했습니다.'); }
    catch (error: any) { setMessage(error.message || 'Human Override 저장 실패'); }
    finally { setLoading(false); }
  };

  const Step = ({ number, title, active = true, children }: { number: number; title: string; active?: boolean; children: React.ReactNode }) => <section className={`rca-pipeline-card ${active ? '' : 'disabled-step'}`}>
    <div className="rca-pipeline-card-head"><span className="rca-step-number">{number}</span><div><small>NEW RCA</small><h2>{title}</h2></div></div><div className="rca-pipeline-card-body">{children}</div>
  </section>;

  return <div className="rca-pipeline-shell">
    <button className="rca-mobile-session-toggle" onClick={() => setMobileSessionsOpen((value) => !value)}><span>Sessions</span><strong>{mode === 'create' ? '새 RCA 실행' : activeResultId ? `Result #${activeResultId}` : '선택 없음'}</strong><span>{mobileSessionsOpen ? '▲' : '▼'}</span></button>
    <aside className={`rca-session-sidebar ${mobileSessionsOpen ? 'open' : ''}`}>
      <div className="rca-session-head"><div><small>RCA LAB</small><h2>Sessions</h2></div><span>{results.length}</span></div>
      <button className={`rca-new-run-button ${mode === 'create' ? 'active' : ''}`} onClick={openCreate}><span>＋</span><strong>새 RCA 실행</strong></button>
      <div className="rca-session-list">{results.map((result) => <button key={result.result_id} className={mode === 'session' && activeResultId === result.result_id ? 'active' : ''} onClick={() => selectSession(result.result_id)}><span className="rca-session-status"/><span><strong>{result.input_name || `Input #${result.input_id}`}</strong><small>Result #{result.result_id} · {result.prompt_name || 'Prompt'}</small><time>{formatDate(result.update_dt)}</time></span><b>{formatScore(result.score)}</b></button>)}{!results.length && <p className="rca-pipeline-empty">아직 생성된 Session이 없습니다.</p>}</div>
    </aside>

    <main className="rca-pipeline-main">
      {message && <div className="rca-pipeline-message">{message}<button onClick={() => setMessage('')}>×</button></div>}
      {mode === 'create' ? <>
        <header className="rca-context-header"><div><small>CREATE MODE</small><h1>새 RCA 실행</h1></div><button onClick={() => activeResultId ? setMode('session') : undefined} disabled={!activeResultId}>취소하고 Session으로 돌아가기</button></header>
        <div className="rca-pipeline-flow rca-create-flow">
          <Step number={1} title="INPUT 생성 또는 선택"><label className="rca-field-label">기존 Input<select value={createInputId} onChange={(event) => setCreateInputId(event.target.value)}><option value="">Input을 선택하세요</option>{inputs.map((input) => <option key={input.input_id} value={input.input_id}>#{input.input_id} · {input.input_name} · {input.record_count || '-'} records</option>)}</select></label><div className="rca-input-create"><label>레코드 수<input type="number" min={1000} value={chunkSize} onChange={(event) => setChunkSize(Number(event.target.value))}/></label><label className="rca-file-action">파일로 생성<input type="file" accept=".dat,.csv,.txt" onChange={(event) => importInput(event.target.files?.[0])}/></label><button disabled={loading} onClick={importSample}>샘플 Input 생성</button></div></Step>
          <Step number={2} title="PROMPT 선택" active={Boolean(createInputId)}><label className="rca-field-label">Prompt<select disabled={!createInputId} value={createPromptId} onChange={(event) => setCreatePromptId(event.target.value)}><option value="">Prompt를 선택하세요</option>{prompts.map((prompt) => <option key={prompt.prompt_id} value={prompt.prompt_id}>#{prompt.prompt_id} · {prompt.prompt_name} · {prompt.version} · {prompt.status}</option>)}</select></label>{createPrompt && <div className="rca-selected-summary"><div><strong>{createPrompt.prompt_name}</strong><span>{createPrompt.version} · {createPrompt.status}</span><p>{createPrompt.text_preview || createPrompt.text?.slice(0, 180) || 'Prompt 요약이 없습니다.'}</p></div><button onClick={() => showText('Prompt 전문', createPrompt.text)}>전문 보기</button></div>}</Step>
          <Step number={3} title="EXPERIMENT 설정" active={Boolean(createInputId && createPromptId)}><div className="rca-experiment-grid"><label>Model<select disabled={!createPromptId} value={createModel} onChange={(event) => setCreateModel(event.target.value)}>{models.map((model) => <option key={model.name}>{model.name}</option>)}</select></label><label>실행 횟수<input disabled={!createPromptId} type="number" min={1} max={100} value={createCount} onChange={(event) => setCreateCount(Number(event.target.value))}/></label></div></Step>
          <Step number={4} title="RUN" active={Boolean(createInputId && createPromptId)}><div className="rca-run-summary"><div><span>Input</span><strong>{inputs.find((row) => row.input_id === Number(createInputId))?.input_name || '-'}</strong></div><div><span>Prompt</span><strong>{createPrompt?.prompt_name || '-'}</strong></div><div><span>Model</span><strong>{createModel || '-'}</strong></div><div><span>Count</span><strong>{createCount}</strong></div></div><button className="primary rca-run-button" disabled={loading || !createInputId || !createPromptId || !createModel} onClick={() => execute(Number(createInputId), Number(createPromptId), createModel, createCount)}>{loading ? '실행 중…' : runState === 'FAILED' ? '다시 실행' : 'RCA 실행'}</button></Step>
          <Step number={5} title="RESULT"><div className={`rca-run-status ${runState.toLowerCase()}`}><strong>{runState}</strong><p>{runMessage}</p></div></Step>
        </div>
      </> : <>
        <header className="rca-context-header rca-session-header"><div><small>COMPLETED RCA SESSION</small><h1>{evaluation?.input.input_name || resultDetail?.input_name || 'Session을 선택하세요'}</h1><p>Session #{activeResultId || '-'} · {formatDate(evaluation?.experiment.update_dt || resultDetail?.update_dt)}</p></div><div className="rca-session-header-actions"><span className="rca-completed-badge">COMPLETED</span><button className="primary" disabled={!evaluation || loading} onClick={reanalyze}>{loading ? '재분석 중…' : '재분석'}</button></div></header>
        <div className="rca-session-content">
          <section className="rca-session-overview"><div><span>Input ID</span><strong>#{evaluation?.input.input_id || '-'}</strong><button disabled={!evaluation} onClick={() => showText('Input 원문', evaluation?.input.text)}>상세보기</button></div><div><span>Prompt ID</span><strong>#{evaluation?.prompt.prompt_id || '-'}</strong><button disabled={!evaluation} onClick={() => showText('Prompt 전문', evaluation?.prompt.text)}>상세보기</button></div><div><span>Experiment ID</span><strong>#{activeExperiment?.experiment_id || evaluation?.experiment.run_id || '-'}</strong><small>{evaluation?.experiment.model || '-'}</small></div><div><span>Result ID</span><strong>#{activeResultId || '-'}</strong><small>{evaluation?.experiment.run_mode || '-'}</small></div></section>
          <section className="rca-session-panel rca-session-result"><header><div><small>RCA RESULT</small><h2>분석 결과</h2></div><strong className="rca-result-score">{formatScore(resultDetail?.score || evaluation?.score.total_score)}</strong></header><div className="rca-result-preview">{resultDetail?.result_preview || evaluation?.result.text?.slice(0, 900) || 'Result를 불러오는 중입니다.'}</div><button disabled={!evaluation} onClick={() => showText(`Result #${activeResultId}`, evaluation?.result.text)}>결과 상세보기</button></section>
          <section className="rca-session-panel"><header><div><small>QUALITY EVALUATION</small><h2>Judge Result</h2></div></header><RcaJudgeResults judges={evaluation?.judges || []} evaluating={evaluating} onEvaluate={evaluateJudge}/></section>
          <section className="rca-session-panel"><header><div><small>OPERATOR DECISION</small><h2>Human Review</h2></div></header><div className="rca-human-review standalone"><div className="rca-rating">{['GOOD','NORMAL','BAD'].map((rating) => <button key={rating} className={humanRating === rating ? `active ${rating.toLowerCase()}` : ''} onClick={() => setHumanRating(rating)}>{rating}</button>)}</div><label>Comment<textarea value={humanComment} onChange={(event) => setHumanComment(event.target.value)} placeholder="판단 근거와 확인 사항을 남겨주세요."/></label><button className="primary" disabled={!activeResultId || loading} onClick={saveReview}>Human Override 저장</button></div></section>
        </div>
      </>}
    </main>
    {modal && <div className="rca-modal-backdrop" onMouseDown={() => setModal(null)}><div className="rca-pipeline-modal" onMouseDown={(event) => event.stopPropagation()}><header><h2>{modal.title}</h2><button onClick={() => setModal(null)}>×</button></header><div><pre className="rca-pipeline-raw">{modal.content}</pre></div></div></div>}
  </div>;
}
