import React from 'react';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { Header } from '../components/Header';
import { MetricCard } from '../components/MetricCard';
import { DataTable } from '../components/DataTable';
import { StatusBadge } from '../components/StatusBadge';

// Explicit API URL to avoid confusion
const API_BASE = 'http://localhost:5151/api/v1';

export default function IndexingPage() {
  const { data: stats } = useQuery({
    queryKey: ['stats'],
    queryFn: async () => {
      const res = await axios.get(`${API_BASE}/stats`);
      return res.data;
    },
    refetchInterval: 5000,
  });

  const { data: progress } = useQuery({
    queryKey: ['progress'],
    queryFn: async () => {
      const res = await axios.get(`${API_BASE}/stats/scan-progress`);
      return res.data;
    },
    refetchInterval: 2000,
  });

  const progressPercent = progress?.progress_percent !== undefined ? progress.progress_percent : 0;

  return (
    <>
      <Header 
        title="Indexing Control" 
        subtitle="Monitor drive scans and real-time processing pipeline."
        onRefresh={() => window.location.reload()}
      />

      <div className="grid grid-cols-12 gap-3 mb-6">
        <div className="col-span-3">
          <MetricCard label="Total Faces" value={stats?.total_faces ?? 0} />
        </div>
        <div className="col-span-3">
          <MetricCard label="Total Images" value={stats?.total_images ?? 0} />
        </div>
        <div className="col-span-3">
          <MetricCard label="Total Videos" value={stats?.total_videos ?? 0} />
        </div>
        <div className="col-span-3">
          <div className="card h-full flex flex-col justify-center">
            <span className="text-xs uppercase text-muted mb-2 font-medium tracking-wider">System Status</span>
            <StatusBadge 
              label={progress?.is_scanning ? "Indexing..." : "Idle"} 
              status={progress?.is_scanning ? "processing" : "online"} 
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-12">
          <h3 className="text-sm font-medium text-secondary mb-3 uppercase tracking-wider">Pipeline Metrics</h3>
          <DataTable 
            columns={[
              { header: 'Metric', accessorKey: 'metric' },
              { header: 'Value', accessorKey: 'value' },
              { header: 'Percentage', accessorKey: 'percent' },
            ]}
            data={[
              { metric: 'Files Scanned', value: progress?.files_scanned ?? 0, percent: progressPercent + '%' },
              { metric: 'Files Processed', value: progress?.files_processed ?? 0, percent: '-' },
              { metric: 'Files Total', value: progress?.files_total ?? 0, percent: '100%' },
              { metric: 'Indexing Workers', value: '2 Active', percent: '-' },
            ]}
          />
        </div>
        
        {progress?.current_file && (
          <div className="col-span-12 mt-3">
             <div className="card">
                <span className="text-xs uppercase text-muted mb-2 font-medium tracking-wider">Processing Current</span>
                <div className="text-sm font-mono text-secondary truncate">{progress.current_file}</div>
             </div>
          </div>
        )}
      </div>
    </>
  );
}