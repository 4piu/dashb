import { useEffect, useMemo, useRef, useState } from 'react';
import './style.css';

type MetricMeta = {
  metric: string;
  unit?: string;
  kind?: string;
  subscribable?: boolean;
};

type MetricValue = {
  value: unknown;
  unit?: string;
  ts_ms: number;
};

type ServerInfoMessage = {
  type: 'server_info';
  metrics?: MetricMeta[];
};

type SampleMessage = {
  type: 'sample';
  ts_ms: number;
  values?: Array<{
    metric: string;
    value: unknown;
    unit?: string;
  }>;
};

type QueryResultMessage = {
  type: 'query_result';
  ts_ms: number;
  values?: Array<{
    metric: string;
    value: unknown;
    unit?: string;
  }>;
};

type SubscribedMessage = {
  type: 'subscribed';
  accepted?: Array<{
    metric: string;
    interval_ms: number;
  }>;
  rejected?: Array<{
    metric: string;
    reason: string;
  }>;
};

type ErrorMessage = {
  type: 'error';
  code?: string;
  message?: string;
};

function formatValue(value: unknown): string {
  if (Array.isArray(value)) {
    return `[${value.map((item) => formatValue(item)).join(', ')}]`;
  }

  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(3);
  }

  if (value === null || value === undefined) {
    return 'n/a';
  }

  if (typeof value === 'object') {
    return JSON.stringify(value);
  }

  return String(value);
}

function App() {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const shouldReconnectRef = useRef(true);
  const reconnectNowRef = useRef<(() => void) | null>(null);
  const [connectionState, setConnectionState] = useState('connecting');
  const [reconnectPaused, setReconnectPaused] = useState(false);
  const [metrics, setMetrics] = useState<MetricMeta[]>([]);
  const [values, setValues] = useState<Record<string, MetricValue>>({});
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [connectionDetail, setConnectionDetail] = useState('');

  useEffect(() => {
    let cancelled = false;

    const clearReconnectTimer = () => {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const pauseReconnect = (detail: string) => {
      clearReconnectTimer();
      shouldReconnectRef.current = false;
      setReconnectPaused(true);
      setConnectionState('error');
      setConnectionDetail(detail);
    };

    const connect = () => {
      clearReconnectTimer();
      shouldReconnectRef.current = true;
      setReconnectPaused(false);
      setConnectionState('connecting');
      setConnectionDetail('');
      wsRef.current?.close();
      wsRef.current = null;

      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const socket = new WebSocket(`${protocol}//${window.location.host}/ws`);
      wsRef.current = socket;

      socket.addEventListener('open', () => {
        setConnectionState('connected');
        setConnectionDetail('websocket open');
        socket.send(
          JSON.stringify({
            type: 'hello',
            id: 'debug-hello',
            proto_min: 1,
            proto_max: 1,
            client: {
              name: 'dashb-debug-theme',
              version: '0.1.0',
            },
          }),
        );
      });

      socket.addEventListener('message', (event) => {
        if (wsRef.current !== socket) {
          return;
        }

        let message:
          | ServerInfoMessage
          | SampleMessage
          | QueryResultMessage
          | SubscribedMessage
          | ErrorMessage
          | { type: string; metrics?: MetricMeta[] };

        try {
          message = JSON.parse(event.data) as
            | ServerInfoMessage
            | SampleMessage
            | QueryResultMessage
            | SubscribedMessage
            | ErrorMessage
            | { type: string; metrics?: MetricMeta[] };
        } catch (error) {
          pauseReconnect(`invalid websocket json: ${String(error)}`);
          return;
        }

        if (message.type === 'server_info') {
          const advertisedMetrics = message.metrics ?? [];
          setMetrics(advertisedMetrics);
          const queryMetrics = advertisedMetrics
            .filter(({ subscribable }) => subscribable === false)
            .map(({ metric }) => metric);
          const subscriptionMetrics = advertisedMetrics.filter(
            ({ subscribable }) => subscribable !== false,
          );

          if (queryMetrics.length > 0) {
            socket.send(
              JSON.stringify({
                type: 'query',
                id: 'debug-query',
                metrics: queryMetrics,
              }),
            );
          }

          for (let index = 0; index < subscriptionMetrics.length; index += 24) {
            const batch = subscriptionMetrics.slice(index, index + 24);
            socket.send(
              JSON.stringify({
                type: 'subscribe',
                id: `debug-subscribe-${index / 24}`,
                subscriptions: batch.map(({ metric }) => ({
                  metric,
                  interval_ms: 1000,
                })),
              }),
            );
          }
          return;
        }

        if (message.type === 'error') {
          const errorMessage = message as ErrorMessage;
          pauseReconnect(
            `server error${errorMessage.code ? ` ${errorMessage.code}` : ''}: ${errorMessage.message ?? 'unknown error'}`,
          );
          return;
        }

        if (message.type === 'subscribed') {
          const subscribedMessage = message as SubscribedMessage;
          const accepted = subscribedMessage.accepted?.length ?? 0;
          const rejected = subscribedMessage.rejected?.length ?? 0;
          setConnectionDetail(
            `subscribed accepted=${accepted} rejected=${rejected}`,
          );
          return;
        }

        if (message.type === 'sample') {
          const sampleMessage = message as SampleMessage;
          setValues((current) => {
            const next = { ...current };

            for (const entry of sampleMessage.values ?? []) {
              next[entry.metric] = {
                value: entry.value,
                unit: entry.unit,
                ts_ms: sampleMessage.ts_ms,
              };
            }

            return next;
          });
          setLastUpdated(sampleMessage.ts_ms);
          return;
        }

        if (message.type === 'query_result') {
          const queryMessage = message as QueryResultMessage;
          setValues((current) => {
            const next = { ...current };

            for (const entry of queryMessage.values ?? []) {
              next[entry.metric] = {
                value: entry.value,
                unit: entry.unit,
                ts_ms: queryMessage.ts_ms,
              };
            }

            return next;
          });
        }
      });

      socket.addEventListener('close', (event) => {
        if (wsRef.current !== socket) {
          return;
        }

        wsRef.current = null;
        const detail = `closed code=${event.code} clean=${event.wasClean}${event.reason ? ` reason=${event.reason}` : ''}`;

        if (!cancelled && event.code !== 1000) {
          pauseReconnect(detail);
          return;
        }

        setConnectionState('disconnected');
        setConnectionDetail(detail);

        if (!cancelled && shouldReconnectRef.current) {
          reconnectTimerRef.current = window.setTimeout(connect, 1000);
        }
      });

      socket.addEventListener('error', (event) => {
        if (wsRef.current !== socket) {
          return;
        }

        pauseReconnect(`websocket error: ${event.type}`);
      });
    };

    reconnectNowRef.current = connect;
    connect();

    return () => {
      cancelled = true;
      clearReconnectTimer();
      reconnectNowRef.current = null;
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, []);

  const rows = useMemo(
    () =>
      metrics.map((metric) => {
        const currentValue = values[metric.metric];
        return {
          ...metric,
          value: currentValue ? formatValue(currentValue.value) : 'waiting...',
          unit: currentValue?.unit ?? metric.unit ?? '',
          ts: currentValue?.ts_ms ?? null,
        };
      }),
    [metrics, values],
  );

  return (
    <main className="debug-screen">
      <header className="debug-header">
        <h1>dashb debug monitor</h1>
        <p>connection: {connectionState}</p>
        {connectionDetail ? <p>detail: {connectionDetail}</p> : null}
        {reconnectPaused ? (
          <button
            className="debug-reconnect"
            type="button"
            onClick={() => reconnectNowRef.current?.()}
          >
            reconnect
          </button>
        ) : null}
        <p>refresh: every 1s</p>
        <p>metrics: {rows.length}</p>
        <p>last sample: {lastUpdated ? new Date(lastUpdated).toLocaleTimeString() : 'waiting...'}</p>
      </header>

      <section className="metric-list" aria-label="supported metrics">
        {rows.map((row) => (
          <article key={row.metric} className="metric-row">
            <div className="metric-name">{row.metric}</div>
            <div className="metric-value">
              {row.value}
              {row.unit ? ` ${row.unit}` : ''}
            </div>
          </article>
        ))}
      </section>
    </main>
  );
}

export default App;
