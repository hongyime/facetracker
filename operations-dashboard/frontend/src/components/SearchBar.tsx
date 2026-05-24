import React from 'react';
import { Search } from 'lucide-react';
import { cn } from '../utils/cn';

interface SearchBarProps {
  placeholder?: string;
  onSearch?: (value: string) => void;
  className?: string;
}

export function SearchBar({ placeholder = "Search...", onSearch, className }: SearchBarProps) {
  return (
    <div className={cn("relative flex items-center", className)}>
      <Search className="absolute left-3 w-4 h-4 text-muted" />
      <input
        type="text"
        placeholder={placeholder}
        onChange={(e) => onSearch?.(e.target.value)}
        className="w-full h-10 pl-10 pr-4 bg-white/5 border border-border rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-white/20 transition-all placeholder:text-muted"
      />
    </div>
  );
}