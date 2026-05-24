import React from 'react';
import { cn } from '../utils/cn';

export interface ColumnDef<T> {
  header: string;
  accessorKey: keyof T | string;
  cell?: (info: { row: T }) => React.ReactNode;
}

interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T>[];
  maxHeight?: string;
  isLoading?: boolean;
}

export function DataTable<T>({ data, columns, maxHeight = '400px', isLoading }: DataTableProps<T>) {
  return (
    <div className="card flex flex-col overflow-hidden" style={{ maxHeight }}>
      <div className="overflow-auto relative flex-1">
        <table className="w-full text-left text-sm whitespace-nowrap">
          <thead className="sticky top-0 bg-surface z-10 border-b border-border shadow-[0_1px_0_0_#1e1e1e]">
            <tr>
              {columns.map((col, idx) => (
                <th key={idx} className="px-4 py-3 text-xs uppercase tracking-wider text-muted font-medium bg-surface">
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {isLoading ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-muted">
                  Loading...
                </td>
              </tr>
            ) : data.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-muted">
                  No results found
                </td>
              </tr>
            ) : (
              data.map((row, rowIdx) => (
                <tr key={rowIdx} className="hover:bg-white/5 transition-colors">
                  {columns.map((col, colIdx) => (
                    <td key={colIdx} className="px-4 py-3 text-secondary font-mono">
                      {col.cell ? col.cell({ row }) : String((row as any)[col.accessorKey])}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}