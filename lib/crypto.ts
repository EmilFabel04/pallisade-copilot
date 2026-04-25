import crypto from 'crypto';

const ALGORITHM = 'aes-256-gcm';
const IV_LENGTH = 16;
const AUTH_TAG_LENGTH = 16;
const KEY_BYTES = 32;

let warnedAboutDevKey = false;

function getEncryptionKey(): Buffer {
  const key = process.env.ENCRYPTION_KEY;
  if (key) {
    const buf = Buffer.from(key, 'hex');
    if (buf.length !== KEY_BYTES) {
      throw new Error(
        `ENCRYPTION_KEY must be ${KEY_BYTES} bytes / ${KEY_BYTES * 2} hex chars; got ${buf.length} bytes.`,
      );
    }
    return buf;
  }
  if (process.env.NODE_ENV === 'production') {
    throw new Error(
      'ENCRYPTION_KEY is not set. Refusing to use the deterministic dev key in production. ' +
        'Generate with: openssl rand -hex 32',
    );
  }
  if (!warnedAboutDevKey) {
    console.warn(
      '[security] ENCRYPTION_KEY is unset — using deterministic dev key. ' +
        'Generate with `openssl rand -hex 32`. Anything encrypted with the dev ' +
        'key will be unreadable after you set ENCRYPTION_KEY.',
    );
    warnedAboutDevKey = true;
  }
  return crypto.scryptSync('pallisade-dev-key', 'salt', KEY_BYTES);
}

/**
 * Encrypt sensitive data (like API credentials)
 */
export function encrypt(text: string): string {
  const key = getEncryptionKey();
  const iv = crypto.randomBytes(IV_LENGTH);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv);

  let encrypted = cipher.update(text, 'utf8', 'hex');
  encrypted += cipher.final('hex');

  const authTag = cipher.getAuthTag();

  // Combine iv + authTag + encrypted data
  return iv.toString('hex') + authTag.toString('hex') + encrypted;
}

/**
 * Decrypt sensitive data
 */
export function decrypt(encryptedData: string): string {
  const key = getEncryptionKey();

  // Extract iv, authTag, and encrypted text
  const iv = Buffer.from(encryptedData.slice(0, IV_LENGTH * 2), 'hex');
  const authTag = Buffer.from(encryptedData.slice(IV_LENGTH * 2, IV_LENGTH * 2 + AUTH_TAG_LENGTH * 2), 'hex');
  const encrypted = encryptedData.slice(IV_LENGTH * 2 + AUTH_TAG_LENGTH * 2);

  const decipher = crypto.createDecipheriv(ALGORITHM, key, iv);
  decipher.setAuthTag(authTag);

  let decrypted = decipher.update(encrypted, 'hex', 'utf8');
  decrypted += decipher.final('utf8');

  return decrypted;
}

/**
 * Hash sensitive data (one-way, for comparison)
 */
export function hash(text: string): string {
  return crypto.createHash('sha256').update(text).digest('hex');
}

/**
 * Generate a secure random token
 */
export function generateToken(length: number = 32): string {
  return crypto.randomBytes(length).toString('hex');
}

