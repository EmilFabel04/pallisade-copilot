'use client';

import { useState, useCallback, useRef } from 'react';
import { UIArtifact } from '@/types/artifacts';

export interface StreamingToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
  result?: {
    success: boolean;
    data?: any;
    error?: string;
  };
  isExecuting?: boolean;
}

export interface PendingConfirmation {
  toolUseId: string;
  toolName: string;
  arguments: Record<string, unknown>;
  description: string;
}

export interface StreamingMessage {
  id: string;
  role: 'assistant';
  content: string;
  isStreaming: boolean;
  toolCalls: StreamingToolCall[];
  pendingConfirmation?: PendingConfirmation;
  inputTokens: number;
  outputTokens: number;
  stopReason: string;
  artifacts: UIArtifact[];
}

interface PendingToolCall {
  toolUseId: string;
  toolName: string;
  arguments: Record<string, unknown>;
}

interface SendMessageOptions {
  sessionId?: string;
  pipelineStackId?: string;
  model: string;
  mode: string;
  nodeIds?: string[];
  referencedEntities?: string[];
  confirmedToolIds?: string[];
  pendingToolCall?: PendingToolCall;
}

interface SendMessageResult {
  sessionId: string | null;
  stopReason: string;
}

export function useStreamingChat() {
  const [streamingMessage, setStreamingMessage] = useState<StreamingMessage | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const abort = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setStreamingMessage(prev =>
      prev ? { ...prev, isStreaming: false } : prev
    );
  }, []);

  const sendMessage = useCallback(async (
    message: string,
    options: SendMessageOptions,
  ): Promise<SendMessageResult> => {
    // Cancel any existing stream
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    const messageId = `stream_${Date.now()}`;

    setStreamingMessage({
      id: messageId,
      role: 'assistant',
      content: '',
      isStreaming: true,
      toolCalls: [],
      inputTokens: 0,
      outputTokens: 0,
      stopReason: '',
      artifacts: [],
    });

    let sessionId: string | null = null;
    let stopReason = '';

    try {
      const response = await fetch('/api/copilot/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message,
          stream: true,
          sessionId: options.sessionId,
          pipelineStackId: options.pipelineStackId,
          model: options.model,
          mode: options.mode,
          node_ids: options.nodeIds,
          referenced_entities: options.referencedEntities,
          confirmed_tool_ids: options.confirmedToolIds,
          pending_tool_call: options.pendingToolCall ? {
            tool_use_id: options.pendingToolCall.toolUseId,
            tool_name: options.pendingToolCall.toolName,
            arguments: options.pendingToolCall.arguments,
          } : undefined,
        }),
        signal: abortController.signal,
      });

      if (!response.ok || !response.body) {
        const errorText = await response.text();
        setStreamingMessage(prev =>
          prev ? { ...prev, isStreaming: false, content: `Error: ${errorText}` } : prev
        );
        return { sessionId: null, stopReason: 'error' };
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop()!; // keep incomplete event in buffer

        for (const eventStr of events) {
          if (!eventStr.trim()) continue;

          const lines = eventStr.split('\n');
          const eventLine = lines.find(l => l.startsWith('event: '));
          const dataLine = lines.find(l => l.startsWith('data: '));

          if (!eventLine || !dataLine) continue;

          const eventType = eventLine.slice(7);
          let data: any;
          try {
            data = JSON.parse(dataLine.slice(6));
          } catch (parseErr) {
            console.warn('[useStreamingChat] Failed to parse SSE data:', dataLine.slice(6, 100), parseErr);
            continue;
          }

          switch (eventType) {
            case 'session_info':
              sessionId = data.sessionId;
              break;

            case 'text_delta':
              setStreamingMessage(prev =>
                prev ? { ...prev, content: prev.content + (data.content || '') } : prev
              );
              break;

            case 'tool_call_start':
              setStreamingMessage(prev => {
                if (!prev) return prev;
                return {
                  ...prev,
                  toolCalls: [
                    ...prev.toolCalls,
                    {
                      id: data.tool_use_id,
                      name: data.tool_name,
                      arguments: data.arguments || {},
                      isExecuting: true,
                    },
                  ],
                };
              });
              break;

            case 'tool_call_result':
              setStreamingMessage(prev => {
                if (!prev) return prev;
                return {
                  ...prev,
                  toolCalls: prev.toolCalls.map(tc =>
                    tc.id === data.tool_use_id
                      ? { ...tc, result: data.result, isExecuting: false }
                      : tc
                  ),
                };
              });
              break;

            case 'tool_confirmation_required':
              setStreamingMessage(prev =>
                prev ? {
                  ...prev,
                  pendingConfirmation: {
                    toolUseId: data.tool_use_id,
                    toolName: data.tool_name,
                    arguments: data.arguments || {},
                    description: data.description || '',
                  },
                } : prev
              );
              break;

            case 'done':
              stopReason = data.stop_reason || 'end_turn';
              setStreamingMessage(prev =>
                prev ? {
                  ...prev,
                  isStreaming: false,
                  inputTokens: data.input_tokens || 0,
                  outputTokens: data.output_tokens || 0,
                  stopReason,
                } : prev
              );
              break;

            case 'ui_artifact': {
              const artifact = data as UIArtifact;
              setStreamingMessage(prev => prev ? {
                ...prev,
                artifacts: [...prev.artifacts, artifact],
              } : prev);
              break;
            }

            case 'error':
              setStreamingMessage(prev =>
                prev ? {
                  ...prev,
                  isStreaming: false,
                  content: prev.content + `\n\nError: ${data.message}`,
                  stopReason: 'error',
                } : prev
              );
              stopReason = 'error';
              break;
          }
        }
      }
      // Safety net: if stream ended without a 'done' or 'error' event,
      // ensure isStreaming is set to false so the UI doesn't get stuck loading.
      setStreamingMessage(prev => {
        if (prev && prev.isStreaming) {
          console.warn('[useStreamingChat] Stream ended without done/error event — forcing isStreaming=false');
          return { ...prev, isStreaming: false, stopReason: stopReason || 'stream_ended' };
        }
        return prev;
      });
      if (!stopReason) stopReason = 'stream_ended';
    } catch (err: any) {
      if (err.name === 'AbortError') {
        stopReason = 'aborted';
        setStreamingMessage(prev =>
          prev ? { ...prev, isStreaming: false, stopReason: 'aborted' } : prev
        );
      } else {
        console.error('[useStreamingChat] Error:', err);
        setStreamingMessage(prev =>
          prev ? {
            ...prev,
            isStreaming: false,
            content: prev.content + `\n\nError: ${err.message}`,
            stopReason: 'error',
          } : prev
        );
        stopReason = 'error';
      }
    }

    abortControllerRef.current = null;
    return { sessionId, stopReason };
  }, []);

  const clearStreamingMessage = useCallback(() => {
    setStreamingMessage(null);
  }, []);

  return {
    streamingMessage,
    setStreamingMessage,
    clearStreamingMessage,
    sendMessage,
    abort,
  };
}
