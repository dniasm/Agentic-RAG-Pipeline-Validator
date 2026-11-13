import { useEffect, useState } from 'react';
import { BarChart3, ClipboardCheck, Database, LayoutGrid, ListChecks, Monitor, Moon, PlayCircle, Sun } from 'lucide-react';
import { useTheme } from './lib/theme.js';
import { api } from './lib/api.js';
import Overview from './pages/Overview.jsx';
import Corpus from './pages/Corpus.jsx';
import Questions from './pages/Questions.jsx';
import Runs from './pages/Runs.jsx';
import Review from './pages/Review.jsx';
import Metrics from './pages/Metrics.jsx';

const PAGES = [
  { key: 'overview', label: 'Overview', Icon: LayoutGrid, Page: Overview },
  { key: 'corpus', label: 'Corpus', Icon: Database, Page: Corpus },
  { key: 'questions', label: 'Question set', Icon: ListChecks, Page: Questions },
  { key: 'runs', label: 'Runs', Icon: PlayCircle, Page: Runs },
  { key: 'review', label: 'Review', Icon: ClipboardCheck, Page: Review },
  { key: 'metrics', label: 'Metrics', Icon: BarChart3, Page: Metrics },
];

// Hash routes: #/review/case2 -> page "review", arg "case2".
function readRoute() {
  const [page, arg] = window.location.hash.replace(/^#\/?/, '').split('/');
  return { page: PAGES.some((p) => p.key === page) ? page : 'overview', arg: arg || null };
}

export function go(page, arg) {
  window.location.hash = `/${page}${arg ? `/${arg}` : ''}`;
}

export default function App() {
  const [route, setRoute] = useState(readRoute);
  const [theme, setTheme] = useTheme();
  const [visitor, setVisitor] = useState(false);
  useEffect(() => {
    api.access().then((a) => {
      const readOnly = a.remote && !a.can_run;
      setVisitor(readOnly);
      document.body.classList.toggle('visitor', readOnly);
    }).catch(() => {});
  }, []);
  useEffect(() => {
    const onHash = () => setRoute(readRoute());
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);
  const { Page } = PAGES.find((p) => p.key === route.page);
  const ThemeIcon = { system: Monitor, light: Sun, dark: Moon }[theme];
  const nextTheme = { system: 'light', light: 'dark', dark: 'system' }[theme];

  return (
    <div className="flex h-full">
      <aside className="w-[220px] flex-none border-r border-line bg-surface flex flex-col">
        <a href="#/overview" title="Go to Overview"
           className="px-4 h-14 flex items-center gap-2 border-b border-line hover:bg-raised">
          <img src="/mark.svg" alt="" className="w-5 h-5" />
          <span className="font-medium">RAG Validator</span>
        </a>
        <nav className="p-2 space-y-0.5 flex-1">
          {PAGES.map(({ key, label, Icon }) => (
            <a key={key} href={`#/${key}`}
               className={`flex items-center gap-2 h-9 px-3 rounded-control text-body ${route.page === key
                 ? 'bg-active text-ink font-medium' : 'text-muted hover:bg-raised hover:text-ink'}`}>
              <Icon size={16} /> {label}
            </a>
          ))}
        </nav>
        {visitor && (
          <p className="mx-3 mb-1 text-small text-muted">
            Shared view: you can browse results and record reviews. Runs and corpus changes are host-only.
          </p>
        )}
        <button className="btn-ghost m-2 justify-start text-muted" onClick={() => setTheme(nextTheme)}
                title={`Theme: ${theme} (click for ${nextTheme})`}>
          <ThemeIcon size={16} /> Theme: {theme}
        </button>
      </aside>
      <main className="flex-1 min-w-0 overflow-y-auto">
        <div className="max-w-[1200px] mx-auto px-8 py-8">
          <Page arg={route.arg} />
        </div>
      </main>
    </div>
  );
}
