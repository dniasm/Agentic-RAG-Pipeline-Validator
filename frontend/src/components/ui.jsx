import { CheckCircle2, CircleDashed, MinusCircle, XCircle } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Verdicts are status, so they use the status tokens, and always carry an icon + word (never colour alone).
export const VERDICT = {
  pass: { label: 'Pass', pill: 'pill-positive', color: 'var(--positive)', Icon: CheckCircle2 },
  partial: { label: 'Partial', pill: 'pill-warning', color: 'var(--warning)', Icon: MinusCircle },
  fail: { label: 'Fail', pill: 'pill-negative', color: 'var(--negative)', Icon: XCircle },
};

export function Verdict({ value, error }) {
  if (error) return <span className="pill-negative" title={error}><XCircle size={12} /> Error</span>;
  const v = VERDICT[value];
  if (!v) return <span className="pill-neutral"><CircleDashed size={12} /> Pending</span>;
  return <span className={v.pill}><v.Icon size={12} /> {v.label}</span>;
}

const POINT = {
  covered: 'pill-positive', respected: 'pill-positive', partial: 'pill-warning',
  missing: 'pill-negative', violated: 'pill-negative',
};
export function PointStatus({ status }) {
  return <span className={POINT[status] || 'pill-neutral'}>{status}</span>;
}

export function StatTile({ label, value, hint }) {
  return (
    <div className="panel p-4 min-w-0">
      <div className="text-small text-muted">{label}</div>
      <div className="text-kpi font-medium num mt-1">{value}</div>
      {hint && <div className="text-small text-muted mt-1">{hint}</div>}
    </div>
  );
}

// Segmented bar: one whole (all graded questions) split into pass / partial / fail.
// Tall variant: 28px, 4px corners, 2px surface gap, share inside a segment only when it fits.
export function VerdictBar({ counts, label }) {
  const order = ['pass', 'partial', 'fail'];
  const total = order.reduce((s, k) => s + (counts?.[k] || 0), 0);
  return (
    <div className="flex items-center gap-3">
      <div className="w-40 flex-none text-body text-ink truncate" title={label}>{label}</div>
      {total === 0 ? (
        <div className="h-7 flex-1 rounded bg-raised" title="Nothing graded yet" />
      ) : (
        <div className="flex h-7 flex-1 gap-[2px]" role="img"
             aria-label={`${label}: ${order.map((k) => `${counts[k] || 0} ${k}`).join(', ')} of ${total}`}>
          {order.filter((k) => counts[k]).map((k) => {
            const share = counts[k] / total;
            return (
              <div key={k} className="h-full rounded-[4px] flex items-center justify-center text-small font-medium num"
                   style={{ width: `${share * 100}%`, background: VERDICT[k].color,
                            color: k === 'partial' ? '#0b0b0b' : '#ffffff' }}
                   title={`${VERDICT[k].label}: ${counts[k]} of ${total} (${Math.round(share * 100)}%)`}>
                {share >= 0.12 ? `${Math.round(share * 100)}%` : ''}
              </div>
            );
          })}
        </div>
      )}
      <div className="w-12 flex-none text-right text-small text-muted num">{total}</div>
    </div>
  );
}

export function VerdictLegend() {
  return (
    <div className="flex gap-4 text-small text-muted">
      {Object.entries(VERDICT).map(([k, v]) => (
        <span key={k} className="inline-flex items-center gap-1.5">
          <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: v.color }} />
          <v.Icon size={12} /> {v.label}
        </span>
      ))}
    </div>
  );
}

export function Markdown({ children }) {
  return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ''}</ReactMarkdown></div>;
}

export function Section({ title, actions, children }) {
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-section font-medium">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

export function ErrorNote({ error }) {
  if (!error) return null;
  return <div className="panel p-3 text-body text-negative border-[color:var(--negative)]">{String(error)}</div>;
}

export function ProgressBar({ done, total }) {
  const share = total ? Math.min(done / total, 1) : 0;
  return (
    <div className="h-2 w-full rounded-full bg-raised overflow-hidden" role="progressbar"
         aria-valuenow={done} aria-valuemax={total}>
      <div className="h-full rounded-full bg-[color:var(--hue)]" style={{ width: `${share * 100}%` }} />
    </div>
  );
}
