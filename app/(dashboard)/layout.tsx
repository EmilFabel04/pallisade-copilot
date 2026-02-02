import { getServerSession } from 'next-auth';
import { redirect } from 'next/navigation';
import { authOptions } from '../../lib/auth';
import { Sidebar } from '../../components/dashboard/Sidebar';
import { DashboardHeader } from '../../components/dashboard/Header';
import { SessionProvider } from '../../components/providers/SessionProvider';
import { DashboardProviders } from '../../components/providers/DashboardProviders';
import { SidebarProvider } from '../../contexts/SidebarContext';
import { DashboardMain } from '../../components/dashboard/DashboardMain';
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
          <div className="min-h-screen bg-[#030303]">
            <Sidebar />
            <DashboardMain>
              <DashboardHeader />
              <main className="flex-1 p-6 overflow-y-auto">
                {children}
              </main>
            </DashboardMain>
          </div>
        </DashboardProviders>
      </SidebarProvider>
    </SessionProvider>
  );
}
