import { useState, useEffect } from 'react';

export interface HealthStatus {
  service: string;
  status: 'online' | 'offline' | 'warning' | 'error' | 'processing' | 'idle';
  latency_ms: number;
  updated_at: string;
}

export function useHealthWS(url: string = 'ws://localhost:8700/ws/health') {
  const [healthData, setHealthData] = useState<HealthStatus[]>([]);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket;
    let reconnectTimer: number;
    let backoff = 1000;

    const connect = () => {
      ws = new WebSocket(url);

      ws.onopen = () => {
        setIsConnected(true);
        backoff = 1000; // reset backoff
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setHealthData(data);
        } catch (e) {
          console.error("Failed to parse WS message", e);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        // Exponential backoff
        reconnectTimer = window.setTimeout(connect, backoff);
        backoff = Math.min(backoff * 1.5, 10000);
      };

      ws.onerror = (err) => {
        console.error("WS error:", err);
        ws.close();
      };
    };

    connect();

    return () => {
      clearTimeout(reconnectTimer);
      if (ws) {
        ws.close();
      }
    };
  }, [url]);

  return { healthData, isConnected };
}