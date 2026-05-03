'use client';

import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';

import CustomSourceWizard from '@/app/(dashboard)/dashboard/integrations/connect/custom-source/CustomSourceWizard';

interface CustomSourceWizardModalProps {
  onClose: () => void;
}

export default function CustomSourceWizardModal({ onClose }: CustomSourceWizardModalProps) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  if (!mounted) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 sm:p-8"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-3xl rounded-xl border border-[var(--subtle-border)] bg-[var(--surface)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <CustomSourceWizard onClose={onClose} />
      </div>
    </div>,
    document.body,
  );
}
