import '../globals.css';
import { SessionProvider } from '../../components/providers/SessionProvider';

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen relative overflow-hidden flex flex-col bg-[var(--bg)]">
      <div className="orb orb-1" />
      <div className="orb orb-2" />
      <div className="absolute inset-0 pointer-events-none overflow-hidden">
        <div
          className="absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 w-[1400px] h-[700px] opacity-[0.03]"
          style={{
            background:
              'repeating-linear-gradient(0deg, currentColor 0 1px, transparent 1px 80px), repeating-linear-gradient(90deg, currentColor 0 1px, transparent 1px 80px)',
            color: 'rgb(139,11,16)',
            transform: 'perspective(1200px) rotateX(65deg) translateZ(-150px)',
          }}
        />
      </div>
      <div className="flex-1 flex items-center justify-center px-4 py-8">
        <SessionProvider>{children}</SessionProvider>
      </div>
    </div>
  );
}
