import { getServerSession } from 'next-auth';
import { redirect } from 'next/navigation';
import { authOptions } from '../../lib/auth';
import { Sidebar } from '../../components/dashboard/Sidebar';
import { DashboardHeader } from '../../components/dashboard/Header';
import { SessionProvider } from '../../components/providers/SessionProvider';
import { DashboardProviders } from '../../components/providers/DashboardProviders';
import { SidebarProvider } from '../../contexts/SidebarContext';
import '../globals.css';

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const session = await getServerSession(authOptions);

  if (!session) {
    redirect('/login');
  }

  return (
    <SessionProvider session={session}>
      <SidebarProvider>
        <DashboardProviders>
          <div className="dashboard-layout">
            <Sidebar />
            <div className="dashboard-main">
              <DashboardHeader />
              <main className="dashboard-content">
                {children}
              </main>
            </div>
          </div>
        </DashboardProviders>
      </SidebarProvider>
    </SessionProvider>
  );
}

