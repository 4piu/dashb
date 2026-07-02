import { useEffect, useState } from 'react';
import './index.css';

type ThemeInfo = {
  id: string;
  name: string;
  path: string;
  description?: string;
  version?: string;
  minServerVersion?: string;
};

type ThemesResponse = {
  serverVersion: string;
  themes: ThemeInfo[];
};

const fallbackThemes: ThemeInfo[] = [
  {
    id: 'debug',
    name: 'Debug',
    path: '/theme/debug/',
    description: 'Simple live metric list for Dashb development',
  },
];

// Numeric, dot-separated version compare (e.g. "0.10.0" > "0.9.0"). Returns
// > 0 if `a` is newer than `b`. Non-numeric segments are treated as 0 rather
// than rejected outright, since this only gates an advisory warning badge.
function compareVersions(a: string, b: string): number {
  const partsA = a.split('.').map((part) => parseInt(part, 10) || 0);
  const partsB = b.split('.').map((part) => parseInt(part, 10) || 0);
  const length = Math.max(partsA.length, partsB.length);
  for (let i = 0; i < length; i += 1) {
    const diff = (partsA[i] ?? 0) - (partsB[i] ?? 0);
    if (diff !== 0) {
      return diff;
    }
  }
  return 0;
}

function App() {
  const [themes, setThemes] = useState<ThemeInfo[]>([]);
  const [serverVersion, setServerVersion] = useState<string | null>(null);
  const [status, setStatus] = useState('loading themes...');

  useEffect(() => {
    let cancelled = false;

    fetch('/api/themes')
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        return response.json() as Promise<ThemesResponse>;
      })
      .then(({ serverVersion: version, themes: nextThemes }) => {
        if (cancelled) {
          return;
        }
        setThemes(nextThemes);
        setServerVersion(version ?? null);
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
        <header className="theme-header">
          <span className="brand">dashb</span>
          <h1 id="theme-selector-title">Theme Selector</h1>
        </header>
        <p className="status">{status}</p>

        <div className="theme-list">
          {themes.map((theme) => {
            const isIncompatible =
              !!theme.minServerVersion &&
              !!serverVersion &&
              compareVersions(theme.minServerVersion, serverVersion) > 0;
            return (
              <a key={theme.id} className="theme-link" href={theme.path}>
                <span>
                  <strong>{theme.name}</strong>
                  {theme.description ? <small>{theme.description}</small> : null}
                  {isIncompatible ? (
                    <small className="theme-warning">
                      requires server v{theme.minServerVersion}+ (running v{serverVersion})
                    </small>
                  ) : null}
                </span>
                {theme.version ? <em>v{theme.version}</em> : null}
              </a>
            );
          })}
        </div>
      </section>
    </main>
  );
}

export default App;
