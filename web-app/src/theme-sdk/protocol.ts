// Wire types for the dashb WebSocket protocol (`/ws`). Kept dependency-free
// and framework-agnostic so this module can be consumed both by themes with
// a JS bundler (via `import`) and by plain static-HTML themes (via the
// bundled `theme-runtime.js` global, see client.ts).

export type MetricMeta = {
  metric: string;
  unit?: string;
  kind?: string;
  subscribable?: boolean;
};

export type SampleEntry = {
  metric: string;
  value: unknown;
  unit?: string;
};

export type WelcomeMessage = {
  type: 'welcome';
  id?: string;
  ts_ms: number;
  proto: number;
  server?: { name?: string; version?: string };
  capabilities?: {
    auth?: string;
    tls?: boolean;
    query?: boolean;
    max_subscriptions?: number;
    min_interval_ms?: number;
    max_interval_ms?: number;
  };
};

export type ServerInfoMessage = {
  type: 'server_info';
  ts_ms: number;
  metrics?: MetricMeta[];
};

export type SampleMessage = {
  type: 'sample';
  ts_ms: number;
  values?: SampleEntry[];
};

export type QueryResultMessage = {
  type: 'query_result';
  id?: string;
  ts_ms: number;
  values?: SampleEntry[];
};

export type SubscribedMessage = {
  type: 'subscribed';
  id?: string;
  accepted?: Array<{ metric: string; interval_ms: number }>;
  rejected?: Array<{ metric: string; reason: string }>;
};

export type ErrorMessage = {
  type: 'error';
  id?: string;
  code?: string;
  message?: string;
};

export type PongMessage = {
  type: 'pong';
  id?: string;
  ts_ms: number;
};

export type DashbMessage =
  | WelcomeMessage
  | ServerInfoMessage
  | SampleMessage
  | QueryResultMessage
  | SubscribedMessage
  | ErrorMessage
  | PongMessage
  | { type: string };

export type Subscription = {
  metric: string;
  interval_ms: number;
};

// 'stale' is distinct from 'disconnected': the socket is still technically
// open, but no data has arrived recently enough to trust what's on screen
// (e.g. the server machine went to sleep without ever closing the socket).
export type ConnectionState = 'connecting' | 'connected' | 'stale' | 'disconnected' | 'error';
