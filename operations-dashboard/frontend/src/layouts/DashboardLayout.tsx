import React from 'react';
import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Sidebar } from '../components/Sidebar';

const SIDEBAR_ITEMS = [
  { name: 'Indexing', href: '/' },
  { name: 'Identities', href: '/identities' },
  { name: 'Search', href: '/search' },
];

export default function DashboardLayout() {
  const navigate = useNavigate();
  const location = useLocation();

  return (
    <div className="min-h-screen bg-background">
      <Sidebar 
        items={SIDEBAR_ITEMS} 
        activeRoute={location.pathname} 
        onNavigate={(href) => navigate(href)} 
      />
      
      {/* Added pl-64 for more gap (sidebar is 56) and pr-8 for right side padding */}
      <main className="pl-64 pr-8 py-8">
        <Outlet />
      </main>
    </div>
  );
}