import React from 'react';
import { cn } from '../utils/cn';
import { useHealthWS } from '../hooks/useHealthWS';

interface SidebarItem {
  name: string;
  href: string;
  icon?: React.ReactNode;
}

interface SidebarProps {
  items: SidebarItem[];
  activeRoute: string;
  onNavigate: (href: string) => void;
}

export function Sidebar({ items, activeRoute, onNavigate }: SidebarProps) {
  const { isConnected } = useHealthWS();

  return (
    <aside className="fixed left-0 top-0 bottom-0 w-56 bg-surface border-r border-border flex flex-col">
      <div className="p-4 border-b border-border flex items-center justify-between">
        <h1 className="text-sm font-bold tracking-widest uppercase text-white">FT</h1>
      </div>
      
      <nav className="flex-1 overflow-y-auto p-3 space-y-1">
        {items.map((item) => (
          <button
            key={item.href}
            onClick={() => onNavigate(item.href)}
            className={cn(
              "w-full flex items-center gap-3 px-3 py-2 text-sm font-medium rounded-md transition-colors",
              activeRoute === item.href 
                ? "bg-white text-black" 
                : "text-secondary hover:bg-white/10 hover:text-white"
            )}
          >
            {item.icon}
            {item.name}
          </button>
        ))}
      </nav>

      <div className="p-4 border-t border-border">
        <div className="flex items-center gap-2 text-xs font-mono text-muted">
          <div className={cn("w-2 h-2 rounded-full", isConnected ? "bg-success" : "bg-error")} />
          WS {isConnected ? 'Connected' : 'Disconnected'}
        </div>
      </div>
    </aside>
  );
}