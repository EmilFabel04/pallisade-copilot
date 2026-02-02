'use client';

import { useSidebar } from '@/contexts/SidebarContext';

export function DashboardMain({ children }: { children: React.ReactNode }) {
  const { isCollapsed } = useSidebar();

  return (
    <div 
      className={`
        flex flex-col min-h-screen
        transition-all duration-300 ease-in-out
        ${isCollapsed ? 'ml-[68px]' : 'ml-[240px]'}
      `}
    >
      {children}
    </div>
  );
}
