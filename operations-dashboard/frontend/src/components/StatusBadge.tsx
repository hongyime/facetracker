import React from 'react';
import { cn } from '../utils/cn';

interface StatusBadgeProps {
  label: string;
  status: 'online' | 'offline' | 'warning' | 'error' | 'processing' | 'idle';
}

export function StatusBadge({ label, status }: StatusBadgeProps) {
  const statusConfig = {
    online: 'bg-success',
    offline: 'bg-muted',
    warning: 'bg-warning',
    error: 'bg-error',
    processing: 'bg-info animate-pulse',
    idle: 'bg-secondary',
  };

  return (
    <div className="flex items-center gap-2 px-2 py-1 rounded-full bg-white/5 border border-border w-fit">
      <div className={cn("w-2 h-2 rounded-full", statusConfig[status])} />
      <span className="text-xs font-medium text-secondary capitalize">{label}</span>
    </div>
  );
}