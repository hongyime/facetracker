import React from 'react';
import { Button } from './Button';

interface HeaderProps {
  title: string;
  subtitle?: string;
  lastUpdated?: string;
  onRefresh?: () => void;
  actions?: React.ReactNode;
}

export function Header({ title, subtitle, lastUpdated, onRefresh, actions }: HeaderProps) {
  return (
    <header className="flex items-start justify-between pb-6 mb-6 border-b border-border">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">{title}</h2>
        {subtitle && <p className="text-sm text-secondary mt-1">{subtitle}</p>}
        {lastUpdated && (
          <p className="text-xs text-muted font-mono mt-2">
            Last updated: {lastUpdated}
          </p>
        )}
      </div>
      <div className="flex items-center gap-3">
        {actions}
        {onRefresh && (
          <Button variant="ghost" size="sm" onClick={onRefresh}>
            Refresh
          </Button>
        )}
      </div>
    </header>
  );
}