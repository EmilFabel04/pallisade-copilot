'use client';

import { useState, useEffect } from 'react';

interface TypewriterTextProps {
  text: string;
  speed?: number;
  delay?: number;
  className?: string;
  onComplete?: () => void;
  cursor?: boolean;
}

export function TypewriterText({
  text,
  speed = 30,
  delay = 0,
  className = '',
  onComplete,
  cursor = true,
}: TypewriterTextProps) {
  const [displayedText, setDisplayedText] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [showCursor, setShowCursor] = useState(cursor);

  useEffect(() => {
    setDisplayedText('');
    setIsTyping(false);

    const delayTimer = setTimeout(() => {
      setIsTyping(true);
      let index = 0;

      const typeInterval = setInterval(() => {
        if (index < text.length) {
          setDisplayedText(text.slice(0, index + 1));
          index++;
        } else {
          clearInterval(typeInterval);
          setIsTyping(false);
          onComplete?.();
        }
      }, speed);

      return () => clearInterval(typeInterval);
    }, delay);

    return () => clearTimeout(delayTimer);
  }, [text, speed, delay, onComplete]);

  // Cursor blink effect
  useEffect(() => {
    if (!cursor) return;

    const blinkInterval = setInterval(() => {
      setShowCursor(prev => !prev);
    }, 500);

    return () => clearInterval(blinkInterval);
  }, [cursor]);

  return (
    <span className={className}>
      {displayedText}
      {cursor && (
        <span 
          className={`inline-block w-0.5 h-[1em] ml-0.5 bg-current align-middle transition-opacity ${
            showCursor && isTyping ? 'opacity-100' : 'opacity-0'
          }`}
        />
      )}
    </span>
  );
}

// Multi-line typewriter for logs/console style output
interface TypewriterLogProps {
  lines: Array<{
    text: string;
    type?: 'info' | 'success' | 'warning' | 'error' | 'data';
    prefix?: string;
  }>;
  speed?: number;
  lineDelay?: number;
  className?: string;
}

export function TypewriterLog({
  lines,
  speed = 20,
  lineDelay = 100,
  className = '',
}: TypewriterLogProps) {
  const [currentLine, setCurrentLine] = useState(0);
  const [completedLines, setCompletedLines] = useState<number[]>([]);

  const handleLineComplete = () => {
    setCompletedLines(prev => [...prev, currentLine]);
    if (currentLine < lines.length - 1) {
      setTimeout(() => setCurrentLine(prev => prev + 1), lineDelay);
    }
  };

  const getLineColor = (type?: string) => {
    switch (type) {
      case 'success': return 'text-emerald-400';
      case 'warning': return 'text-amber-400';
      case 'error': return 'text-red-400';
      case 'data': return 'text-blue-400';
      default: return 'text-[var(--text-tertiary)]';
    }
  };

  const getPrefix = (line: typeof lines[0]) => {
    if (line.prefix) return line.prefix;
    switch (line.type) {
      case 'success': return '✓';
      case 'warning': return '⚠';
      case 'error': return '✗';
      case 'data': return '→';
      default: return '›';
    }
  };

  return (
    <div className={`font-mono text-sm space-y-1 ${className}`}>
      {lines.map((line, idx) => {
        if (idx > currentLine) return null;
        const isComplete = completedLines.includes(idx);
        const isCurrent = idx === currentLine;

        return (
          <div key={idx} className={`flex items-start gap-2 ${getLineColor(line.type)}`}>
            <span className="opacity-50 flex-shrink-0">{getPrefix(line)}</span>
            {isComplete ? (
              <span>{line.text}</span>
            ) : isCurrent ? (
              <TypewriterText
                text={line.text}
                speed={speed}
                onComplete={handleLineComplete}
                cursor={true}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
