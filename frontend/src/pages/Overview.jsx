import { useEffect, useState } from 'react';
import { ArrowRight, Check, X } from 'lucide-react';
import { api } from '../lib/api.js';
import { ErrorNote, ProgressBar, Section } from '../components/ui.jsx';

const PROVIDER = { groq: 'Groq', google: 'Google AI Studio', nvidia: 'NVIDIA', openrouter: 'OpenRouter' };

function Role({ title, model, note }) {
  return (
    <div className="min-w-0">
      <div className="text-small text-muted">{title}</div>
      <div className="font-medium truncate">{model.label}</div>
      <div className="text-small text-muted">{PROVIDER[model.provider]}{note ? ` · ${note}` : ''}</div>
    </div>
  );
}

export default function Overview() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    const load = () => api.overview().then(setData).catch(setError);
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <div className="skeleton h-40" />;
  const n = data.questions;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-title font-medium">Agentic-RAG Pipeline Validator</h1>
        <p className="text-muted mt-1 max-w-[720px]">
          The base agent answers a fixed question set from the ingested corpus using day7's ingestion and RAG
          pipeline. Two judges then grade each answer against an abstract rubric of expected concepts. Each judge
          searches the corpus on its own. A human checker makes the final call.
        </p>
      </header>

      <Section title="Flow">
        <ol className="panel p-4 grid grid-cols-1 md:grid-cols-5 gap-4 text-body">
          {[
            ['1. Corpus', 'Ingested with day7 (chunk → Gemini embed → Qdrant hybrid)'],
            ['2. Question set', 'questions.json + expected.json (hints and concepts only)'],
            ['3. Base agent', 'Search → rerank → MMR → answer with citations'],
            ['4. Two judges', 'Each searches the corpus itself and grades every rubric point'],
            ['5. Human checker', 'Reviews both judges and gives the final verdict'],
          ].map(([t, d]) => (
            <li key={t}><div className="font-medium">{t}</div><div className="text-small text-muted mt-1">{d}</div></li>
          ))}
        </ol>
      </Section>

      <Section title="Test cases">
        <div className="grid md:grid-cols-2 gap-4">
          {data.cases.map((c) => (
            <div key={c.key} className="panel p-4 space-y-4">
              <div className="flex items-center justify-between">
                <div className="font-medium">{c.label}</div>
                <span className={c.running ? 'pill-positive' : 'pill-neutral'}>
                  {c.running ? 'Running' : `Runs ${c.order === 1 ? 'first' : 'second'}`}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <Role title="Smaller judge" model={c.small_judge} />
                <Role title="Base (answers)" model={c.base} />
                <Role title="Larger judge" model={c.large_judge} />
              </div>
              <div className="space-y-2">
                {[['Answers (shared)', 'generated'], ['Smaller judge', 'judge_small'], ['Larger judge', 'judge_large'],
                  ['Human review', 'human']].map(([label, key]) => (
                  <div key={key} className="grid grid-cols-[110px_1fr_56px] items-center gap-3 text-small">
                    <span className="text-muted">{label}</span>
                    <ProgressBar done={c.progress[key]} total={n} />
                    <span className="num text-right">{c.progress[key]}/{n}</span>
                  </div>
                ))}
              </div>
              <div className="flex gap-2">
                <a className="btn-secondary" href={`#/runs/${c.key}`}>Run</a>
                <a className="btn-secondary" href={`#/review/${c.key}`}>Review</a>
                <a className="btn-ghost" href={`#/metrics/${c.key}`}>Metrics <ArrowRight size={14} /></a>
              </div>
            </div>
          ))}
        </div>
      </Section>

      <div className="grid md:grid-cols-2 gap-4">
        <Section title="Question set">
          <div className="panel p-4 space-y-2">
            <div><span className="num font-medium">{n}</span> questions</div>
            {data.question_problems.length ? (
              <ul className="text-small text-negative list-disc pl-5">
                {data.question_problems.slice(0, 6).map((p) => <li key={p}>{p}</li>)}
              </ul>
            ) : <div className="text-small text-muted">Every question has a rubric.</div>}
          </div>
        </Section>
        <Section title="API keys">
          <div className="panel p-4 grid grid-cols-2 gap-2 text-body">
            {Object.entries(data.keys).map(([k, ok]) => (
              <div key={k} className="flex items-center gap-2">
                {ok ? <Check size={14} className="text-positive" /> : <X size={14} className="text-negative" />}
                <span className="capitalize">{k}</span>
                <span className="text-small text-muted">{ok ? 'set' : 'missing'}</span>
              </div>
            ))}
          </div>
        </Section>
      </div>
    </div>
  );
}
