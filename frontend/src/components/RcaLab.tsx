import React, { useEffect, useMemo, useState } from 'react';
import {
  createRcaLabHumanEvaluation,
  createRcaLabPrompt,
  deleteRcaLabInput,
  deleteRcaLabPrompt,
  fetchRcaLabExperiments,
  fetchRcaLabInput,
  fetchRcaLabInputs,
  fetchRcaLabPrompt,
  fetchRcaLabPrompts,
  fetchRcaLabResult,
  fetchRcaLabResults,
  importRcaLabFile,
  importRcaLabSample,
  RcaLabExperiment,
  RcaLabInput,
  RcaLabPrompt,
  RcaLabResult,
  runRcaLabExperiment,
  updateRcaLabPrompt,
} from '../api';

type Tab = 'inputs' | 'prompts' | 'experiments' | 'results' | 'human';

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
  const [selectedInput, setSelectedInput] = useState<RcaLabInput | null>(null);
  const [selectedPrompt, setSelectedPrompt] = useState<RcaLabPrompt | null>(null);
  const [selectedResult, setSelectedResult] = useState<RcaLabResult | null>(null);
  const [promptText, setPromptText] = useState('');
  const [experimentInputId, setExperimentInputId] = useState('');
  const [experimentPromptId, setExperimentPromptId] = useState('');
  const [experimentModel, setExperimentModel] = useState(selectedModel);
  const [experimentCount, setExperimentCount] = useState(1);
  const [compareInputId, setCompareInputId] = useState('');
  const [inputChunkSize, setInputChunkSize] = useState(10000);
  const [humanRating, setHumanRating] = useState('GOOD');
  const [humanComment, setHumanComment] = useState('');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');

  const defaultResultId = useMemo(() => results[0]?.result_id || '', [results]);

  const refreshAll = async () => {
    const [nextInputs, nextPrompts, nextExperiments, nextResults] = await Promise.all([
      fetchRcaLabInputs(),
      fetchRcaLabPrompts(),
      fetchRcaLabExperiments(),
      fetchRcaLabResults(compareInputId ? Number(compareInputId) : undefined),
    ]);
    setInputs(nextInputs);
    setPrompts(nextPrompts);
    setExperiments(nextExperiments);
    setResults(nextResults);
    if (!experimentInputId && nextInputs[0]) setExperimentInputId(String(nextInputs[0].input_id));
    if (!experimentPromptId && nextPrompts[0]) setExperimentPromptId(String(nextPrompts[0].prompt_id));
  };

  useEffect(() => {
    refreshAll().catch((err) => setMessage(err.message || 'RCA Lab 로딩 실패'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setExperimentModel(selectedModel);
  }, [selectedModel]);

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
    const detail = await fetchRcaLabPrompt(id);
    setSelectedPrompt(detail);
    setPromptText(detail.text || '');
  };

  const handleShowResult = async (id: number) => {
    const detail = await fetchRcaLabResult(id);
    setSelectedResult(detail);
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
    await runAction(async () => {
      await runRcaLabExperiment(
        Number(experimentInputId),
        Number(experimentPromptId),
        experimentModel,
        experimentCount,
      );
      setMessage('Experiment 실행이 완료되었습니다.');
    });
  };

  const handleHumanSave = async () => {
    const resultId = selectedResult?.result_id || Number(defaultResultId);
    if (!resultId) {
      setMessage('평가할 Result를 선택하세요.');
      return;
    }
    await runAction(async () => {
      await createRcaLabHumanEvaluation(resultId, humanRating, humanComment);
      setHumanComment('');
      setMessage('Human 평가를 저장했습니다.');
    });
  };

  return (
    <div className="rca-lab">
      <div className="rca-lab-tabs">
        {[
          ['inputs', 'INPUT 관리'],
          ['prompts', 'Prompt 관리'],
          ['experiments', 'Experiment 실행'],
          ['results', 'Result 비교'],
          ['human', 'Human 평가'],
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
                    <td className="rca-lab-actions">
                      <button onClick={() => handleShowPrompt(prompt.prompt_id)}>열기</button>
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
              {selectedPrompt && <button onClick={() => { setSelectedPrompt(null); setPromptText(''); }}>새 Prompt</button>}
            </div>
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
              <select value={compareInputId} onChange={(e) => setCompareInputId(e.target.value)}>
                <option value="">전체 INPUT</option>
                {inputs.map((input) => <option key={input.input_id} value={input.input_id}>{input.input_name}</option>)}
              </select>
              <button onClick={() => runAction(async () => { setResults(await fetchRcaLabResults(compareInputId ? Number(compareInputId) : undefined)); })}>조회</button>
            </div>
            <table className="rca-lab-table">
              <thead>
                <tr>
                  <th>Result</th>
                  <th>INPUT</th>
                  <th>Prompt</th>
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

      {tab === 'human' && (
        <section className="rca-lab-grid">
          <div className="rca-lab-panel">
            <h2>Human 평가</h2>
            <label>Result</label>
            <select
              value={selectedResult?.result_id || defaultResultId}
              onChange={(e) => handleShowResult(Number(e.target.value))}
            >
              {results.map((result) => <option key={result.result_id} value={result.result_id}>Result #{result.result_id} / {result.prompt_name}</option>)}
            </select>
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
            <button disabled={loading || results.length === 0} onClick={handleHumanSave}>평가 저장</button>
          </div>
          <pre className="rca-lab-preview">{selectedResult?.text || '평가할 Result를 선택하세요.'}</pre>
        </section>
      )}
    </div>
  );
}
