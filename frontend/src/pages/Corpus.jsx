import { useEffect, useRef, useState } from 'react';
import { Upload } from 'lucide-react';
import { api } from '../lib/api.js';
import { ErrorNote, Section } from '../components/ui.jsx';

const STATE = { ingested: 'pill-positive', changed: 'pill-warning', new: 'pill-neutral' };

export default function Corpus() {
  const [data, setData] = useState(null);
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const input = useRef(null);

  const load = () => api.corpus().then(setData).catch(setError);
  useEffect(() => {
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);

  const act = async (fn) => {
    setBusy(true); setError(null);
    try { await fn(); await load(); } catch (e) { setError(e); } finally { setBusy(false); }
  };

  if (!data) return error ? <ErrorNote error={error} /> : <div className="skeleton h-40" />;
  const pending = data.files.filter((f) => f.state !== 'ingested').length + data.removed.length;
  const running = data.ingest.state === 'running';

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-title font-medium">Corpus</h1>
        <p className="text-muted mt-1 max-w-[720px]">
          Files in <code className="font-mono text-small">data/corpus/</code> are ingested with day7's pipeline:
          clean, 1,000-character chunks with 200 overlap, Gemini embeddings and BM25 into Qdrant. Every chunk costs one
          Gemini embedding request, and the free tier allows 1,000 a day (shared with searches), so check the estimate
          before ingesting.
        </p>
      </header>
      <ErrorNote error={error} />

      <Section title="Files" actions={
        <div className="flex gap-2 host-only">
          <input ref={input} type="file" multiple accept=".pdf,.docx,.txt,.md" className="hidden"
                 onChange={(e) => act(() => api.upload(e.target.files))} />
          <button className="btn-secondary" disabled={busy || running} onClick={() => input.current.click()}>
            <Upload size={16} /> Add files
          </button>
          <button className="btn-secondary" disabled={busy || !pending}
                  onClick={() => act(async () => setPlan(await api.corpusPlan()))}>Estimate</button>
          <button className="btn-primary" disabled={busy || running || !pending} onClick={() => act(api.ingest)}>
            {running ? 'Ingesting…' : `Ingest${pending ? ` (${pending})` : ''}`}
          </button>
        </div>
      }>
        <div className="panel overflow-hidden">
          <table className="w-full text-body">
            <thead><tr className="text-left text-muted border-b border-line">
              <th className="font-normal px-4 py-2">File</th><th className="font-normal px-4 py-2">State</th>
              <th className="font-normal px-4 py-2 text-right">Size</th><th className="font-normal px-4 py-2 text-right">Pages</th>
              <th className="font-normal px-4 py-2 text-right">Chunks</th>
            </tr></thead>
            <tbody>
              {data.files.map((f) => (
                <tr key={f.name} className="border-b border-rule last:border-0">
                  <td className="px-4 py-2">{f.name}</td>
                  <td className="px-4 py-2"><span className={STATE[f.state]}>{f.state}</span></td>
                  <td className="px-4 py-2 text-right num">{f.size_kb} KB</td>
                  <td className="px-4 py-2 text-right num">{f.pages ?? '—'}</td>
                  <td className="px-4 py-2 text-right num">{f.chunks ?? '—'}</td>
                </tr>
              ))}
              {!data.files.length && (
                <tr><td colSpan={5} className="px-4 py-6 text-center text-muted">
                  No files yet. Add PDF, DOCX, TXT or MD files, or copy them into data/corpus/.
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="text-small text-muted">
          Stored chunks: <span className="num">{data.stored_chunks ?? '—'}</span>
          {data.removed.length > 0 && ` · ${data.removed.length} removed file(s) will be dropped on the next ingest`}
        </div>
      </Section>

      {plan && (
        <Section title="Estimate">
          <div className="panel p-4 text-body space-y-1">
            {plan.files.map((f) => <div key={f.name}>{f.name}: <span className="num">{f.chunks}</span> chunks</div>)}
            <div className="font-medium pt-1">Total: <span className="num">{plan.chunks}</span> embedding requests</div>
            <div className="text-small text-muted">{plan.note}</div>
          </div>
        </Section>
      )}

      {(data.ingest.log.length > 0 || data.ingest.error) && (
        <Section title={`Ingestion: ${data.ingest.state}`}>
          <ErrorNote error={data.ingest.error} />
          <pre className="panel p-3 font-mono text-small whitespace-pre-wrap max-h-72 overflow-y-auto">
            {data.ingest.log.join('\n')}
          </pre>
        </Section>
      )}
    </div>
  );
}
