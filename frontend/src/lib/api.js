// Thin wrapper over the validator backend (proxied to :8100 in dev, same origin when built).
async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, opts);
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new Error((data && data.detail) || `${res.status} ${res.statusText}`);
  return data;
}

export const api = {
  access: () => request('GET', '/access'),
  overview: () => request('GET', '/overview'),
  corpus: () => request('GET', '/corpus'),
  corpusPlan: () => request('GET', '/corpus/plan'),
  upload: (files) => {
    const form = new FormData();
    [...files].forEach((f) => form.append('files', f));
    return request('POST', '/corpus/upload', form);
  },
  ingest: () => request('POST', '/corpus/ingest'),
  questions: () => request('GET', '/questions'),
  run: (c) => request('GET', `/runs/${c}`),
  start: (c, limit) => request('POST', `/runs/${c}/start`, { limit: limit || null }),
  stop: (c) => request('POST', `/runs/${c}/stop`),
  reset: (c, target) => request('POST', `/runs/${c}/reset`, { target }),
  results: (c) => request('GET', `/results/${c}`),
  setHuman: (c, qid, body) => request('PUT', `/results/${c}/${qid}/human`, body),
  clearHuman: (c, qid) => request('DELETE', `/results/${c}/${qid}/human`),
  metrics: (c) => request('GET', `/metrics/${c}`),
  compare: () => request('GET', '/metrics'),
};

export const pct = (v) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);
export const num = (v, d = 2) => (v === null || v === undefined ? '—' : Number(v).toFixed(d));
export const compact = (v) => (v === null || v === undefined ? '—'
  : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e4 ? `${Math.round(v / 1e3)}K` : v.toLocaleString());
