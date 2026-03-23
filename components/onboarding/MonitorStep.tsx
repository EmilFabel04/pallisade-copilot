'use client';

interface MonitorStepProps {
  pipelineName: string;
  warehouseType: string;
  onComplete: () => void;
  onSkip: () => void;
  onBack: () => void;
}

export function MonitorStep({
  pipelineName,
  warehouseType,
  onComplete,
  onSkip,
  onBack,
}: MonitorStepProps) {
  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-2xl font-bold">Set Up Monitoring</h2>
        <p className="text-[var(--muted)] mt-2">
          Your pipeline &ldquo;{pipelineName}&rdquo; ({warehouseType}) is ready to configure
        </p>
      </div>

      <div className="auth-card">
        <div className="bg-[var(--overlay-bg)] border border-[var(--subtle-border)] rounded-xl p-5 space-y-4">
          <h3 className="text-sm font-semibold text-[var(--text)]">Next steps after setup:</h3>
          <div className="space-y-3">
            {[
              { step: '1', text: 'Add your warehouse credentials in pipeline settings' },
              { step: '2', text: 'Pick tables to monitor for freshness, volume, or schema changes' },
              { step: '3', text: 'Run your first scan and see results in real-time' },
            ].map((item) => (
              <div key={item.step} className="flex items-start gap-3">
                <div className="w-6 h-6 rounded-full bg-[var(--accent)] text-white flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
                  {item.step}
                </div>
                <p className="text-sm text-[var(--text)]">{item.text}</p>
              </div>
            ))}
          </div>
        </div>

        <div className="flex gap-3 mt-5">
          <button
            onClick={onBack}
            className="btn w-full justify-center flex-1"
          >
            Back
          </button>
          <button
            onClick={onComplete}
            className="btn btn-elevated w-full justify-center flex-1"
          >
            Go to Dashboard
          </button>
        </div>
      </div>

      <button
        onClick={onSkip}
        className="w-full text-sm text-[var(--muted)] hover:text-[var(--text)] transition-colors py-2"
      >
        Skip for now
      </button>
    </div>
  );
}
