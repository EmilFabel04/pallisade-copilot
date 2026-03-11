/**
 * In-memory fetch cache with stale-while-revalidate.
 *
 * On first call: fetches normally, caches the JSON result.
 * On subsequent calls within TTL: returns cached data instantly (no loading flash).
 * After TTL: returns stale data immediately, revalidates in background.
 *
 * Cache is keyed by URL, so pipeline-scoped URLs naturally get separate entries.
 */

interface CacheEntry {
  data: unknown;
  timestamp: number;
  url: string;
}

const cache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<Response>>();

const DEFAULT_TTL = 30_000; // 30 seconds — data considered fresh
const STALE_TTL = 120_000; // 2 minutes — stale data still returned while revalidating

/**
 * Drop-in replacement for `fetch()` with caching for GET requests.
 * Returns a Response-like object whose `.json()` returns cached data when available.
 *
 * @param url - The fetch URL
 * @param options - Standard fetch options (POST/PUT/DELETE bypass cache)
 * @param ttl - Fresh TTL in ms (default 30s)
 */
export async function cachedFetch(
  url: string,
  options?: RequestInit,
  ttl: number = DEFAULT_TTL,
): Promise<Response> {
  // Only cache GET requests
  const method = options?.method?.toUpperCase() || 'GET';
  if (method !== 'GET') {
    return fetch(url, options);
  }

  const now = Date.now();
  const entry = cache.get(url);

  // Fresh cache hit — return immediately
  if (entry && now - entry.timestamp < ttl) {
    return makeCachedResponse(entry.data);
  }

  // Stale cache hit — return stale data, revalidate in background
  if (entry && now - entry.timestamp < STALE_TTL) {
    revalidate(url, options, ttl);
    return makeCachedResponse(entry.data);
  }

  // No cache or expired — fetch and wait
  return fetchAndCache(url, options, ttl);
}

/**
 * Invalidate cache entries matching a URL prefix.
 * Call this after mutations (POST/PUT/DELETE) to clear stale data.
 *
 * @param urlPrefix - Entries whose URL starts with this are removed
 */
export function invalidateCache(urlPrefix?: string) {
  if (!urlPrefix) {
    cache.clear();
    return;
  }
  cache.forEach((_, key) => {
    if (key.startsWith(urlPrefix)) {
      cache.delete(key);
    }
  });
}

// --- Internal helpers ---

async function fetchAndCache(
  url: string,
  options: RequestInit | undefined,
  ttl: number,
): Promise<Response> {
  // Deduplicate concurrent requests to the same URL
  let pending = inflight.get(url);
  if (!pending) {
    pending = fetch(url, options);
    inflight.set(url, pending);
  }

  try {
    const response = await pending;
    inflight.delete(url);

    if (!response.ok) {
      return response;
    }

    // Clone before reading body (response can only be read once)
    const clone = response.clone();
    const data = await clone.json();
    cache.set(url, { data, timestamp: Date.now(), url });
    // Return a new response with the same data
    return makeCachedResponse(data, response.status);
  } catch (err) {
    inflight.delete(url);
    throw err;
  }
}

function revalidate(url: string, options: RequestInit | undefined, ttl: number) {
  // Only one background revalidation per URL
  if (inflight.has(url)) return;
  fetchAndCache(url, options, ttl).catch(() => {
    // Background revalidation failure is silent — stale data still served
  });
}

function makeCachedResponse(data: unknown, status: number = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: 'OK',
    headers: new Headers({ 'content-type': 'application/json' }),
    json: () => Promise.resolve(data),
    text: () => Promise.resolve(JSON.stringify(data)),
    clone: () => makeCachedResponse(data, status),
    // Stubs for Response interface
    body: null,
    bodyUsed: false,
    arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
    blob: () => Promise.resolve(new Blob()),
    formData: () => Promise.resolve(new FormData()),
    redirected: false,
    type: 'basic' as ResponseType,
    url: '',
    bytes: () => Promise.resolve(new Uint8Array()),
  } as Response;
}
