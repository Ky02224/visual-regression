import { useState, useEffect, useRef } from 'react';

export interface SSEEvent {
  type: string;
  data: Record<string, any>;
  timestamp: number;
}

interface UseSSEOptions {
  onEvent?: (event: SSEEvent) => void;
}

interface Listener {
  onEvent: (event: SSEEvent) => void;
  onConnectionChange: (connected: boolean) => void;
}

interface SharedConnection {
  eventSource: EventSource | null;
  reconnectTimeoutId: any;
  reconnectAttempt: number;
  isConnected: boolean;
  listeners: Set<Listener>;
}

const EVENT_TYPES = [
  'task_started',
  'task_progress',
  'task_completed',
  'task_failed',
  'baseline_updated',
  'compare_completed',
  'compare_failed',
  'scheduler_updated',
  'comment_updated',
  'capture_progress',
  'ai_training',
];

// Every page under Layout mounts useSSE (Layout + TopBar, plus report pages),
// which used to each open their own EventSource to the same URL. This module
// keeps one real connection per URL shared across all callers, torn down only
// once the last subscriber unmounts.
const connections = new Map<string, SharedConnection>();

function getOrCreateConnection(url: string): SharedConnection {
  const existing = connections.get(url);
  if (existing) return existing;

  const conn: SharedConnection = {
    eventSource: null,
    reconnectTimeoutId: null,
    reconnectAttempt: 0,
    isConnected: false,
    listeners: new Set(),
  };
  connections.set(url, conn);

  const maxRetries = 10;

  function connect() {
    if (conn.eventSource) {
      conn.eventSource.close();
    }

    const es = new EventSource(url);
    conn.eventSource = es;

    es.onopen = () => {
      conn.isConnected = true;
      conn.reconnectAttempt = 0;
      conn.listeners.forEach((l) => l.onConnectionChange(true));
    };

    es.onerror = () => {
      conn.isConnected = false;
      conn.listeners.forEach((l) => l.onConnectionChange(false));
      if (conn.eventSource) {
        conn.eventSource.close();
        conn.eventSource = null;
      }

      const attempt = conn.reconnectAttempt;
      if (attempt < maxRetries) {
        // Exponential backoff, not a fixed 3s. EventSource does not expose the
        // HTTP status to onerror, so a 401 on an unauthenticated tab is
        // indistinguishable from a dropped connection — and retrying every
        // three seconds produced ten identical "GET /api/events/stream 401"
        // lines in the server log for anyone sitting on the login page.
        // Retrying cannot produce a session, and the noise buries real errors.
        // Backing off keeps the recovery for genuinely transient failures while
        // making the hopeless case cheap and quiet.
        const delay = Math.min(3000 * 2 ** attempt, 60000);
        conn.reconnectTimeoutId = setTimeout(() => {
          conn.reconnectAttempt = attempt + 1;
          connect();
        }, delay);
      }
    };

    EVENT_TYPES.forEach((type) => {
      es.addEventListener(type, (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data);
          const event: SSEEvent = { type, data, timestamp: Date.now() };
          conn.listeners.forEach((l) => l.onEvent(event));
        } catch (err) {
          console.error('Error parsing SSE data:', err);
        }
      });
    });
  }

  connect();
  return conn;
}

function releaseConnection(url: string, listener: Listener) {
  const conn = connections.get(url);
  if (!conn) return;
  conn.listeners.delete(listener);
  if (conn.listeners.size === 0) {
    if (conn.eventSource) conn.eventSource.close();
    if (conn.reconnectTimeoutId) clearTimeout(conn.reconnectTimeoutId);
    connections.delete(url);
  }
}

export function useSSE(url: string, options?: UseSSEOptions) {
  const [lastEvent, setLastEvent] = useState<SSEEvent | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const onEventRef = useRef(options?.onEvent);
  const reconnectAttemptRef = useRef(0);

  useEffect(() => {
    onEventRef.current = options?.onEvent;
  }, [options?.onEvent]);

  useEffect(() => {
    const listener: Listener = {
      onEvent: (event) => {
        setLastEvent(event);
        if (onEventRef.current) {
          onEventRef.current(event);
        }
      },
      onConnectionChange: (connected) => setIsConnected(connected),
    };

    const conn = getOrCreateConnection(url);
    conn.listeners.add(listener);
    setIsConnected(conn.isConnected);
    reconnectAttemptRef.current = conn.reconnectAttempt;

    return () => {
      releaseConnection(url, listener);
    };
  }, [url]);

  return {
    lastEvent,
    isConnected,
    reconnectCount: reconnectAttemptRef.current,
  };
}
