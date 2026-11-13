import { useEffect, useState } from 'react';
import { Play, RotateCcw, Square } from 'lucide-react';
import { api } from '../lib/api.js';
import { go } from '../App.jsx';
import { ErrorNote, ProgressBar, Section } from '../components/ui.jsx';

const LANE = { base: 'Base agent (answers)', small: 'Smaller judge', large: 'Larger judge' };
const STATE = { running: 'pill-positive', waiting: 'pill-warning', done: 'pill-neutral', stopped: 'pill-neutral',
                error: 'pill-negative', idle: 'pill-neutral' };

function until(iso) {
  if (!iso) return '';
  const s = Math.max(0, Math.round((new Date(iso) - Date.now()) / 1000));
  return s > 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : s > 60 ? `${Math.floor(s / 60)}m ${s % 60}s` : `${s}s`;
}

export default function Runs({ arg }) {
  const [overview, setOverview] = useState(null);
  const [run, setRun] = useState(null);
  const [error, setError] = useState(null);
  const [limit, setLimit] = useState('');
  const cases = overview?.cases || [];
  const caseKey = arg || cases[0]?.key;
  const info = cases.find((c) => c.key === caseKey);

  useEffect(() => { api.overview().then(setOverview).catch(setError); }, []);
  useEffect(() => {
    if (!caseKey) return undefined;
    const load = () => api.run(caseKey).then(setRun).catch(setError);
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [caseKey]);

  const act = async (fn) => {
    setError(null);
    try { await fn(); setRun(await api.run(caseKey)); setOverview(await api.overview()); } catch (e) { setError(e); }
  };
  const reset = (target, what) => {
    if (window.confirm(`Delete ${what} for ${info.label}? They will be regenerated on the next run.`)) {
      act(() => api.reset(caseKey, target));
    }
  };

  if (!overview) return error ? <ErrorNote error={error} /> : <div className="skeleton h-40" />;
  const active = run?.active;
  const n = overview.questions;

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-title font-medium">Runs</h1>
          <p className="text-muted mt-1 max-w-[720px]">
            The three lanes run in parallel. Each saves after every question, waits out rate limits (including the daily
            reset), and resumes where it stopped. The base agent answers each question once, and both cases' judges grade those same answers. Case 2 runs first, then Case 1.
          </p>
        </div>
        <div className="flex gap-1 panel p-1">
          {cases.map((c) => (
            <button key={c.key} onClick={() => go('runs', c.key)}
                    className={c.key === caseKey ? 'btn-primary h-8' : 'btn-ghost h-8'}>{c.label.split(':')[0]}</button>
          ))}
        </div>
      </header>
      <ErrorNote error={error} />

      {info && (
        <Section title={info.label} actions={
          <div className="flex items-center gap-2 host-only">
            <label className="text-small text-muted flex items-center gap-2">
              First
              <input className="input h-9 w-16 num" value={limit} placeholder="all" inputMode="numeric"
                     onChange={(e) => setLimit(e.target.value.replace(/\D/g, ''))} disabled={active} />
              questions
            </label>
            {active
              ? <button className="btn-danger" onClick={() => act(() => api.stop(caseKey))}><Square size={14} /> Stop</button>
              : <button className="btn-primary" disabled={!n}
                        onClick={() => act(() => api.start(caseKey, limit ? Number(limit) : null))}>
                  <Play size={14} /> {info.progress.generated ? 'Resume' : 'Start'}
                </button>}
          </div>
        }>
          <div className="grid md:grid-cols-3 gap-4">
            {['base', 'small', 'large'].map((k) => {
              const lane = run?.lanes?.[k];
              const model = { base: info.base, small: info.small_judge, large: info.large_judge }[k];
              const saved = { base: info.progress.generated, small: info.progress.judge_small, large: info.progress.judge_large }[k];
              const done = lane ? lane.done : saved;
              const total = lane ? lane.total : n;
              return (
                <div key={k} className="panel p-4 space-y-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-small text-muted">{LANE[k]}</div>
                      <div className="font-medium truncate">{model.label}</div>
                    </div>
                    <span className={STATE[lane?.state || 'idle']}>{lane?.state || 'idle'}</span>
                  </div>
                  <ProgressBar done={done} total={total} />
                  <div className="flex justify-between text-small">
                    <span className="num">{done}/{total} done</span>
                    {lane?.errors > 0 && <span className="text-negative num">{lane.errors} failed</span>}
                  </div>
                  <div className="text-small text-muted min-h-[32px]">
                    {lane?.state === 'waiting' ? `${lane.message} (${until(lane.wait_until)} left)`
                      : lane?.current ? `Working on ${lane.current}` : lane?.message || ''}
                  </div>
                </div>
              );
            })}
          </div>
        </Section>
      )}

      <Section title="Log">
        <pre className="panel p-3 font-mono text-small whitespace-pre-wrap h-72 overflow-y-auto">
          {run?.log?.length ? run.log.join('\n') : 'No run in this session yet.'}
        </pre>
      </Section>

      {info && (
        <div className="host-only"><Section title="Redo results">
          <div className="flex gap-2 flex-wrap">
            <button className="btn-secondary" disabled={active} onClick={() => reset('judge_small', 'the smaller judge\'s results')}>
              <RotateCcw size={14} /> Smaller judge</button>
            <button className="btn-secondary" disabled={active} onClick={() => reset('judge_large', 'the larger judge\'s results')}>
              <RotateCcw size={14} /> Larger judge</button>
            <button className="btn-danger" disabled={active} onClick={() => reset('all', "the answers (shared by BOTH cases) and this case's judge results")}>
              <RotateCcw size={14} /> Everything</button>
          </div>
          <p className="text-small text-muted">Human verdicts are never deleted here. The answers are shared by both cases,
            so deleting them makes every judge regrade.</p>
        </Section></div>
      )}
    </div>
  );
}
