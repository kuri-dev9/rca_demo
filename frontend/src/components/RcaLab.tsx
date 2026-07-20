import React, { useEffect, useMemo, useState } from 'react';
import {
  analyzeRcaLabPrompt, compareRcaLabPrompts, createRcaLabHumanEvaluation,
  createRcaLabPrompt, deleteRcaLabInput, deleteRcaLabPrompt, evaluateRcaLabResult,
  fetchRcaLabEvaluation, fetchRcaLabExperiments, fetchRcaLabInput, fetchRcaLabInputs,
  fetchRcaLabPrompt, fetchRcaLabPrompts, fetchRcaLabResult, fetchRcaLabResults,
  importRcaLabFile, importRcaLabSample, RcaLabEvaluationDetail, RcaLabExperiment,
  RcaLabInput, RcaLabJudge, RcaLabMetaAnalysis, RcaLabPrompt, RcaLabPromptComparison,
  RcaLabPromptStats, RcaLabResult, runRcaLabExperiment, updateRcaLabPrompt,
} from '../api';

interface Props { models: { name: string }[]; selectedModel: string; }
type ModalContent = { title: string; content: React.ReactNode } | null;

const formatDate = (value?: string) => value ? new Date(value).toLocaleString() : '-';
const formatScore = (value?: number | null) => value == null ? '-' : value.toFixed(1);

export default function RcaLab({ models, selectedModel }: Props) {
  const [inputs, setInputs] = useState<RcaLabInput[]>([]);
  const [prompts, setPrompts] = useState<RcaLabPrompt[]>([]);
  const [experiments, setExperiments] = useState<RcaLabExperiment[]>([]);
  const [results, setResults] = useState<RcaLabResult[]>([]);
  const [activeResultId, setActiveResultId] = useState<number | null>(null);
  const [evaluation, setEvaluation] = useState<RcaLabEvaluationDetail | null>(null);
  const [selectedResult, setSelectedResult] = useState<RcaLabResult | null>(null);
  const [metaAnalysis, setMetaAnalysis] = useState<RcaLabMetaAnalysis | null>(null);
  const [promptComparison, setPromptComparison] = useState<RcaLabPromptComparison | null>(null);
  const [inputId, setInputId] = useState('');
  const [promptId, setPromptId] = useState('');
  const [experimentModel, setExperimentModel] = useState(selectedModel);
  const [experimentCount, setExperimentCount] = useState(1);
  const [inputChunkSize, setInputChunkSize] = useState(10000);
  const [promptText, setPromptText] = useState('');
  const [editingPrompt, setEditingPrompt] = useState<RcaLabPrompt | null>(null);
  const [humanRating, setHumanRating] = useState('GOOD');
  const [humanComment, setHumanComment] = useState('');
  const [compareResultId, setCompareResultId] = useState('');
  const [comparePromptId, setComparePromptId] = useState('');
  const [modal, setModal] = useState<ModalContent>(null);
  const [mobileSessionsOpen, setMobileSessionsOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [progress, setProgress] = useState(0);
  const [progressText, setProgressText] = useState('READY');
  const [evaluating, setEvaluating] = useState<Record<string, boolean>>({});

  const activeResult = useMemo(
    () => results.find((item) => item.result_id === activeResultId) || selectedResult,
    [results, activeResultId, selectedResult],
  );
  const activeExperiment = useMemo(() => experiments.find((item) => item.result_id === activeResultId), [experiments, activeResultId]);

  const refreshAll = async () => {
    const [nextInputs, nextPrompts, nextExperiments, nextResults] = await Promise.all([
      fetchRcaLabInputs(), fetchRcaLabPrompts(), fetchRcaLabExperiments(),
      fetchRcaLabResults(),
    ]);
    setInputs(nextInputs); setPrompts(nextPrompts); setExperiments(nextExperiments);
    setResults(nextResults);
    if (!inputId && nextInputs[0]) setInputId(String(nextInputs[0].input_id));
    if (!promptId && nextPrompts[0]) setPromptId(String(nextPrompts[0].prompt_id));
    setActiveResultId((current) => current && nextResults.some((item) => item.result_id === current) ? current : nextResults[0]?.result_id || null);
  };

  useEffect(() => { refreshAll().catch((err) => setMessage(err.message || 'RCA Lab 로딩 실패')); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { setExperimentModel(selectedModel); }, [selectedModel]);
  useEffect(() => {
    if (!activeResultId) { setEvaluation(null); setSelectedResult(null); return; }
    Promise.all([fetchRcaLabResult(activeResultId), fetchRcaLabEvaluation(activeResultId)])
      .then(([result, detail]) => { setSelectedResult(result); setEvaluation(detail); setInputId(String(detail.input.input_id)); setPromptId(String(detail.prompt.prompt_id)); })
      .catch((err) => setMessage(err.message || 'Session 상세 조회 실패'));
  }, [activeResultId]);

  const action = async (work: () => Promise<void>) => {
    setLoading(true); setMessage('');
    try { await work(); await refreshAll(); }
    catch (err: any) { setMessage(err.message || '작업에 실패했습니다.'); }
    finally { setLoading(false); }
  };

  const selectSession = (id: number) => { setActiveResultId(id); setMobileSessionsOpen(false); setMetaAnalysis(null); setPromptComparison(null); };
  const showText = (title: string, content?: string | null) => setModal({ title, content: <pre className="rca-pipeline-raw">{content || '내용이 없습니다.'}</pre> });

  const runExperiment = async () => {
    if (!inputId || !promptId) return;
    setLoading(true); setMessage(''); setProgress(0); setProgressText('RCA 실행 준비 중');
    try {
      for (let index = 0; index < experimentCount; index += 1) {
        setProgress(Math.round((index / experimentCount) * 100));
        setProgressText(`${index + 1} / ${experimentCount} RCA 실행 중`);
        await runRcaLabExperiment(Number(inputId), Number(promptId), experimentModel, 1);
      }
      setProgress(100); setProgressText('Judge 평가까지 완료'); setMessage('Experiment 실행을 완료했습니다.');
      await refreshAll();
    } catch (err: any) { setProgressText('FAILED'); setMessage(err.message || 'Experiment 실행 실패'); }
    finally { setLoading(false); }
  };

  const openPromptEditor = async (id?: number) => {
    if (!id) { setEditingPrompt(null); setPromptText('\n'); return; }
    const detail = await fetchRcaLabPrompt(id);
    setEditingPrompt(detail); setPromptText(detail.text || '');
  };

  const savePrompt = () => action(async () => {
    if (editingPrompt) await updateRcaLabPrompt(editingPrompt.prompt_id, promptText);
    else await createRcaLabPrompt(promptText);
    setEditingPrompt(null); setPromptText(''); setMessage('Prompt를 저장했습니다.');
  });

  const analyzePrompt = () => action(async () => {
    const target = evaluation?.prompt.prompt_id || Number(promptId);
    if (!target) throw new Error('분석할 Prompt가 없습니다.');
    setMetaAnalysis(await analyzeRcaLabPrompt(target)); setMessage('Meta Analyzer 분석을 완료했습니다.');
  });

  const compare = () => action(async () => {
    if (!evaluation || !comparePromptId) throw new Error('비교할 Prompt를 선택하세요.');
    const comparison = await compareRcaLabPrompts(evaluation.prompt.prompt_id, Number(comparePromptId), evaluation.input.input_id, activeResult?.model || undefined);
    setPromptComparison(comparison);
    setModal({ title: `Result #${activeResultId} Compare`, content: renderComparison(comparison) });
  });

  const saveHumanReview = () => action(async () => {
    if (!activeResultId) throw new Error('평가할 Session을 선택하세요.');
    await createRcaLabHumanEvaluation(activeResultId, humanRating, humanComment);
    setEvaluation(await fetchRcaLabEvaluation(activeResultId)); setHumanComment(''); setMessage('Human Override를 저장했습니다.');
  });

  const evaluateJudge = async (type: 'LOCAL' | 'CLAUDE') => {
    if (!activeResultId || evaluating[type]) return;
    setEvaluating((prev) => ({ ...prev, [type]: true })); setMessage(`${type} 평가 중...`);
    try { await evaluateRcaLabResult(activeResultId, type); setEvaluation(await fetchRcaLabEvaluation(activeResultId)); setMessage(`${type} 평가가 완료되었습니다.`); }
    catch (err: any) { setMessage(err.message || `${type} 평가 실패`); }
    finally { setEvaluating((prev) => ({ ...prev, [type]: false })); }
  };

  const latestJudges = (rows: RcaLabJudge[] = []) => {
    const map = new Map<string, RcaLabJudge>(); rows.forEach((row) => { if (!map.has(row.judge_type)) map.set(row.judge_type, row); });
    return Array.from(map.values());
  };

  const metrics = (stats?: RcaLabPromptStats | null) => <div className="rca-pipeline-metrics">
    {[['Total', stats?.average_score], ['Accuracy', stats?.accuracy_average], ['Reasoning', stats?.reasoning_average], ['Evidence', stats?.evidence_average], ['Action', stats?.actionability_average]].map(([label, value]) =>
      <div key={String(label)}><span>{label}</span><strong>{formatScore(value as number | null | undefined)}</strong></div>)}
  </div>;

  function renderComparison(comparison = promptComparison) {
    if (!comparison) return <div className="rca-pipeline-empty">비교를 실행하면 결과가 표시됩니다.</div>;
    return <div className="rca-compare-content"><p>{comparison.change_summary}</p>{metrics(comparison.right.stats)}
      <table className="rca-pipeline-table"><thead><tr><th>Metric</th><th>{comparison.left.prompt_name}</th><th>{comparison.right.prompt_name}</th><th>Delta</th></tr></thead><tbody>
        {[['Total','average_score','total_score'],['Accuracy','accuracy_average','accuracy'],['Reasoning','reasoning_average','reasoning'],['Evidence','evidence_average','evidence'],['Action','actionability_average','actionability']].map(([label,key,delta]) => <tr key={label}><td>{label}</td><td>{formatScore((comparison.left.stats as any)[key])}</td><td>{formatScore((comparison.right.stats as any)[key])}</td><td>{formatScore(comparison.deltas[delta])}</td></tr>)}
      </tbody></table></div>;
  }

  const Card = ({ step, title, children }: { step: number; title: string; children: React.ReactNode }) => <section className="rca-pipeline-card">
    <div className="rca-pipeline-card-head"><span className="rca-step-number">{step}</span><div><small>RCA PIPELINE</small><h2>{title}</h2></div></div>
    <div className="rca-pipeline-card-body">{children}</div>
  </section>;

  return <div className="rca-pipeline-shell">
    <button className="rca-mobile-session-toggle" onClick={() => setMobileSessionsOpen((v) => !v)}>
      <span>Sessions</span><strong>{activeResultId ? `Result #${activeResultId}` : '선택 없음'}</strong><span>{mobileSessionsOpen ? '▲' : '▼'}</span>
    </button>
    <aside className={`rca-session-sidebar ${mobileSessionsOpen ? 'open' : ''}`}>
      <div className="rca-session-head"><div><small>RCA LAB</small><h2>Sessions</h2></div><span>{results.length}</span></div>
      <div className="rca-session-list">{results.map((result) => <button key={result.result_id} className={activeResultId === result.result_id ? 'active' : ''} onClick={() => selectSession(result.result_id)}>
        <span className="rca-session-status" /><span><strong>{result.input_name || `Input #${result.input_id}`}</strong><small>Result #{result.result_id} · {result.prompt_name || 'Prompt'}</small><time>{formatDate(result.update_dt)}</time></span><b>{formatScore(result.score)}</b>
      </button>)}{!results.length && <p className="rca-pipeline-empty">아직 생성된 Session이 없습니다.</p>}</div>
      <div className="rca-session-tools">
        <strong>새 Input</strong><div><input type="number" min={1000} value={inputChunkSize} onChange={(e) => setInputChunkSize(Number(e.target.value))} />
        <label>파일<input type="file" accept=".dat,.csv,.txt" onChange={(e) => { const file=e.target.files?.[0]; if (file) action(async () => { await importRcaLabFile(file,inputChunkSize,file.name); }); }} /></label>
        <button disabled={loading} onClick={() => action(async () => { await importRcaLabSample(inputChunkSize); })}>샘플</button></div>
      </div>
    </aside>

    <main className="rca-pipeline-main">
      <header className="rca-context-header">
        <div><small>CURRENT RCA SESSION</small><h1>{evaluation?.input.input_name || activeResult?.input_name || 'Session을 선택하세요'}</h1></div>
        <div className="rca-context-chips"><span>Input <b>#{evaluation?.input.input_id || activeResult?.input_id || '-'}</b></span><span>Prompt <b>#{evaluation?.prompt.prompt_id || activeResult?.prompt_id || '-'}</b></span><span>Experiment <b>#{activeExperiment?.experiment_id || '-'}</b></span><span>Result <b>#{activeResultId || '-'}</b></span></div>
      </header>
      {message && <div className="rca-pipeline-message">{message}<button onClick={() => setMessage('')}>×</button></div>}

      <div className="rca-pipeline-flow">
        <Card step={1} title="INPUT"><div className="rca-summary-row"><div><h3>{evaluation?.input.input_name || 'Input 선택'}</h3><p>{evaluation?.input.summary || 'Session의 분석 입력 데이터입니다.'}</p></div><div className="rca-card-actions"><span>{evaluation?.input.record_count?.toLocaleString() || '-'} records</span><button disabled={!evaluation} onClick={() => showText('Input 원문', evaluation?.input.text)}>원문 보기</button></div></div>
          <div className="rca-manage-row"><select value={inputId} onChange={(e)=>setInputId(e.target.value)}>{inputs.map((item)=><option key={item.input_id} value={item.input_id}>#{item.input_id} {item.input_name}</option>)}</select><button disabled={!inputId} onClick={() => action(async()=>{ const detail=await fetchRcaLabInput(Number(inputId)); showText(detail.input_name,detail.text || detail.description); })}>조회</button><button className="danger" disabled={!inputId} onClick={()=>action(()=>deleteRcaLabInput(Number(inputId)))}>삭제</button></div>
        </Card>

        <Card step={2} title="PROMPT"><div className="rca-summary-row"><div><h3>{evaluation?.prompt.prompt_name || 'Prompt 선택'}</h3><p>{evaluation ? `${evaluation.prompt.version} · Prompt #${evaluation.prompt.prompt_id}` : 'Experiment에 사용할 Prompt를 선택하세요.'}</p></div><div className="rca-card-actions"><button disabled={!evaluation} onClick={() => showText('Prompt 전문',evaluation?.prompt.text)}>전문 보기</button></div></div>
          <div className="rca-manage-row"><select value={promptId} onChange={(e)=>setPromptId(e.target.value)}>{prompts.map((item)=><option key={item.prompt_id} value={item.prompt_id}>#{item.prompt_id} {item.prompt_name} {item.version}</option>)}</select><button onClick={()=>openPromptEditor(Number(promptId))}>편집</button><button onClick={()=>openPromptEditor()}>새 Prompt</button><button className="danger" disabled={!promptId} onClick={()=>action(()=>deleteRcaLabPrompt(Number(promptId)))}>삭제</button></div>
          {(editingPrompt || promptText !== '') && <div className="rca-inline-editor"><textarea value={promptText} onChange={(e)=>setPromptText(e.target.value)} placeholder="RCA system prompt"/><div><button onClick={()=>{setEditingPrompt(null);setPromptText('');}}>취소</button><button disabled={!promptText.trim() || loading} onClick={savePrompt}>저장</button></div></div>}
        </Card>

        <Card step={3} title="EXPERIMENT"><div className="rca-experiment-grid"><label>Input<select value={inputId} onChange={(e)=>setInputId(e.target.value)}>{inputs.map((item)=><option key={item.input_id} value={item.input_id}>{item.input_name}</option>)}</select></label><label>Prompt<select value={promptId} onChange={(e)=>setPromptId(e.target.value)}>{prompts.map((item)=><option key={item.prompt_id} value={item.prompt_id}>{item.prompt_name}</option>)}</select></label><label>Model<select value={experimentModel} onChange={(e)=>setExperimentModel(e.target.value)}>{models.map((item)=><option key={item.name}>{item.name}</option>)}</select></label><label>Count<input type="number" min={1} max={100} value={experimentCount} onChange={(e)=>setExperimentCount(Number(e.target.value))}/></label><button className="primary" disabled={loading || !inputId || !promptId} onClick={runExperiment}>{loading ? '처리 중…' : 'Experiment 실행'}</button></div>
          <div className="rca-progress"><div><span>{progressText}</span><b>{progress}%</b></div><i><span style={{width:`${progress}%`}}/></i></div>
        </Card>

        <Card step={4} title="RESULT"><div className="rca-result-head"><div><h3>Result #{activeResultId || '-'}</h3><p>{activeResult?.model || activeExperiment?.model || '-'} · {formatDate(activeResult?.update_dt)}</p></div><strong className="rca-result-score">{formatScore(activeResult?.score)}</strong></div>
          <div className="rca-result-preview">{activeResult?.result_preview || selectedResult?.text?.slice(0,600) || 'Session을 선택하면 Result가 표시됩니다.'}</div>
          <div className="rca-card-actions"><button disabled={!selectedResult} onClick={()=>showText(`Result #${activeResultId}`,selectedResult?.text)}>전체 결과 보기</button><select value={compareResultId} onChange={(e)=>setCompareResultId(e.target.value)}><option value="">Result 선택</option>{results.filter((r)=>r.result_id!==activeResultId).map((r)=><option key={r.result_id} value={r.result_id}>Result #{r.result_id} · {r.prompt_name}</option>)}</select><button disabled={!compareResultId} onClick={async()=>{const other=await fetchRcaLabResult(Number(compareResultId));setModal({title:`Result #${activeResultId} vs #${compareResultId}`,content:<div className="rca-side-compare"><pre>{selectedResult?.text}</pre><pre>{other.text || other.result_preview}</pre></div>});}}>Compare</button></div>
        </Card>

        <Card step={5} title="META ANALYZER"><div className="rca-card-actions"><button className="primary" disabled={!evaluation || loading} onClick={analyzePrompt}>현재 Prompt 분석</button><select value={comparePromptId} onChange={(e)=>setComparePromptId(e.target.value)}><option value="">비교 Prompt 선택</option>{prompts.filter((p)=>p.prompt_id!==evaluation?.prompt.prompt_id).map((p)=><option key={p.prompt_id} value={p.prompt_id}>{p.prompt_name} {p.version}</option>)}</select><button disabled={!comparePromptId || loading} onClick={compare}>Prompt 비교</button></div>
          {metaAnalysis ? <div className="rca-meta-content">{metrics(metaAnalysis.stats)}<div className="rca-meta-columns"><div><h3>강점</h3><ul>{metaAnalysis.analysis.strengths.map((x)=><li key={x}>{x}</li>)}</ul></div><div><h3>개선 필요</h3><ul>{[...metaAnalysis.analysis.weaknesses,...metaAnalysis.improvement_proposal.items].map((x)=><li key={x}>{x}</li>)}</ul></div></div></div> : <p className="rca-pipeline-empty">현재 Session의 Prompt를 분석해 성능과 개선점을 확인하세요.</p>}
        </Card>

        <Card step={6} title="HUMAN REVIEW"><div className="rca-review-layout"><div><h3>Judge Result</h3>{evaluation ? <div className="rca-judge-list">{latestJudges(evaluation.judges).map((judge)=><div key={`${judge.judge_type}-${judge.judge_id}`}><span><b>{judge.judge_type}</b><small>{judge.status}</small></span><strong>{formatScore(judge.total_score)}</strong>{(judge.judge_type==='LOCAL'||judge.judge_type==='CLAUDE')&&<button disabled={evaluating[judge.judge_type]} onClick={()=>evaluateJudge(judge.judge_type as 'LOCAL'|'CLAUDE')}>{evaluating[judge.judge_type]?'평가 중':'재평가'}</button>}<p>{judge.judge_comment || judge.error_message || '-'}</p></div>)}</div>:<p className="rca-pipeline-empty">Judge 결과가 없습니다.</p>}</div>
            <div className="rca-human-review"><h3>Human Override</h3><div className="rca-rating">{['GOOD','NORMAL','BAD'].map((rating)=><button key={rating} className={humanRating===rating?`active ${rating.toLowerCase()}`:''} onClick={()=>setHumanRating(rating)}>{rating}</button>)}</div><label>Comment<textarea value={humanComment} onChange={(e)=>setHumanComment(e.target.value)} placeholder="판단 근거와 확인 사항을 남겨주세요."/></label><button className="primary" disabled={!activeResultId || loading} onClick={saveHumanReview}>Human Override 저장</button></div></div>
        </Card>
      </div>
    </main>
    {modal && <div className="rca-modal-backdrop" onMouseDown={()=>setModal(null)}><div className="rca-pipeline-modal" onMouseDown={(e)=>e.stopPropagation()}><header><h2>{modal.title}</h2><button onClick={()=>setModal(null)}>×</button></header><div>{modal.content}</div></div></div>}
  </div>;
}
