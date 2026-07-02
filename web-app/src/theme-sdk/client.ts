import type {
  ConnectionState,
  DashbMessage,
  ErrorMessage,
  QueryResultMessage,
  SampleMessage,
  ServerInfoMessage,
  SubscribedMessage,
  Subscription,
  WelcomeMessage,
} from './protocol';

export type DashbClientOptions = {
  /** Defaults to ws(s)://<location.host>/ws. */
  url?: string;
  clientName?: string;
  clientVersion?: string;
  /** How long without any message before the connection is considered stale. Default 3000. */
  staleTimeoutMs?: number;
  /** How often to check for staleness. Default 500. */
  staleCheckIntervalMs?: number;
  /** Delay before reconnecting after a close/stale-forced-close. Default 1200. */
  reconnectDelayMs?: number;
  onConnectionChange?: (state: ConnectionState, detail: string) => void;
  onWelcome?: (message: WelcomeMessage) => void;
  onServerInfo?: (message: ServerInfoMessage) => void;
  onSample?: (message: SampleMessage) => void;
  onQueryResult?: (message: QueryResultMessage) => void;
  onSubscribed?: (message: SubscribedMessage) => void;
  onError?: (message: ErrorMessage) => void;
};

export type DashbClient = {
  /** Send a subscribe request. Queued until the connection has completed its hello handshake. */
  subscribe: (subscriptions: Subscription[], id?: string) => void;
  /** Send a query request for one-shot metric values. Queued the same way as subscribe. */
  query: (metrics: string[], id?: string) => void;
  /** Stop reconnecting and close the socket. The client is unusable after this. */
  close: () => void;
};

const DEFAULT_STALE_TIMEOUT_MS = 3000;
const DEFAULT_STALE_CHECK_INTERVAL_MS = 500;
const DEFAULT_RECONNECT_DELAY_MS = 1200;

function defaultUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws`;
}

/**
 * Connects to the dashb `/ws` endpoint and manages the hello handshake,
 * reconnection, and a staleness watchdog for connections that go quietly
 * dead (e.g. the server machine sleeps) without ever firing a close event.
 */
export function connectDashb(options: DashbClientOptions = {}): DashbClient {
  const url = options.url ?? defaultUrl();
  const staleTimeoutMs = options.staleTimeoutMs ?? DEFAULT_STALE_TIMEOUT_MS;
  const staleCheckIntervalMs = options.staleCheckIntervalMs ?? DEFAULT_STALE_CHECK_INTERVAL_MS;
  const reconnectDelayMs = options.reconnectDelayMs ?? DEFAULT_RECONNECT_DELAY_MS;

  let cancelled = false;
  let socket: WebSocket | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let staleCheckTimer: ReturnType<typeof setInterval> | null = null;
  let lastMessageAt = 0;
  let ready = false;
  let helloIdCounter = 0;
  const pending: string[] = [];

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const send = (payload: unknown) => {
    const text = JSON.stringify(payload);
    if (ready && socket && socket.readyState === WebSocket.OPEN) {
      socket.send(text);
    } else {
      pending.push(text);
    }
  };

  const flushPending = () => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    while (pending.length > 0) {
      socket.send(pending.shift() as string);
    }
  };

  const connect = () => {
    clearReconnectTimer();
    ready = false;
    options.onConnectionChange?.('connecting', '');

    const ws = new WebSocket(url);
    socket = ws;

    ws.addEventListener('open', () => {
      lastMessageAt = Date.now();
      helloIdCounter += 1;
      ws.send(
        JSON.stringify({
          type: 'hello',
          id: `hello-${helloIdCounter}`,
          proto_min: 1,
          proto_max: 1,
          client: {
            name: options.clientName ?? 'dashb-theme',
            version: options.clientVersion ?? '0.0.0',
          },
        }),
      );
    });

    ws.addEventListener('message', (event) => {
      if (socket !== ws) {
        return;
      }
      lastMessageAt = Date.now();

      let message: DashbMessage;
      try {
        message = JSON.parse(event.data) as DashbMessage;
      } catch (error) {
        options.onConnectionChange?.('error', `bad json: ${String(error)}`);
        return;
      }

      switch (message.type) {
        case 'welcome':
          options.onWelcome?.(message as WelcomeMessage);
          return;
        case 'server_info':
          ready = true;
          options.onConnectionChange?.('connected', 'online');
          flushPending();
          options.onServerInfo?.(message as ServerInfoMessage);
          return;
        case 'sample':
          options.onSample?.(message as SampleMessage);
          return;
        case 'query_result':
          options.onQueryResult?.(message as QueryResultMessage);
          return;
        case 'subscribed':
          options.onSubscribed?.(message as SubscribedMessage);
          return;
        case 'error':
          options.onConnectionChange?.('error', (message as ErrorMessage).message ?? 'server error');
          options.onError?.(message as ErrorMessage);
          return;
        default:
          return;
      }
    });

    ws.addEventListener('close', (event) => {
      if (socket !== ws) {
        return;
      }
      socket = null;
      ready = false;
      options.onConnectionChange?.('disconnected', `closed ${event.code}`);
      if (!cancelled) {
        reconnectTimer = setTimeout(connect, reconnectDelayMs);
      }
    });

    ws.addEventListener('error', () => {
      if (socket !== ws) {
        return;
      }
      options.onConnectionChange?.('error', 'websocket error');
    });
  };

  connect();

  // The server can disappear (sleep, crash, unplugged network) without the
  // socket ever firing close/error - the OS-level TCP timeout that would
  // eventually surface that can take minutes. Force a reconnect once data
  // goes stale instead of waiting for it.
  staleCheckTimer = setInterval(() => {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    if (Date.now() - lastMessageAt > staleTimeoutMs) {
      options.onConnectionChange?.('stale', 'no data received recently');
      socket.close();
    }
  }, staleCheckIntervalMs);

  return {
    subscribe(subscriptions: Subscription[], id = 'subscribe') {
      send({ type: 'subscribe', id, subscriptions });
    },
    query(metrics: string[], id = 'query') {
      send({ type: 'query', id, metrics });
    },
    close() {
      cancelled = true;
      clearReconnectTimer();
      if (staleCheckTimer !== null) {
        clearInterval(staleCheckTimer);
        staleCheckTimer = null;
      }
      socket?.close();
      socket = null;
    },
  };
}
