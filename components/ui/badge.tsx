import * as React from 'react';
import { cn } from '../../lib/utils';

export function Badge({ className, ...props }: React.HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border border-[rgba(139,11,16,0.55)] px-2 py-0.5 text-xs font-medium text-white/90',
        className
      )}
      {...props}
    />
  );
}

