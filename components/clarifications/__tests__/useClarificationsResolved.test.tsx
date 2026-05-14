/**
 * @jest-environment jsdom
 */
import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { useClarificationsResolved } from '../useClarificationsResolved';
import { ClarificationProvider } from '../ClarificationProvider';
import * as client from '@/lib/clarifications/client';
import * as pipelineCtx from '@/contexts/PipelineContext';

jest.mock('@/contexts/PipelineContext', () => ({
  usePipeline: jest.fn(),
}));
jest.mock('@/lib/clarifications/client', () => ({
  listContextRequests: jest.fn(),
  fetchContextRequest: jest.fn(),
  dismissContextRequest: jest.fn(),
}));

(pipelineCtx.usePipeline as jest.Mock).mockReturnValue({ selectedPipelineId: 'p1' });


describe('useClarificationsResolved', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (pipelineCtx.usePipeline as jest.Mock).mockReturnValue({ selectedPipelineId: 'p1' });
  });

  it('does not fire when ids is empty', () => {
    (client.listContextRequests as jest.Mock).mockResolvedValue([]);
    const cb = jest.fn();
    renderHook(() => useClarificationsResolved([], cb), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <ClarificationProvider>{children}</ClarificationProvider>
      ),
    });
    expect(cb).not.toHaveBeenCalled();
  });

  it('fires with the answers map when every id transitions to answered', async () => {
    (client.listContextRequests as jest.Mock).mockResolvedValue([
      { id: 'a', kind: 'timestamp_choice', scope_type: 'node', scope_ref: 'x', payload: {}, status: 'answered', priority: 'normal', created_at: 't', dismissed_until: null },
      { id: 'b', kind: 'timestamp_choice', scope_type: 'node', scope_ref: 'y', payload: {}, status: 'answered', priority: 'normal', created_at: 't', dismissed_until: null },
    ]);
    (client.fetchContextRequest as jest.Mock).mockImplementation(async (id: string) => ({
      id, status: 'answered', answer: { column: id === 'a' ? 'loaded_at' : 'date' },
    }));

    const cb = jest.fn();
    renderHook(() => useClarificationsResolved(['a', 'b'], cb), {
      wrapper: ({ children }: { children: React.ReactNode }) => (
        <ClarificationProvider>{children}</ClarificationProvider>
      ),
    });

    await waitFor(() => expect(cb).toHaveBeenCalledTimes(1));
    expect(cb).toHaveBeenCalledWith({
      a: { column: 'loaded_at' },
      b: { column: 'date' },
    });
  });
});
