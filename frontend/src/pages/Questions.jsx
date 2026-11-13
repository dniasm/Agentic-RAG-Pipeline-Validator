import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { api } from '../lib/api.js';
import { ErrorNote } from '../components/ui.jsx';

export function Rubric({ expected }) {
  if (!expected) return <div className="text-small text-negative">No rubric for this question.</div>;
  const groups = [
    ['Must include', expected.must_include, 'M'],
    ['Should include', expected.should_include, 'S'],
    ['Must not include', expected.must_not_include, 'N'],
  ];
  return (
    <div className="space-y-3 text-body">
      <div className="text-small">
        {expected.answerable === false
          ? <span className="pill-warning">Not answerable from the corpus</span>
          : <span className="pill-neutral">Answerable from the corpus</span>}
      </div>
      {groups.filter(([, items]) => items?.length).map(([title, items, prefix]) => (
        <div key={title}>
          <div className="text-small text-muted mb-1">{title}</div>
          <ul className="space-y-1">
            {items.map((t, i) => (
              <li key={i} className="flex gap-2"><span className="font-mono text-small text-muted w-7 flex-none">{prefix}{i + 1}</span>{t}</li>
            ))}
          </ul>
        </div>
      ))}
      {expected.notes && <div className="text-small text-muted">Grader notes: {expected.notes}</div>}
    </div>
  );
}

export default function Questions() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState({});
  const [filter, setFilter] = useState('all');
  useEffect(() => { api.questions().then(setData).catch(setError); }, []);

  if (error) return <ErrorNote error={error} />;
  if (!data) return <div className="skeleton h-40" />;
  const types = ['all', ...new Set(data.questions.map((q) => q.type || 'untyped'))];
  const shown = data.questions.filter((q) => filter === 'all' || (q.type || 'untyped') === filter);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-title font-medium">Question set</h1>
        <p className="text-muted mt-1 max-w-[720px]">
          <code className="font-mono text-small">data/questions.json</code> and its complementary
          {' '}<code className="font-mono text-small">data/expected.json</code>. The rubric lists the hints and
          concepts a good answer should contain, not the answer itself. The base agent never sees it; the judges do.
        </p>
      </header>
      {data.problems.length > 0 && <ErrorNote error={data.problems.join(' · ')} />}
      <div className="flex gap-2 flex-wrap">
        {types.map((t) => (
          <button key={t} className={filter === t ? 'btn-primary h-8' : 'btn-secondary h-8'} onClick={() => setFilter(t)}>
            {t} {t !== 'all' && <span className="num opacity-70">{data.questions.filter((q) => (q.type || 'untyped') === t).length}</span>}
          </button>
        ))}
      </div>
      <div className="panel divide-y divide-[color:var(--rule)]">
        {shown.map((q) => (
          <div key={q.id}>
            <button className="w-full text-left px-4 py-3 flex gap-3 items-start hover:bg-raised"
                    onClick={() => setOpen({ ...open, [q.id]: !open[q.id] })} aria-expanded={!!open[q.id]}>
              {open[q.id] ? <ChevronDown size={16} className="mt-0.5" /> : <ChevronRight size={16} className="mt-0.5" />}
              <span className="font-mono text-small text-muted w-10 flex-none mt-0.5">{q.id}</span>
              <span className="flex-1">{q.question}</span>
              <span className="pill-neutral">{q.type || 'untyped'}</span>
            </button>
            {open[q.id] && (
              <div className="px-4 pb-4 pl-[76px] space-y-3">
                <Rubric expected={q.expected} />
                {(q.expected?.source_files || q.source_files)?.length > 0 && (
                  <div className="text-small text-muted">
                    Source file(s), used only for retrieval metrics and never shown to the base agent or judges: {(q.expected?.source_files || q.source_files).join(', ')}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
        {!shown.length && <div className="px-4 py-6 text-center text-muted">No questions yet.</div>}
      </div>
    </div>
  );
}
