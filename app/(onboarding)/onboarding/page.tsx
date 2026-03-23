'use client';

import { useState, useEffect } from 'react';
import { useSession } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { StepProgress } from '../../../components/onboarding/StepProgress';
import { ProfileStep } from '../../../components/onboarding/ProfileStep';
import { CompanyStep } from '../../../components/onboarding/CompanyStep';
import { WarehouseStep } from '../../../components/onboarding/WarehouseStep';
import { MonitorStep } from '../../../components/onboarding/MonitorStep';

export default function OnboardingPage() {
  const { data: session, status, update } = useSession();
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(1);
  const [completedSteps, setCompletedSteps] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [initialDataLoaded, setInitialDataLoaded] = useState(false);

  // Data from previous steps (for passing to later steps)
  const [userName, setUserName] = useState('');
  const [orgName, setOrgName] = useState('');
  const [pipelineName, setPipelineName] = useState('');
  const [warehouseType, setWarehouseType] = useState('');
  const [warehouseConnected, setWarehouseConnected] = useState(false);

  useEffect(() => {
    if (status === 'unauthenticated') {
      router.push('/login');
    }
  }, [status, router]);

  // Load initial data — resume from last step, redirect if already completed
  useEffect(() => {
    if (status !== 'authenticated' || initialDataLoaded) return;

    async function loadOnboardingState() {
      // Check onboarding progress from DB
      try {
        const res = await fetch('/api/user/onboarding');
        if (res.ok) {
          const data = await res.json();
          if (data.user?.onboardingCompleted) {
            router.push('/dashboard');
            return;
          }
          const savedStep = data.user?.onboardingStep ?? 0;
          if (savedStep > 0) {
            setCompletedSteps(savedStep);
            setCurrentStep(savedStep + 1);
          }
        }
      } catch {
        // Fresh start
      }

      // Pre-fill name from session
      setUserName((session?.user as any)?.name || '');

      // Load org name if exists
      try {
        const orgRes = await fetch('/api/organization');
        if (orgRes.ok) {
          const data = await orgRes.json();
          if (data.organization?.name) {
            setOrgName(data.organization.name);
          }
        }
      } catch {
        // No org yet
      }

      setInitialDataLoaded(true);
    }

    loadOnboardingState();
  }, [status, session, initialDataLoaded]);

  async function saveStep(step: number, completed = false) {
    await fetch('/api/user/onboarding', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ step, completed }),
    });
  }

  async function handleProfileComplete(data: { name: string; timezone: string; role: string }) {
    setIsLoading(true);
    try {
      const res = await fetch('/api/user/profile', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error('Failed to save profile');

      setUserName(data.name);
      await saveStep(1);
      setCompletedSteps(1);
      setCurrentStep(2);
    } catch (err) {
      console.error('Profile save error:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleCompanyComplete(data: {
    name: string;
    companySize: string;
    industry?: string;
    dataTeamSize?: string;
  }) {
    setIsLoading(true);
    try {
      const res = await fetch('/api/organization', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error('Failed to save company');

      setOrgName(data.name);
      await saveStep(2);
      setCompletedSteps(2);
      setCurrentStep(3);
    } catch (err) {
      console.error('Company save error:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleWarehouseComplete(data: {
    pipelineName: string;
    warehouseType: string;
  }) {
    setIsLoading(true);
    try {
      // Create pipeline
      const pipelineRes = await fetch('/api/pipeline', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: data.pipelineName }),
      });
      if (!pipelineRes.ok) throw new Error('Failed to create pipeline');

      setPipelineName(data.pipelineName);
      setWarehouseType(data.warehouseType);
      setWarehouseConnected(true);
      await saveStep(3);
      setCompletedSteps(3);
      setCurrentStep(4);
    } catch (err) {
      console.error('Warehouse setup error:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleFinish() {
    setIsLoading(true);
    try {
      await saveStep(4, true);
      // Refresh session to pick up timezone
      await update();
      router.push('/dashboard');
      router.refresh();
    } catch (err) {
      console.error('Finish error:', err);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSkipWarehouse() {
    await saveStep(4, true);
    await update();
    router.push('/dashboard');
    router.refresh();
  }

  async function handleSkipMonitor() {
    await saveStep(4, true);
    await update();
    router.push('/dashboard');
    router.refresh();
  }

  if (status === 'loading' || !initialDataLoaded) {
    return (
      <div className="w-full max-w-md text-center">
        <p className="text-[var(--muted)]">Loading...</p>
      </div>
    );
  }

  return (
    <div className="w-full max-w-md">
      <div className="text-center mb-6">
        <img src="/pallisade_emblem.svg" alt="Pallisade" className="w-14 h-14 mx-auto mb-3" />
      </div>
      <StepProgress currentStep={currentStep} completedSteps={completedSteps} />

      {currentStep === 1 && (
        <ProfileStep
          initialName={userName}
          onComplete={handleProfileComplete}
          isLoading={isLoading}
        />
      )}

      {currentStep === 2 && (
        <CompanyStep
          initialName={orgName}
          onComplete={handleCompanyComplete}
          onBack={() => setCurrentStep(1)}
          isLoading={isLoading}
        />
      )}

      {currentStep === 3 && (
        <WarehouseStep
          onComplete={handleWarehouseComplete}
          onSkip={handleSkipWarehouse}
          onBack={() => setCurrentStep(2)}
          isLoading={isLoading}
        />
      )}

      {currentStep === 4 && (
        <MonitorStep
          pipelineName={pipelineName}
          warehouseType={warehouseType}
          onComplete={handleFinish}
          onSkip={handleSkipMonitor}
          onBack={() => setCurrentStep(3)}
        />
      )}
    </div>
  );
}
