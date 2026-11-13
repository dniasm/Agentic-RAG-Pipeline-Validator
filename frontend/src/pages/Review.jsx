import { useEffect, useMemo, useState } from 'react';
import { ChevronDown, ChevronRight, Download } from 'lucide-react';
import { api } from '../lib/api.js';
import { go } from '../App.jsx';
import { ErrorNote, Markdown, PointStatus, Verdict } from '../components/ui.jsx';
import { Rubric } from './Questions.jsx';

function Disclosure({ title, children, initiallyOpen = false }) {
  const [open, setOpen] = useState(initiallyOpen);
  return (
    <div>
      <button className="link-action text-small text-muted" onClick={() => setOpen(!open)} aria-expanded={open}>
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />} {title}
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}

function JudgeCard({ title, label, result }) {
  if (!result) return <div className="panel p-4"><div className="text-small text-muted">{title}</div><div className="font-medium">{label}</div><div className="mt-3"><Verdict /></div></div>;
  if (result.error) return <div className="panel p-4 space-y-2"><div className="font-medium">{label}</div><Verdict error={result.error} /><div className="text-small text-negative break-words">{result.error}</div></div>;
  const fallback = result.calls?.find((c) => c.model !== result.judge);
  return (
    <div className="panel p-4 space-y-4 min-w-0">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0"><div className="text-small text-muted">{title}</div><div className="font-medium truncate">{label}</div></div>
        <div className="flex items-center gap-2"><span className="num text-small text-muted">{result.score}/10</span><Verdict value={result.verdict} /></div>
      </div>
      {fallback && <div className="pill-warning">Answered by fallback {fallback.model}</div>}
      <p className="text-body">{result.reason}</p>
      <div className="space-y-1.5">
        {result.rubric.map((p) => (
          <div key={p.id} className="flex gap-2 items-start text-body">
            <span className="font-mono text-small text-muted w-7 flex-none mt-0.5">{p.id}</span>
            <PointStatus status={p.status} />
            <span className="flex-1 min-w-0">{p.text}{p.note && <span className="block text-small text-muted">{p.note}</span>}</span>
          </div>
        ))}
        {result.ungraded_points?.length > 0 && (
          <div className="text-small text-warning">Not graded: {result.ungraded_points.join(', ')}</div>
        )}
      </div>
      <div className="text-small space-y-1">
        <div><span className="text-muted">Grounding:</span> {result.grounding.replace('_', ' ')} · <span className="text-muted">Confidence:</span> {result.confidence}</div>
        {result.unsupported_claims?.length > 0 && <div><span className="text-muted">Unsupported:</span> {result.unsupported_claims.join(' · ')}</div>}
        {result.contradicted_by_corpus?.length > 0 && <div className="text-negative"><span>Contradicted by corpus:</span> {result.contradicted_by_corpus.join(' · ')}</div>}
      </div>
      <Disclosure title={`Its searches (${result.queries.length}) and ${result.passages.length} passages found`}>
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1">{result.queries.map((q) => <span key={q} className="pill-neutral">{q}</span>)}</div>
          {result.passages.map((p, i) => (
            <div key={p.id} className="border-l-2 border-control pl-3 text-small">
              <div className="text-muted">[S{i + 1}] {p.source}</div>
              <div className="whitespace-pre-wrap">{p.content}</div>
            </div>
          ))}
        </div>
      </Disclosure>
      <div className="text-small text-muted num">
        {result.calls?.length} calls · {result.calls?.reduce((s, c) => s + c.input + c.output, 0).toLocaleString()} tokens · {result.latency_s}s
      </div>
    </div>
  );
}

function HumanForm({ caseKey, qid, human, onSaved }) {
  const [note, setNote] = useState(human?.note || '');
  const [agrees, setAgrees] = useState(human?.agrees_with || null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => { setNote(human?.note || ''); setAgrees(human?.agrees_with || null); }, [qid, human]);
  const save = async (verdict) => {
    setBusy(true); setError(null);
    try { await api.setHuman(caseKey, qid, { verdict, note, agrees_with: agrees }); onSaved(); } catch (e) { setError(e); } finally { setBusy(false); }
  };
  const agreedLabel = { small: 'the smaller judge', large: 'the larger judge', both: 'both judges', neither: 'neither judge' };
  return (
    <div className="panel p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium">Human checker: final verdict</div>
        {human && <Verdict value={human.verdict} />}
      </div>
      {human ? (
        <div className="rounded-control border border-line bg-raised p-3 space-y-2">
          <div className="flex items-center gap-2 flex-wrap text-small text-muted">
            <span className="font-medium text-ink">Submitted review</span>
            <span>·</span>
            <span>{human.reviewer || 'Human checker'}</span>
            {human.at && <><span>·</span><span>{new Date(human.at).toLocaleString()}</span></>}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Verdict value={human.verdict} />
            {human.agrees_with && <span className="text-small">Agrees with {agreedLabel[human.agrees_with]}</span>}
          </div>
          <p className="text-body whitespace-pre-wrap">{human.note || <span className="text-muted">No note.</span>}</p>
        </div>
      ) : (
        <p className="text-small text-muted">Not reviewed yet.</p>
      )}
      <div className="text-small font-medium pt-1">{human ? 'Change the review' : 'Give the review'}</div>
      <div>
        <div className="text-small text-muted mb-1">Which judge got it right?</div>
        <div className="flex gap-1 flex-wrap">
          {[['small', 'Smaller'], ['large', 'Larger'], ['both', 'Both'], ['neither', 'Neither']].map(([k, l]) => (
            <button key={k} className={agrees === k ? 'btn-primary h-8' : 'btn-secondary h-8'} onClick={() => setAgrees(agrees === k ? null : k)}>{l}</button>
          ))}
        </div>
      </div>
      <textarea className="input h-28 py-2" placeholder="Note (optional): why, what the judges missed…" value={note} onChange={(e) => setNote(e.target.value)} />
      <ErrorNote error={error} />
      <div className="flex gap-2">
        <button className="btn-secondary" disabled={busy} onClick={() => save('pass')}>Pass</button>
        <button className="btn-secondary" disabled={busy} onClick={() => save('partial')}>Partial</button>
        <button className="btn-secondary" disabled={busy} onClick={() => save('fail')}>Fail</button>
        {human && <button className="btn-ghost text-muted" disabled={busy} onClick={async () => { await api.clearHuman(caseKey, qid); onSaved(); }}>Clear</button>}
      </div>
    </div>
  );
}

export default function Review({ arg }) {
  const [overview, setOverview] = useState(null);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [filter, setFilter] = useState('all');
  const caseKey = arg || overview?.cases[0]?.key;

  useEffect(() => { api.overview().then(setOverview).catch(setError); }, []);
  const load = () => caseKey && api.results(caseKey).then(setData).catch(setError);
  useEffect(() => { setData(null); setSelected(null); load(); }, [caseKey]);

  const items = data?.items || [];
  const shown = useMemo(() => items.filter((it) => {
    const s = it.small?.verdict, l = it.large?.verdict;
    if (filter === 'disagree') return s && l && s !== l;
    if (filter === 'unreviewed') return s && l && !it.human;
    if (filter === 'reviewed') return !!it.human;
    return true;
  }), [items, filter]);
  const current = items.find((it) => it.question.id === selected) || shown[0];

  if (error) return <ErrorNote error={error} />;
  if (!data || !overview) return <div className="skeleton h-40" />;
  const c = data.case;
  const counts = {
    disagree: items.filter((it) => it.small?.verdict && it.large?.verdict && it.small.verdict !== it.large.verdict).length,
    unreviewed: items.filter((it) => it.small?.verdict && it.large?.verdict && !it.human).length,
    reviewed: items.filter((it) => it.human).length,
  };

  return (
    <div className="space-y-6">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-title font-medium">Review</h1>
          <p className="text-muted mt-1">Compare both judges on each answer and give the final verdict.</p>
        </div>
        <div className="flex gap-2 items-center">
          <a className="btn-ghost" href={`/api/export/${caseKey}.csv`}><Download size={14} /> CSV</a>
          <div className="flex gap-1 panel p-1">
            {overview.cases.map((x) => (
              <button key={x.key} onClick={() => go('review', x.key)} className={x.key === caseKey ? 'btn-primary h-8' : 'btn-ghost h-8'}>{x.label.split(':')[0]}</button>
            ))}
          </div>
        </div>
      </header>

      <div className="grid grid-cols-[300px_1fr] gap-6 items-start">
        <div className="panel overflow-hidden sticky top-4">
          <div className="p-2 border-b border-line flex gap-1 flex-wrap">
            {[['all', `All ${items.length}`], ['disagree', `Disagree ${counts.disagree}`], ['unreviewed', `To review ${counts.unreviewed}`], ['reviewed', `Reviewed ${counts.reviewed}`]].map(([k, l]) => (
              <button key={k} className={filter === k ? 'btn-primary h-7 px-2 text-small' : 'btn-ghost h-7 px-2 text-small'} onClick={() => setFilter(k)}>{l}</button>
            ))}
          </div>
          <div className="max-h-[70vh] overflow-y-auto divide-y divide-[color:var(--rule)]">
            {shown.map((it) => {
              const q = it.question;
              const disagree = it.small?.verdict && it.large?.verdict && it.small.verdict !== it.large.verdict;
              return (
                <button key={q.id} onClick={() => setSelected(q.id)}
                        className={`w-full text-left px-3 py-2 hover:bg-raised ${current?.question.id === q.id ? 'bg-active' : ''}`}>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-small text-muted">{q.id}</span>
                    {disagree && <span className="pill-warning h-[18px] text-[11px]">disagree</span>}
                    {it.human && <span className="ml-auto"><Verdict value={it.human.verdict} /></span>}
                  </div>
                  <div className="text-small truncate mt-0.5">{q.question}</div>
                  <div className="flex gap-1 mt-1 text-[11px] text-muted items-center">
                    S <Verdict value={it.small?.verdict} error={it.small?.error} /> L <Verdict value={it.large?.verdict} error={it.large?.error} />
                  </div>
                </button>
              );
            })}
            {!shown.length && <div className="p-4 text-small text-muted">Nothing here.</div>}
          </div>
        </div>

        {current ? (
          <div className="space-y-4 min-w-0">
            <div className="panel p-4 space-y-3">
              <div className="flex gap-2 items-center"><span className="font-mono text-small text-muted">{current.question.id}</span><span className="pill-neutral">{current.question.type || 'untyped'}</span></div>
              <div className="text-section font-medium">{current.question.question}</div>
              <Disclosure title="Expected (rubric)" initiallyOpen><Rubric expected={current.expected} /></Disclosure>
            </div>

            <div className="panel p-4 space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div><div className="text-small text-muted">Generated answer</div><div className="font-medium">{c.base.label}</div></div>
                {current.generated && !current.generated.error && (
                  <div className="flex gap-2 text-small">
                    <span className="pill-neutral">{current.generated.retrieval?.zone} match</span>
                    {current.generated.citations && <span className={current.generated.citations.ok ? 'pill-positive' : 'pill-warning'}>citations {current.generated.citations.ok ? 'check out' : 'flagged'}</span>}
                  </div>
                )}
              </div>
              {!current.generated ? <div className="text-muted">Not answered yet.</div>
                : current.generated.error ? <ErrorNote error={current.generated.error} />
                : <>
                    <Markdown>{current.generated.answer}</Markdown>
                    {current.generated.citations?.problems?.length > 0 && <div className="text-small text-warning">Citation check: {current.generated.citations.problems.join('; ')}</div>}
                    <Disclosure title={`Passages the base agent used (${current.generated.passages.length}). The judges never see these.`}>
                      <div className="space-y-2">
                        {current.generated.passages.map((p) => (
                          <div key={p.n} className="border-l-2 border-[color:var(--hue)] pl-3 text-small">
                            <div className="text-muted">[{p.n}] {p.source} · relevance {p.relevance ?? '—'}</div>
                            <div className="whitespace-pre-wrap">{p.content}</div>
                          </div>
                        ))}
                      </div>
                    </Disclosure>
                  </>}
            </div>

            <div className="grid md:grid-cols-2 gap-4 items-start">
              <JudgeCard title="Smaller judge" label={c.small_judge.label} result={current.small} />
              <JudgeCard title="Larger judge" label={c.large_judge.label} result={current.large} />
            </div>

            <HumanForm caseKey={caseKey} qid={current.question.id} human={current.human} onSaved={load} />
          </div>
        ) : <div className="panel p-6 text-muted">No questions to show.</div>}
      </div>
    </div>
  );
}
