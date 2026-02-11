'use client';

import React from 'react';
import { Button } from '@/components/ui/button';

interface OnboardingBannerProps {
  status: 'NOT_STARTED' | 'IN_PROGRESS' | 'COMPLETED' | 'NEEDS_UPDATE';
  onStart: () => void;
  isLoading?: boolean;
}

export function OnboardingBanner({
  status,
  onStart,
  isLoading = false,
}: OnboardingBannerProps) {
  // Don't show banner if onboarding is completed
  if (status === 'COMPLETED') {
    return null;
  }

  const getMessage = () => {
    switch (status) {
      case 'NOT_STARTED':
        return {
          title: 'Teach me about your setup',
          description:
            'Answer a few questions so I can help without asking for clarification later.',
          buttonText: 'Start Onboarding',
        };
      case 'IN_PROGRESS':
        return {
          title: 'Continue onboarding',
          description:
            'You started telling me about your setup. Let\'s finish so I can help you better.',
          buttonText: 'Continue',
        };
      case 'NEEDS_UPDATE':
        return {
          title: 'New integration detected',
          description:
            'You\'ve connected new tools. Answer a few questions so I can help with them.',
          buttonText: 'Update Context',
        };
      default:
        return null;
    }
  };

  const message = getMessage();
  if (!message) return null;

  return (
    <div className="bg-indigo-500/10 border border-indigo-500/30 rounded-xl p-4 mb-4">
      <div className="flex items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          {/* Graduation cap icon */}
          <div className="w-10 h-10 rounded-lg bg-indigo-500/20 flex items-center justify-center flex-shrink-0">
            <svg
              className="w-5 h-5 text-indigo-400"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M4.26 10.147a60.436 60.436 0 00-.491 6.347A48.627 48.627 0 0112 20.904a48.627 48.627 0 018.232-4.41 60.46 60.46 0 00-.491-6.347m-15.482 0a50.57 50.57 0 00-2.658-.813A59.905 59.905 0 0112 3.493a59.902 59.902 0 0110.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.697 50.697 0 0112 13.489a50.702 50.702 0 017.74-3.342M6.75 15a.75.75 0 100-1.5.75.75 0 000 1.5zm0 0v-3.675A55.378 55.378 0 0112 8.443m-7.007 11.55A5.981 5.981 0 006.75 15.75v-1.5"
              />
            </svg>
          </div>
          <div>
            <h3 className="font-medium text-indigo-300 text-[14px]">
              {message.title}
            </h3>
            <p className="text-[13px] text-indigo-400/70 mt-0.5">
              {message.description}
            </p>
          </div>
        </div>
        <Button
          onClick={onStart}
          disabled={isLoading}
          variant="outline"
          size="sm"
          className="border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/20 hover:text-indigo-200 flex-shrink-0"
        >
          {isLoading ? (
            <>
              <div className="w-3.5 h-3.5 border-2 border-indigo-300/30 border-t-indigo-300 rounded-full animate-spin mr-2" />
              Starting...
            </>
          ) : (
            message.buttonText
          )}
        </Button>
      </div>
    </div>
  );
}
