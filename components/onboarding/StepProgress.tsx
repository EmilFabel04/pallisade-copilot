'use client';

const STEPS = [
  { label: 'Profile', number: 1 },
  { label: 'Company', number: 2 },
  { label: 'Warehouse', number: 3 },
  { label: 'Monitor', number: 4 },
];

interface StepProgressProps {
  currentStep: number;
  completedSteps: number;
}

export function StepProgress({ currentStep, completedSteps }: StepProgressProps) {
  return (
    <div className="flex items-center justify-center gap-3 mb-8">
      {STEPS.map((step, i) => {
        const isCompleted = step.number <= completedSteps;
        const isCurrent = step.number === currentStep;
        return (
          <div key={step.number} className="flex items-center gap-3">
            {i > 0 && (
              <div
                className={`w-8 h-[2px] ${
                  step.number <= completedSteps + 1
                    ? 'bg-[var(--accent)]'
                    : 'bg-[var(--overlay-medium)]'
                }`}
              />
            )}
            <div className="flex items-center gap-2">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-semibold transition-colors ${
                  isCompleted || isCurrent
                    ? 'bg-[var(--accent)] text-white'
                    : 'bg-[var(--overlay-medium)] text-[var(--muted)]'
                }`}
              >
                {isCompleted && step.number < currentStep ? '✓' : step.number}
              </div>
              <span
                className={`text-[12px] font-medium hidden sm:inline ${
                  isCurrent ? 'text-[var(--text)]' : 'text-[var(--muted)]'
                }`}
              >
                {step.label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
