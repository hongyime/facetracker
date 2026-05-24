import React from 'react';
import { Header } from '../components/Header';
import { SearchBar } from '../components/SearchBar';

export default function SearchPage() {
  return (
    <>
      <Header 
        title="Face Search" 
        subtitle="Search for faces across the entire indexed collection."
      />

      <div className="grid grid-cols-12 gap-3">
        <div className="col-span-12">
          <div className="card">
            <span className="text-xs uppercase text-muted mb-4 block font-medium tracking-wider">Search Engine</span>
            <SearchBar placeholder="Search by name, ID or metadata..." />
            <div className="mt-8 text-center py-12 border-2 border-dashed border-border rounded-lg">
              <p className="text-muted">Enter a search query or upload an image to start searching.</p>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}