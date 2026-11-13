import { useEffect, useState } from 'react';
import { Download } from 'lucide-react';
import { api, compact, num, pct } from '../lib/api.js';
import { go } from '../App.jsx';
import { ErrorNote, Section, StatTile, VerdictBar, VerdictLegend } from '../components/ui.jsx';

const LABELS = ['pass', 'partial', 'fail'];

// Agreement as a confusion table. One hue, light -> dark by count (sequential); the number is always printed.
function Confusion({ table, rowLabel, colLabel }) {
  if (!table) return <div className="text-small text-muted">Nothing to compare yet.</div>;
  const max = Math.max(1, ...LABELS.flatMap((r) => LABELS.map((c) => table[r][c])));
  return (
    <table className="text-body border-separate" style={{ borderSpacing: 2 }}>
      <thead>
        <tr><th className="text-small text-muted font-normal text-left pr-2">{rowLabel} ↓ / {colLabel} →</th>
          {LABELS.map((c) => <th key={c} className="text-small text-muted font-normal w-16 capitalize">{c}</th>)}</tr>
      </thead>
      <tbody>
        {LABELS.map((r) => (
          <tr key={r}>
            <th className="text-small text-muted font-normal text-left pr-2 capitalize">{r}</th>
            {LABELS.map((c) => {
              const v = table[r][c];
              const share = v / max;
              return (
                <td key={c} className="h-10 w-16 text-center num rounded-[4px]" title={`${rowLabel} ${r}, ${colLabel} ${c}: ${v}`}
                    style={{ background: v ? `color-mix(in srgb, var(--hue) ${Math.round(15 + share * 70)}%, var(--surface))` : 'var(--raised)',
                             color: share > 0.55 ? '#ffffff' : 'var(--text)', outline: r === c ? '1px solid var(--control)' : 'none' }}>
                  {v}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Agreement({ a, title }) {
  if (!a) return null;
  return (
    <div className="panel p-4 space-y-4">
      <div className="font-medium">{title}</div>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 text-body">
        <div><div className="text-small text-muted">Same verdict</div><div className="num font-medium">{pct(a.verdict_agreement)}</div></div>
        <div><div className="text-small text-muted">Cohen's kappa</div><div className="num font-medium">{num(a.cohen_kappa)}</div></div>
        <div><div className="text-small text-muted">Weighted kappa</div><div className="num font-medium">{num(a.weighted_kappa)}</div></div>
        <div><div className="text-small text-muted">Rubric points agreed</div><div className="num font-medium">{pct(a.rubric_point_agreement)}</div></div>
        <div><div className="text-small text-muted">Score correlation</div><div className="num font-medium">{num(a.score_correlation)}</div></div>
        <div><div className="text-small text-muted">Mean score gap</div><div className="num font-medium">{num(a.mean_score_difference, 1)}</div></div>
      </div>
      <Confusion table={a.confusion} rowLabel={a.between[0]} colLabel={a.between[1]} />
      <div className="text-small text-muted">Compared on {a.compared} questions. Kappa: 1 = perfect agreement, 0 = no better than chance.</div>
    </div>
  );
}

function JudgeTable({ m }) {
  const rows = [
    ['Graded', (j) => j.graded], ['Errors', (j) => j.errors],
    ['Pass rate', (j) => pct(j.pass_rate)], ['Pass or partial', (j) => pct(j.pass_or_partial_rate)],
    ['Mean score (0-10)', (j) => num(j.mean_score, 1)],
    ['Must-include coverage', (j) => pct(j.must_coverage)], ['Should-include coverage', (j) => pct(j.should_coverage)],
    ['Must-not violations', (j) => j.must_not_violations],
    ['Unsupported claims found', (j) => j.unsupported_claims], ['Contradicted claims found', (j) => j.contradicted_claims],
    ['Verdict matches its own rubric grades', (j) => pct(j.self_consistency)],
    ['Grounding', (j) => Object.entries(j.grounding).map(([k, v]) => `${k.replace('_', ' ')} ${v}`).join(', ') || '—'],
    ['Confidence', (j) => Object.entries(j.confidence).map(([k, v]) => `${k} ${v}`).join(', ') || '—'],
    ['Median latency', (j) => (j.latency_s.median ? `${num(j.latency_s.median, 1)}s` : '—')],
    ['Calls · tokens', (j) => `${j.calls} · ${compact(j.tokens)}`],
    ['Fallback model used', (j) => j.fallback_used],
  ];
  return (
    <div className="panel overflow-hidden">
      <table className="w-full text-body">
        <thead><tr className="border-b border-line text-left text-muted">
          <th className="font-normal px-4 py-2">Judge metric</th>
          <th className="font-normal px-4 py-2">{m.models.small_judge} (smaller)</th>
          <th className="font-normal px-4 py-2">{m.models.large_judge} (larger)</th>
        </tr></thead>
        <tbody>{rows.map(([label, f]) => (
          <tr key={label} className="border-b border-rule last:border-0">
            <td className="px-4 py-2 text-muted">{label}</td>
            <td className="px-4 py-2 num">{f(m.judges.small)}</td>
            <td className="px-4 py-2 num">{f(m.judges.large)}</td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function CaseMetrics({ m }) {
  const b = m.base;
  const types = [...new Set([...Object.keys(m.judges.small.pass_rate_by_type), ...Object.keys(m.judges.large.pass_rate_by_type)])];
  return (
    <div className="space-y-8">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatTile label="Answered" value={`${b.answered}/${m.questions}`} hint={b.errors ? `${b.errors} failed` : 'by the base agent'} />
        <StatTile label="Smaller judge pass rate" value={pct(m.judges.small.pass_rate)} hint={m.models.small_judge} />
        <StatTile label="Larger judge pass rate" value={pct(m.judges.large.pass_rate)} hint={m.models.large_judge} />
        <StatTile label="Human pass rate" value={pct(m.human?.pass_rate)} hint={m.human ? `${m.human.reviewed} reviewed` : 'not reviewed yet'} />
      </div>

      <Section title="Verdicts" actions={<VerdictLegend />}>
        <div className="panel p-4 space-y-3">
          <VerdictBar label={`${m.models.small_judge} (smaller)`} counts={m.judges.small.verdicts} />
          <VerdictBar label={`${m.models.large_judge} (larger)`} counts={m.judges.large.verdicts} />
          <VerdictBar label="Human checker" counts={m.human?.verdicts || {}} />
          <div className="text-small text-muted">Number on the right: questions graded. Hover a segment for its count.</div>
        </div>
      </Section>

      <Section title="Agreement">
        <div className="grid lg:grid-cols-2 gap-4 items-start">
          <Agreement a={m.agreement} title="Smaller vs larger judge" />
          {m.human ? (
            <div className="space-y-4">
              <Agreement a={m.human.small_vs_human} title="Smaller judge vs human" />
              <Agreement a={m.human.large_vs_human} title="Larger judge vs human" />
            </div>
          ) : <div className="panel p-4 text-muted">Judge vs human agreement appears once the human checker has reviewed answers.</div>}
        </div>
        {m.agreement.disagreements.length > 0 && (
          <div className="text-small">
            <span className="text-muted">Disagreements: </span>
            {m.agreement.disagreements.map((d) => <a key={d.id} className="link-action text-small mr-2" href={`#/review/${m.case}`}>{d.id}</a>)}
          </div>
        )}
      </Section>

      <Section title="Judges in detail"><JudgeTable m={m} /></Section>

      {types.length > 0 && (
        <Section title="Pass rate by question type">
          <div className="panel overflow-hidden">
            <table className="w-full text-body">
              <thead><tr className="border-b border-line text-left text-muted"><th className="font-normal px-4 py-2">Type</th>
                <th className="font-normal px-4 py-2">Smaller judge</th><th className="font-normal px-4 py-2">Larger judge</th></tr></thead>
              <tbody>{types.map((t) => (
                <tr key={t} className="border-b border-rule last:border-0"><td className="px-4 py-2">{t}</td>
                  <td className="px-4 py-2 num">{pct(m.judges.small.pass_rate_by_type[t])}</td>
                  <td className="px-4 py-2 num">{pct(m.judges.large.pass_rate_by_type[t])}</td></tr>
              ))}</tbody>
            </table>
          </div>
        </Section>
      )}

      <Section title={`Base agent: ${m.models.base}`}>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatTile label="Answerable questions answered" value={pct(b.answerable_answered)} />
          <StatTile label="Unanswerable correctly declined" value={pct(b.unanswerable_declined)} />
          <StatTile label="Citations check out" value={pct(b.citations_ok)} hint={`mean support ${num(b.mean_citation_support)}`} />
          <StatTile label="Median latency" value={b.latency_s.median ? `${num(b.latency_s.median, 1)}s` : '—'} hint={`${compact(b.tokens.input + b.tokens.output)} tokens`} />
          <StatTile label="Source file retrieved" value={pct(b.source_hit_rate)} hint="questions that name a source file" />
          <StatTile label="Source MRR" value={num(b.source_mrr)} hint="1 / rank of the first passage from it" />
          <StatTile label="Mean best relevance" value={num(b.mean_best_relevance)} hint="Voyage rerank score" />
          <StatTile label="Match zones" value={Object.values(b.match_zones).reduce((s, v) => s + v, 0) || '—'}
                    hint={Object.entries(b.match_zones).map(([k, v]) => `${k} ${v}`).join(' · ') || 'none yet'} />
        </div>
      </Section>
    </div>
  );
}

export default function Metrics({ arg }) {
  const [compare, setCompare] = useState(null);
  const [m, setM] = useState(null);
  const [error, setError] = useState(null);
  const caseKey = arg || compare?.[0]?.case;

  useEffect(() => { api.compare().then((d) => setCompare(d.cases)).catch(setError); }, []);
  useEffect(() => { if (caseKey) { setM(null); api.metrics(caseKey).then(setM).catch(setError); } }, [caseKey]);

  if (error) return <ErrorNote error={error} />;
  if (!compare) return <div className="skeleton h-40" />;

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-title font-medium">Metrics</h1>
        <p className="text-muted mt-1">Recomputed from the saved results every time you open this page.</p>
      </header>

      <Section title="Both cases">
        <div className="panel overflow-x-auto">
          <table className="w-full text-body">
            <thead><tr className="border-b border-line text-left text-muted">
              {['Case', 'Base', 'Answered', 'Declined unanswerable', 'Citations OK', 'Smaller judge pass', 'Larger judge pass',
                'Judges agree', 'Kappa', 'Human pass'].map((h) => <th key={h} className="font-normal px-3 py-2 whitespace-nowrap">{h}</th>)}
            </tr></thead>
            <tbody>{compare.map((r) => (
              <tr key={r.case} onClick={() => go('metrics', r.case)}
                  className={`border-b border-rule last:border-0 cursor-pointer hover:bg-raised ${r.case === caseKey ? 'bg-active' : ''}`}>
                <td className="px-3 py-2 font-medium whitespace-nowrap">{r.label.split(':')[0]}</td>
                <td className="px-3 py-2 whitespace-nowrap">{r.models.base}</td>
                <td className="px-3 py-2 num">{r.answered}/{r.questions}</td>
                <td className="px-3 py-2 num">{pct(r.unanswerable_declined)}</td>
                <td className="px-3 py-2 num">{pct(r.citations_ok)}</td>
                <td className="px-3 py-2 num">{pct(r.small_pass_rate)} <span className="text-muted text-small">{r.models.small_judge}</span></td>
                <td className="px-3 py-2 num">{pct(r.large_pass_rate)} <span className="text-muted text-small">{r.models.large_judge}</span></td>
                <td className="px-3 py-2 num">{pct(r.judge_agreement)}</td>
                <td className="px-3 py-2 num">{num(r.judge_kappa)}</td>
                <td className="px-3 py-2 num">{pct(r.human_pass_rate)} {r.human_reviewed > 0 && <span className="text-muted text-small">({r.human_reviewed})</span>}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      </Section>

      {m && (
        <Section title={m.label} actions={
          <div className="flex gap-2">
            <a className="btn-ghost" href={`/api/export/${m.case}.csv`}><Download size={14} /> CSV</a>
            <a className="btn-ghost" href={`/api/export/${m.case}.json`}><Download size={14} /> JSON</a>
          </div>
        }>
          <CaseMetrics m={m} />
        </Section>
      )}
    </div>
  );
}
