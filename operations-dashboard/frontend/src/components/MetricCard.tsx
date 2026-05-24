import React from 'react';
import { cn } from '../utils/cn';

interface MetricCardProps {
  label: string;
  value: string | number;
  sublabel?: string;
  trend?: {
    value: number;
    direction: 'up' | 'down';
  };
  icon?: React.ReactNode;
  status?: 'success' | 'warning' | 'error' | 'info';
}

export function MetricCard({ label, value, sublabel, trend, icon, status }: MetricCardProps) {
  return (
    <div className="card flex flex-col gap-2">
      <div className="flex items-center justify-between text-xs uppercase tracking-wider text-muted font-medium">
        <span>{label}</span>
        {icon && <span className="text-secondary">{icon}</span>}
      </div>
      <div className="flex items-end gap-2">
        <span className="text-2xl font-mono font-semibold">{value}</span>
        {trend && (
          <span className={cn(
            "text-xs mb-1 font-mono",
            trend.direction === 'up' ? "text-success" : "text-error"
          )}>
            {trend.direction === 'up' ? '↑' : '↓'}{Math.abs(trend.value)}%
          </span>
        )}
      </div>
      {sublabel && <div className="text-xs text-secondary mt-1">{sublabel}</div>}
    </div>
  );
}