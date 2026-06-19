import { useEffect, useState } from 'react';
import './index.css';

type ThemeInfo = {
  id: string;
  name: string;
  path: string;
  description?: string;
  version?: string;
};

const fallbackThemes: ThemeInfo[] = [
  {
    id: 'debug',
    name: 'Debug',
    path: '/theme/debug/',
    description: 'Simple live metric list for Dashb development',
  },
];

function App() {
  const [themes, setThemes] = useState<ThemeInfo[]>([]);
  const [status, setStatus] = useState('loading themes...');

  useEffect(() => {
    let cancelled = false;

    fetch('/api/themes')
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json() as Promise<ThemeInfo[]>;
      })
      .then((nextThemes) => {
        if (cancelled) {
          return;
        }
        setThemes(nextThemes);
        setStatus(nextThemes.length ? 'choose a dashboard theme' : 'no themes found');
      })
      .catch(() => {
        if (cancelled) {
          return;
        }
        setThemes(fallbackThemes);
        setStatus('using bundled theme list');
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="theme-selector">
      <section className="theme-card" aria-labelledby="theme-selector-title">
        <p className="eyebrow">dashb</p>
        <h1 id="theme-selector-title">Theme Selector</h1>
        <p className="status">{status}</p>

        <div className="theme-list">
          {themes.map((theme) => (
            <a key={theme.id} className="theme-link" href={theme.path}>
              <span>
                <strong>{theme.name}</strong>
                {theme.description ? <small>{theme.description}</small> : null}
              </span>
              {theme.version ? <em>v{theme.version}</em> : null}
            </a>
          ))}
        </div>
      </section>
    </main>
  );
}

export default App;
