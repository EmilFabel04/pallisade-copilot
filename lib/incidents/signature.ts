import { createHash } from 'crypto';

export interface SignatureInput {
  monitorType: string;     // e.g. 'FRESHNESS'
  breachClass: string;     // e.g. 'over-threshold' | 'under-threshold' | 'schema-changed' | 'unknown'
}

export function fallbackSignature(input: SignatureInput): string {
  const key = `${input.monitorType.toLowerCase()}|${input.breachClass.toLowerCase()}`;
  const hash = createHash('sha1').update(key).digest('hex').slice(0, 8);
  // Slug: monitorType (lowercase) + 8-char hash, capped at 32 chars
  const prefix = input.monitorType.toLowerCase().replace(/[^a-z0-9]+/g, '-').slice(0, 22);
  return `${prefix}-${hash}`;
}
