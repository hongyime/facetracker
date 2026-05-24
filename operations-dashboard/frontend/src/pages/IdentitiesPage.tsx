import React from 'react';
import { useQuery } from '@tanstack/react-query';
import axios from 'axios';
import { Header } from '../components/Header';
import { DataTable } from '../components/DataTable';
import { StatusBadge } from '../components/StatusBadge';

const API_BASE = 'http://localhost:5151/api/v1';

export default function IdentitiesPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['identities'],
    queryFn: async () => {
      const res = await axios.get(`${API_BASE}/identities`);
      return res.data;
    },
  });

  return (
    <>
      <Header 
        title="Identities" 
        subtitle="Manage discovered face clusters and verified persons."
      />

      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-12">
          <DataTable 
            isLoading={isLoading}
            columns={[
              { header: 'ID', accessorKey: 'identity_id' },
              { header: 'Name', accessorKey: 'name', cell: ({ row }) => (row as any).name || 'Unknown' },
              { header: 'Face Count', accessorKey: 'face_count' },
              { header: 'Last Updated', accessorKey: 'updated_at' },
              { header: 'Status', accessorKey: 'status', cell: ({ row }) => (
                <StatusBadge 
                  label={(row as any).is_verified ? 'Verified' : 'Unverified'} 
                  status={(row as any).is_verified ? 'online' : 'warning'} 
                />
              )},
            ]}
            data={data?.identities || []}
          />
        </div>
      </div>
    </>
  );
}