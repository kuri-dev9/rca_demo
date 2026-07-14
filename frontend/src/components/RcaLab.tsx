import React, { useEffect, useMemo, useState } from 'react';
import {
  analyzeRcaLabPrompt,
  compareRcaLabPrompts,
  createRcaLabHumanEvaluation,
  createRcaLabPrompt,
  deleteRcaLabInput,
  deleteRcaLabPrompt,
  fetchRcaLabExperiments,
  fetchRcaLabEvaluation,
  fetchRcaLabInput,
  fetchRcaLabInputs,
  fetchRcaLabPrompt,
  fetchRcaLabPromptComments,
  fetchRcaLabPromptPerformance,
  fetchRcaLabPrompts,
  fetchRcaLabPromptStats,
  fetchRcaLabResult,
  fetchRcaLabResults,
  importRcaLabFile,
  importRcaLabSample,
  RcaLabExperiment,
  RcaLabEvaluationDetail,
  RcaLabInput,
  RcaLabMetaAnalysis,
  RcaLabPrompt,
  RcaLabPromptComparison,
  RcaLabPromptStats,
  RcaLabResult,
  runRcaLabExperiment,
  updateRcaLabPrompt,
} from '../api';

type Tab = 'inputs' | 'prompts' | 'experiments' | 'results' | 'meta' | 'human';

interface Props {
  models: { name: string }[];
  selectedModel: string;
}

function formatDate(value?: string) {
  if (!value) return '-';
  return new Date(value).toLocaleString();
}

function formatScore(value?: number | null) {
  return value === null || value === undefined ? '-' : value.toFixed(1);
}

export default function RcaLab({ models, selectedModel }: Props) {
  const [tab, setTab] = useState<Tab>('inputs');
  const [inputs, setInputs] = useState<RcaLabInput[]>([]);
  const [prompts, setPrompts] = useState<RcaLabPrompt[]>([]);
  const [experiments, setExperiments] = useState<RcaLabExperiment[]>([]);
  const [results, setResults] = useState<RcaLabResult[]>([]);
  const [promptPerformance, setPromptPerformance] = useState<RcaLabPromptStats[]>([]);
  const [selectedInput, setSelectedInput] = useState<RcaLabInput | null>(null);
  const [selectedPrompt, setSelectedPrompt] = useState<RcaLabPrompt | null>(null);
  const [selectedPromptStats, setSelectedPromptStats] = useState<RcaLabPromptStats | null>(null);
  const [selectedPromptComments, setSelectedPromptComments] = useState<{ comment: string; count: number }[]>([]);
  const [selectedResult, setSelectedResult] = useState<RcaLabResult | null>(null);
  const [evaluationDetail, setEvaluationDetail] = useState<RcaLabEvaluationDetail | null>(null);
  const [metaAnalysis, setMetaAnalysis] = useState<RcaLabMetaAnalysis | null>(null);
  const [promptComparison, setPromptComparison] = useState<RcaLabPromptComparison | null>(null);
  const [promptText, setPromptText] = useState('');
  const [experimentInputId, setExperimentInputId] = useState('');
  const [experimentPromptId, setExperimentPromptId] = useState('');
  const [experimentModel, setExperimentModel] = useState(selectedModel);
  const [experimentCount, setExperimentCount] = useState(1);
  const [compareInputId, setCompareInputId] = useState('');
  const [compareModel, setCompareModel] = useState('');
  const [metaPromptId, setMetaPromptId] = useState('');
  const [leftComparePromptId, setLeftComparePromptId] = useState('');
  const [rightComparePromptId, setRightComparePromptId] = useState('');
  const [inputChunkSize, setInputChunkSize] = useState(10000);
  const [humanRating, setHumanRating] = useState('GOOD');
  const [humanComment, setHumanComment] = useState('');
  const [experimentStatus, setExperimentStatus] = useState<'READY' | 'RUNNING' | 'SCORING' | 'COMPLETED' | 'FAILED'>('READY');
  const [experimentProgress, setExperimentProgress] = useState(0);
  const [experimentProgressText, setExperimentProgressText] = useState('READY');
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    input: true,
    prompt: true,
    result: true,
    score: true,
    comment: true,
    judges: true,
  });
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const defaultResultId = useMemo(() => results[0]?.result_id || '', [results]);

  const refreshAll = async () => {
    const currentInputId = compareInputId ? Number(compareInputId) : undefined;
    const currentModel = compareModel || undefined;
    const [nextInputs, nextPrompts, nextExperiments, nextResults, nextPerformance] = await Promise.all([
      fetchRcaLabInputs(),
      fetchRcaLabPrompts(),
      fetchRcaLabExperiments(),
      fetchRcaLabResults(currentInputId, currentModel),
      fetchRcaLabPromptPerformance(currentInputId, currentModel),
    ]);
    setInputs(nextInputs);
    setPrompts(nextPrompts);
    setExperiments(nextExperiments);
    setResults(nextResults);
    setPromptPerformance(nextPerformance);
    if (!experimentInputId && nextInputs[0]) setExperimentInputId(String(nextInputs[0].input_id));
    if (!experimentPromptId && nextPrompts[0]) setExperimentPromptId(String(nextPrompts[0].prompt_id));
    if (!metaPromptId && nextPrompts[0]) setMetaPromptId(String(nextPrompts[0].prompt_id));
    if (!leftComparePromptId && nextPrompts[0]) setLeftComparePromptId(String(nextPrompts[0].prompt_id));
    if (!rightComparePromptId && nextPrompts[1]) setRightComparePromptId(String(nextPrompts[1].prompt_id));
  };

  useEffect(() => {
    refreshAll().catch((err) => setMessage(err.message || 'RCA Lab 로딩 실패'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setExperimentModel(selectedModel);
  }, [selectedModel]);

  useEffect(() => {
    if (tab === 'human' && !evaluationDetail && defaultResultId) {
      handleShowResult(Number(defaultResultId)).catch((err) => setMessage(err.message || '평가 상세 조회 실패'));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, defaultResultId]);

  const runAction = async (action: () => Promise<void>) => {
    setLoading(true);
    setMessage('');
    try {
      await action();
      await refreshAll();
    } catch (err: any) {
      setMessage(err.message || '작업 실패');
    } finally {
      setLoading(false);
    }
  };

  const handleShowInput = async (id: number) => {
    const detail = await fetchRcaLabInput(id);
    setSelectedInput(detail);
  };

  const handleShowPrompt = async (id: number) => {
    const [detail, stats, comments] = await Promise.all([
      fetchRcaLabPrompt(id),
      fetchRcaLabPromptStats(id),
      fetchRcaLabPromptComments(id),
    ]);
    setSelectedPrompt(detail);
    setSelectedPromptStats(stats);
    setSelectedPromptComments(comments.comment_frequency);
    setPromptText(detail.text || '');
  };

  const handleShowResult = async (id: number) => {
    const [detail, evaluation] = await Promise.all([
      fetchRcaLabResult(id),
      fetchRcaLabEvaluation(id),
    ]);
    setSelectedResult(detail);
    setEvaluationDetail(evaluation);
  };

  const handlePromptSave = async () => {
    await runAction(async () => {
      if (selectedPrompt) {
        await updateRcaLabPrompt(selectedPrompt.prompt_id, promptText);
        setMessage('Prompt를 수정했습니다.');
      } else {
        await createRcaLabPrompt(promptText);
        setMessage('Prompt를 등록했습니다.');
      }
      setSelectedPrompt(null);
      setPromptText('');
    });
  };

  const handleInputFileImport = async (file?: File | null) => {
    if (!file) return;
    await runAction(async () => {
      await importRcaLabFile(file, inputChunkSize, file.name);
      setMessage('파일 INPUT 생성을 완료했습니다.');
    });
  };

  const handleRunExperiment = async () => {
    setLoading(true);
    setMessage('');
    setExperimentStatus('RUNNING');
    setExperimentProgress(0);
    setExperimentProgressText(`0 / ${experimentCount}`);
    try {
      for (let i = 0; i < experimentCount; i += 1) {
        setExperimentStatus('RUNNING');
        setExperimentProgress(Math.round((i / experimentCount) * 100));
        setExperimentProgressText(`${i} / ${experimentCount} RCA 실행 중`);
        await runRcaLabExperiment(
          Number(experimentInputId),
          Number(experimentPromptId),
          experimentModel,
          1,
        );
        setExperimentStatus('SCORING');
        setExperimentProgress(Math.round(((i + 1) / experimentCount) * 100));
        setExperimentProgressText(`${i + 1} / ${experimentCount} AI Judge 반영`);
        await refreshAll();
      }
      setExperimentStatus('COMPLETED');
      setExperimentProgress(100);
      setExperimentProgressText('COMPLETED');
      if (metaAnalysis && metaPromptId) {
        setMetaAnalysis(await analyzeRcaLabPrompt(Number(metaPromptId)));
      }
      if (promptComparison && leftComparePromptId && rightComparePromptId) {
        setPromptComparison(await compareRcaLabPrompts(
          Number(leftComparePromptId),
          Number(rightComparePromptId),
          compareInputId ? Number(compareInputId) : undefined,
          compareModel || undefined,
        ));
      }
      setMessage('Experiment 실행과 AI Judge 평가가 완료되었습니다.');
    } catch (err: any) {
      setExperimentStatus('FAILED');
      setExperimentProgressText('FAILED');
      setMessage(err.message || 'Experiment 실행 실패');
    } finally {
      setLoading(false);
    }
  };

  const handleHumanSave = async () => {
    const resultId = selectedResult?.result_id || Number(defaultResultId);
    if (!resultId) {
      setMessage('평가할 Result를 선택하세요.');
      return;
    }
    await runAction(async () => {
      await createRcaLabHumanEvaluation(resultId, humanRating, humanComment);
      const evaluation = await fetchRcaLabEvaluation(resultId);
      setEvaluationDetail(evaluation);
      setHumanComment('');
      setMessage('Human 평가를 저장했습니다.');
    });
  };

  const handleAnalyzePrompt = async () => {
    if (!metaPromptId) {
      setMessage('분석할 Prompt를 선택하세요.');
      return;
    }
    await runAction(async () => {
      const analysis = await analyzeRcaLabPrompt(Number(metaPromptId));
      setMetaAnalysis(analysis);
      setMessage('Meta Analyzer 분석을 완료했습니다.');
    });
  };

  const handleComparePrompts = async () => {
    if (!leftComparePromptId || !rightComparePromptId) {
      setMessage('비교할 Prompt 두 개를 선택하세요.');
      return;
    }
    await runAction(async () => {
      const comparison = await compareRcaLabPrompts(
        Number(leftComparePromptId),
        Number(rightComparePromptId),
        compareInputId ? Number(compareInputId) : undefined,
        compareModel || undefined,
      );
      setPromptComparison(comparison);
      setMessage('Prompt 비교를 완료했습니다.');
    });
  };

  const renderMetricGrid = (stats?: RcaLabPromptStats | null) => (
    <div className="rca-lab-metrics">
      <div><span>Total</span><strong>{formatScore(stats?.average_score)}</strong></div>
      <div><span>Accuracy</span><strong>{formatScore(stats?.accuracy_average)}</strong></div>
      <div><span>Reasoning</span><strong>{formatScore(stats?.reasoning_average)}</strong></div>
      <div><span>Evidence</span><strong>{formatScore(stats?.evidence_average)}</strong></div>
      <div><span>Actionability</span><strong>{formatScore(stats?.actionability_average)}</strong></div>
      <div><span>Recent 10</span><strong>{formatScore(stats?.recent_10_average)}</strong></div>
    </div>
  );

  const toggleSection = (key: string) => {
    setOpenSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const renderEvaluationSection = (key: string, title: string, content: React.ReactNode) => (
    <section className="rca-eval-section">
      <button className="rca-eval-section-title" onClick={() => toggleSection(key)}>
        <span>{openSections[key] ? 'v' : '>'} {title}</span>
      </button>
      {openSections[key] && <div className="rca-eval-section-body">{content}</div>}
    </section>
  );

  return (
    <div className="rca-lab">
      <div className="rca-lab-tabs">
        {[
          ['inputs', 'INPUT 관리'],
          ['prompts', 'Prompt 관리'],
          ['experiments', 'Experiment 실행'],
          ['results', 'Result 비교'],
          ['meta', 'Meta Analyzer'],
          ['human', '평가 / Human Override'],
        ].map(([key, label]) => (
          <button
            key={key}
            className={tab === key ? 'active' : ''}
            onClick={() => setTab(key as Tab)}
          >
            {label}
          </button>
        ))}
      </div>

      {message && <div className="rca-lab-message">{message}</div>}

      {tab === 'inputs' && (
        <section className="rca-lab-grid">
          <div className="rca-lab-panel wide">
            <div className="rca-lab-panel-header">
              <h2>INPUT 관리</h2>
              <div className="rca-lab-inline-actions">
                <input
                  type="number"
                  min={1000}
                  value={inputChunkSize}
                  onChange={(e) => setInputChunkSize(Number(e.target.value))}
                  title="chunk size"
                />
                <label className="rca-lab-file-btn">
                  파일 생성
                  <input
                    type="file"
                    accept=".dat,.csv,.txt"
                    onChange={(e) => handleInputFileImport(e.target.files?.[0])}
                  />
                </label>
                <button disabled={loading} onClick={() => runAction(async () => { await importRcaLabSample(inputChunkSize); setMessage('샘플 INPUT 생성을 요청했습니다.'); })}>
                  샘플 생성
                </button>
              </div>
            </div>
            <table className="rca-lab-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>이름</th>
                  <th>데이터 건수</th>
                  <th>상태</th>
                  <th>생성/수정</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {inputs.map((input) => (
                  <tr key={input.input_id}>
                    <td>{input.input_id}</td>
                    <td>{input.input_name}</td>
                    <td>{input.record_count?.toLocaleString() || '-'}</td>
                    <td>{input.status}</td>
                    <td>{formatDate(input.update_dt)}</td>
                    <td className="rca-lab-actions">
                      <button onClick={() => handleShowInput(input.input_id)}>상세</button>
                      <button onClick={() => runAction(() => deleteRcaLabInput(input.input_id))}>삭제</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <pre className="rca-lab-preview">{selectedInput?.text || selectedInput?.description || 'INPUT 상세를 선택하세요.'}</pre>
        </section>
      )}

      {tab === 'prompts' && (
        <section className="rca-lab-grid">
          <div className="rca-lab-panel">
            <h2>Prompt 목록</h2>
            <table className="rca-lab-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Name</th>
                  <th>Version</th>
                  <th>실행</th>
                  <th>평균</th>
                  <th>최근10</th>
                  <th>Reasoning</th>
                  <th>Evidence</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {prompts.map((prompt) => (
                  <tr key={prompt.prompt_id}>
                    <td>{prompt.prompt_id}</td>
                    <td>{prompt.prompt_name}</td>
                    <td>{prompt.version}</td>
                    <td>{prompt.execution_count || 0}</td>
                    <td>{formatScore(prompt.average_score)}</td>
                    <td>{formatScore(prompt.recent_10_average)}</td>
                    <td>{formatScore(prompt.reasoning_average)}</td>
                    <td>{formatScore(prompt.evidence_average)}</td>
                    <td className="rca-lab-actions">
                      <button onClick={() => handleShowPrompt(prompt.prompt_id)}>열기</button>
                      <button onClick={() => { setMetaPromptId(String(prompt.prompt_id)); setTab('meta'); }}>분석</button>
                      <button onClick={() => runAction(() => deleteRcaLabPrompt(prompt.prompt_id))}>삭제</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="rca-lab-panel">
            <div className="rca-lab-panel-header">
              <h2>{selectedPrompt ? `${selectedPrompt.prompt_name} 수정` : 'Prompt 등록'}</h2>
              {selectedPrompt && <button onClick={() => { setSelectedPrompt(null); setSelectedPromptStats(null); setSelectedPromptComments([]); setPromptText(''); }}>새 Prompt</button>}
            </div>
            {selectedPromptStats && renderMetricGrid(selectedPromptStats)}
            {selectedPromptComments.length > 0 && (
              <div className="rca-lab-comment-box">
                <h3>Comment 빈도</h3>
                {selectedPromptComments.slice(0, 5).map((item) => (
                  <div key={item.comment} className="rca-lab-comment-row">
                    <span>{item.comment}</span>
                    <strong>{item.count}</strong>
                  </div>
                ))}
              </div>
            )}
            <textarea
              className="rca-lab-textarea"
              value={promptText}
              onChange={(e) => setPromptText(e.target.value)}
              placeholder="RCA system prompt를 입력하세요."
            />
            <button disabled={loading || !promptText.trim()} onClick={handlePromptSave}>
              {selectedPrompt ? '수정 저장' : '등록'}
            </button>
          </div>
        </section>
      )}

      {tab === 'experiments' && (
        <section className="rca-lab-grid">
          <div className="rca-lab-panel">
            <h2>Experiment 실행</h2>
            <label>INPUT</label>
            <select value={experimentInputId} onChange={(e) => setExperimentInputId(e.target.value)}>
              {inputs.map((input) => <option key={input.input_id} value={input.input_id}>{input.input_name}</option>)}
            </select>
            <label>Prompt</label>
            <select value={experimentPromptId} onChange={(e) => setExperimentPromptId(e.target.value)}>
              {prompts.map((prompt) => <option key={prompt.prompt_id} value={prompt.prompt_id}>{prompt.prompt_name}</option>)}
            </select>
            <label>Model</label>
            <select value={experimentModel} onChange={(e) => setExperimentModel(e.target.value)}>
              {models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}
            </select>
            <label>실행횟수</label>
            <input type="number" min={1} max={100} value={experimentCount} onChange={(e) => setExperimentCount(Number(e.target.value))} />
            <button disabled={loading || !experimentInputId || !experimentPromptId} onClick={handleRunExperiment}>
              실행
            </button>
            <div className="rca-progress-card">
              <div className="rca-progress-head">
                <strong>{experimentStatus}</strong>
                <span>{experimentProgress}%</span>
              </div>
              <div className="rca-progress-bar">
                <div style={{ width: `${experimentProgress}%` }} />
              </div>
              <small>{experimentProgressText}</small>
            </div>
          </div>
          <div className="rca-lab-panel wide">
            <h2>Experiment 이력</h2>
            <table className="rca-lab-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>INPUT</th>
                  <th>Prompt</th>
                  <th>Model</th>
                  <th>상태</th>
                  <th>Result</th>
                  <th>일시</th>
                </tr>
              </thead>
              <tbody>
                {experiments.map((experiment) => (
                  <tr key={experiment.step_id}>
                    <td>{experiment.experiment_id}</td>
                    <td>{experiment.input_name}</td>
                    <td>{experiment.prompt_name}</td>
                    <td>{experiment.model}</td>
                    <td>{experiment.status}</td>
                    <td>{experiment.result_id || '-'}</td>
                    <td>{formatDate(experiment.update_dt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {tab === 'results' && (
        <section className="rca-lab-grid">
          <div className="rca-lab-panel">
            <div className="rca-lab-panel-header">
              <h2>Result 비교</h2>
              <div className="rca-lab-inline-actions">
                <select value={compareInputId} onChange={(e) => setCompareInputId(e.target.value)}>
                  <option value="">전체 INPUT</option>
                  {inputs.map((input) => <option key={input.input_id} value={input.input_id}>{input.input_name}</option>)}
                </select>
                <select value={compareModel} onChange={(e) => setCompareModel(e.target.value)}>
                  <option value="">전체 MODEL</option>
                  {models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}
                </select>
                <button onClick={() => runAction(async () => {
                  const inputId = compareInputId ? Number(compareInputId) : undefined;
                  const model = compareModel || undefined;
                  setResults(await fetchRcaLabResults(inputId, model));
                  setPromptPerformance(await fetchRcaLabPromptPerformance(inputId, model));
                })}>조회</button>
              </div>
            </div>
            <h3>Prompt 성능 통계</h3>
            <table className="rca-lab-table compact">
              <thead>
                <tr>
                  <th>Prompt</th>
                  <th>실행</th>
                  <th>Total</th>
                  <th>Accuracy</th>
                  <th>Reasoning</th>
                  <th>Evidence</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {promptPerformance.map((prompt) => (
                  <tr key={prompt.prompt_id}>
                    <td>{prompt.prompt_name}</td>
                    <td>{prompt.execution_count}</td>
                    <td>{formatScore(prompt.average_score)}</td>
                    <td>{formatScore(prompt.accuracy_average)}</td>
                    <td>{formatScore(prompt.reasoning_average)}</td>
                    <td>{formatScore(prompt.evidence_average)}</td>
                    <td>{formatScore(prompt.actionability_average)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <h3>개별 Result</h3>
            <table className="rca-lab-table">
              <thead>
                <tr>
                  <th>Result</th>
                  <th>INPUT</th>
                  <th>Prompt</th>
                  <th>Model</th>
                  <th>평균</th>
                  <th>정확</th>
                  <th>근거</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {results.map((result) => (
                  <tr key={result.result_id}>
                    <td>{result.result_id}</td>
                    <td>{result.input_name}</td>
                    <td>{result.prompt_name}</td>
                    <td>{result.model || '-'}</td>
                    <td>{formatScore(result.score)}</td>
                    <td>{formatScore(result.accuracy_score)}</td>
                    <td>{formatScore(result.evidence_score)}</td>
                    <td><button onClick={() => handleShowResult(result.result_id)}>보기</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <pre className="rca-lab-preview">{selectedResult?.text || selectedResult?.result_preview || 'Result를 선택하세요.'}</pre>
        </section>
      )}

      {tab === 'meta' && (
        <section className="rca-lab-grid">
          <div className="rca-lab-panel">
            <h2>Prompt 분석</h2>
            <label>분석 대상 Prompt</label>
            <select value={metaPromptId} onChange={(e) => setMetaPromptId(e.target.value)}>
              {prompts.map((prompt) => <option key={prompt.prompt_id} value={prompt.prompt_id}>{prompt.prompt_name}</option>)}
            </select>
            <button disabled={loading || !metaPromptId} onClick={handleAnalyzePrompt}>Prompt 분석</button>

            {metaAnalysis && (
              <div className="rca-lab-analysis">
                {renderMetricGrid(metaAnalysis.stats)}
                <h3>강점</h3>
                <ul>{metaAnalysis.analysis.strengths.map((item) => <li key={item}>{item}</li>)}</ul>
                <h3>약점</h3>
                <ul>{metaAnalysis.analysis.weaknesses.map((item) => <li key={item}>{item}</li>)}</ul>
                <h3>자주 발생하는 문제</h3>
                <ul>{metaAnalysis.analysis.frequent_issues.map((item) => <li key={item}>{item}</li>)}</ul>
                <h3>개선 제안</h3>
                <ul>{metaAnalysis.improvement_proposal.items.map((item) => <li key={item}>{item}</li>)}</ul>
              </div>
            )}
          </div>

          <div className="rca-lab-panel">
            <h2>Prompt 차수 비교</h2>
            <label>비교 조건 INPUT</label>
            <select value={compareInputId} onChange={(e) => setCompareInputId(e.target.value)}>
              <option value="">전체 INPUT</option>
              {inputs.map((input) => <option key={input.input_id} value={input.input_id}>{input.input_name}</option>)}
            </select>
            <label>비교 조건 MODEL</label>
            <select value={compareModel} onChange={(e) => setCompareModel(e.target.value)}>
              <option value="">전체 MODEL</option>
              {models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}
            </select>
            <label>기준 Prompt</label>
            <select value={leftComparePromptId} onChange={(e) => setLeftComparePromptId(e.target.value)}>
              {prompts.map((prompt) => <option key={prompt.prompt_id} value={prompt.prompt_id}>{prompt.prompt_name}</option>)}
            </select>
            <label>비교 Prompt</label>
            <select value={rightComparePromptId} onChange={(e) => setRightComparePromptId(e.target.value)}>
              {prompts.map((prompt) => <option key={prompt.prompt_id} value={prompt.prompt_id}>{prompt.prompt_name}</option>)}
            </select>
            <button disabled={loading || !leftComparePromptId || !rightComparePromptId} onClick={handleComparePrompts}>Prompt 비교</button>

            {promptComparison && (
              <div className="rca-lab-analysis">
                <h3>변화 요약</h3>
                <p>{promptComparison.change_summary}</p>
                <table className="rca-lab-table compact">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th>{promptComparison.left.prompt_name}</th>
                      <th>{promptComparison.right.prompt_name}</th>
                      <th>Delta</th>
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ['Total Score', 'average_score', 'total_score'],
                      ['Accuracy', 'accuracy_average', 'accuracy'],
                      ['Reasoning', 'reasoning_average', 'reasoning'],
                      ['Evidence', 'evidence_average', 'evidence'],
                      ['Actionability', 'actionability_average', 'actionability'],
                    ].map(([label, statKey, deltaKey]) => (
                      <tr key={label}>
                        <td>{label}</td>
                        <td>{formatScore((promptComparison.left.stats as any)[statKey])}</td>
                        <td>{formatScore((promptComparison.right.stats as any)[statKey])}</td>
                        <td>{formatScore(promptComparison.deltas[deltaKey])}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      )}

      {tab === 'human' && (
        <section className="rca-lab-grid">
          <div className="rca-lab-panel wide">
            <h2>평가 화면</h2>
            <label>Result</label>
            <select
              value={selectedResult?.result_id || defaultResultId}
              onChange={(e) => handleShowResult(Number(e.target.value))}
            >
              {results.map((result) => <option key={result.result_id} value={result.result_id}>Result #{result.result_id} / {result.prompt_name}</option>)}
            </select>
            {!evaluationDetail && <div className="rca-lab-message">평가할 Result를 선택하세요.</div>}
            {evaluationDetail && (
              <div className="rca-evaluation">
                {renderEvaluationSection('input', 'INPUT', (
                  <>
                    <div className="rca-eval-meta">
                      <span>ID #{evaluationDetail.input.input_id}</span>
                      <span>{evaluationDetail.input.input_name}</span>
                      <span>{evaluationDetail.input.record_count?.toLocaleString() || '-'} records</span>
                    </div>
                    <h3>요약</h3>
                    <pre>{evaluationDetail.input.summary}</pre>
                    <h3>원문</h3>
                    <pre>{evaluationDetail.input.text}</pre>
                  </>
                ))}
                {renderEvaluationSection('prompt', 'PROMPT', (
                  <>
                    <div className="rca-eval-meta">
                      <span>{evaluationDetail.prompt.prompt_name}</span>
                      <span>{evaluationDetail.prompt.version}</span>
                    </div>
                    <pre>{evaluationDetail.prompt.text}</pre>
                  </>
                ))}
                {renderEvaluationSection('result', 'RESULT', (
                  <pre>{evaluationDetail.result.text}</pre>
                ))}
                {renderEvaluationSection('score', 'SCORE', (
                  <div className="rca-lab-metrics">
                    <div><span>Total</span><strong>{formatScore(evaluationDetail.score.total_score)}</strong></div>
                    <div><span>Accuracy</span><strong>{formatScore(evaluationDetail.score.accuracy_score)}</strong></div>
                    <div><span>Reasoning</span><strong>{formatScore(evaluationDetail.score.reasoning_score)}</strong></div>
                    <div><span>Evidence</span><strong>{formatScore(evaluationDetail.score.evidence_score)}</strong></div>
                    <div><span>Actionability</span><strong>{formatScore(evaluationDetail.score.actionability_score)}</strong></div>
                  </div>
                ))}
                {renderEvaluationSection('comment', 'COMMENT', (
                  <div className="rca-eval-comments">
                    <p><strong>Accuracy</strong>{evaluationDetail.comment.accuracy_comment || '-'}</p>
                    <p><strong>Reasoning</strong>{evaluationDetail.comment.reasoning_comment || '-'}</p>
                    <p><strong>Evidence</strong>{evaluationDetail.comment.evidence_comment || '-'}</p>
                    <p><strong>Actionability</strong>{evaluationDetail.comment.actionability_comment || '-'}</p>
                    <p><strong>Overall</strong>{evaluationDetail.comment.evaluation_comment || '-'}</p>
                  </div>
                ))}
                {renderEvaluationSection('judges', 'JUDGE 비교', (
                  <table className="rca-lab-table compact">
                    <thead>
                      <tr>
                        <th>Type</th>
                        <th>Status</th>
                        <th>Total</th>
                        <th>Accuracy</th>
                        <th>Reasoning</th>
                        <th>Evidence</th>
                        <th>Action</th>
                        <th>Comment</th>
                      </tr>
                    </thead>
                    <tbody>
                      {evaluationDetail.judges.map((judge) => (
                        <tr key={judge.judge_id}>
                          <td>{judge.judge_type}</td>
                          <td>{judge.status}</td>
                          <td>{formatScore(judge.total_score)}</td>
                          <td>{formatScore(judge.accuracy_score)}</td>
                          <td>{formatScore(judge.reasoning_score)}</td>
                          <td>{formatScore(judge.evidence_score)}</td>
                          <td>{formatScore(judge.actionability_score)}</td>
                          <td>{judge.judge_comment || '-'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ))}
              </div>
            )}
          </div>
          <div className="rca-lab-panel">
            <h2>Human Override</h2>
            <p className="rca-lab-help">AI Judge 이후 사람이 추가로 남기는 평가입니다. LOCAL/GPT/CLAUDE/GEMINI/HUMAN Judge 비교 구조에 함께 저장됩니다.</p>
            <label>평가</label>
            <div className="rca-lab-rating">
              {['GOOD', 'NORMAL', 'BAD'].map((rating) => (
                <button key={rating} className={humanRating === rating ? 'active' : ''} onClick={() => setHumanRating(rating)}>
                  {rating}
                </button>
              ))}
            </div>
            <label>Comment</label>
            <textarea className="rca-lab-textarea small" value={humanComment} onChange={(e) => setHumanComment(e.target.value)} />
            <button disabled={loading || results.length === 0} onClick={handleHumanSave}>Human Override 저장</button>
          </div>
        </section>
      )}
    </div>
  );
}
