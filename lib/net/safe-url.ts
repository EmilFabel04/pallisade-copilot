/**
 * SSRF guard: validate that a user-supplied URL points at an external host
 * before passing it to fetch(). Blocks private IPs, loopback, link-local,
 * and the cloud-metadata range on both IPv4 and IPv6.
 *
 * Use: `const u = await assertExternalUrl(userHost); await fetch(u, ...)`
 */
import { lookup } from "node:dns/promises";
import net from "node:net";

const PRIVATE_V4_RANGES: Array<[number, number, number, number, number]> = [
  [10, 0, 0, 0, 8],              // 10.0.0.0/8
  [127, 0, 0, 0, 8],             // loopback
  [169, 254, 0, 0, 16],          // link-local / IMDS (AWS, GCP, Azure)
  [172, 16, 0, 0, 12],           // 172.16.0.0/12
  [192, 168, 0, 0, 16],
  [192, 0, 2, 0, 24],            // TEST-NET-1
  [198, 18, 0, 0, 15],           // benchmarking
  [198, 51, 100, 0, 24],         // TEST-NET-2
  [203, 0, 113, 0, 24],          // TEST-NET-3
  [100, 64, 0, 0, 10],           // CG-NAT
  [0, 0, 0, 0, 8],               // 0.0.0.0/8 (this network)
];

function ipv4ToInt(ip: string): number | null {
  const parts = ip.split(".");
  if (parts.length !== 4) return null;
  let out = 0;
  for (const p of parts) {
    const n = Number(p);
    if (!Number.isInteger(n) || n < 0 || n > 255) return null;
    out = (out << 8) | n;
  }
  return out >>> 0;
}

function isPrivateV4(ip: string): boolean {
  const n = ipv4ToInt(ip);
  if (n === null) return false;
  for (const [a, b, c, d, prefix] of PRIVATE_V4_RANGES) {
    const net = (((a << 24) | (b << 16) | (c << 8) | d) >>> 0);
    const mask = prefix === 0 ? 0 : (~0 << (32 - prefix)) >>> 0;
    if ((n & mask) === (net & mask)) return true;
  }
  return false;
}

function isPrivateV6(ip: string): boolean {
  const lower = ip.toLowerCase();
  if (lower === "::1" || lower === "::") return true;                 // loopback / unspecified
  if (lower.startsWith("fe80:") || lower.startsWith("fe80::")) return true; // link-local
  // Unique local addresses: fc00::/7 → first byte in [0xfc, 0xfd]
  if (/^f[cd]/.test(lower)) return true;
  // IPv4-mapped dotted-decimal form (::ffff:a.b.c.d)
  const mDotted = lower.match(/^::ffff:(\d+\.\d+\.\d+\.\d+)$/);
  if (mDotted) return isPrivateV4(mDotted[1]);
  // IPv4-mapped hex form (::ffff:hhhh:hhhh) — as produced by the WHATWG URL parser
  const mHex = lower.match(/^::ffff:([0-9a-f]{1,4}):([0-9a-f]{1,4})$/);
  if (mHex) {
    const hi = parseInt(mHex[1], 16);
    const lo = parseInt(mHex[2], 16);
    const dotted = `${(hi >> 8) & 0xff}.${hi & 0xff}.${(lo >> 8) & 0xff}.${lo & 0xff}`;
    return isPrivateV4(dotted);
  }
  return false;
}

export type UrlPolicy = {
  /** Protocols that are acceptable. Default ["https:"]. */
  allowedProtocols?: string[];
  /** If provided, only these hostnames (or *.suffix) are accepted. */
  allowedHostSuffixes?: string[];
};

export async function assertExternalUrl(
  raw: string | null | undefined,
  policy: UrlPolicy = {},
): Promise<URL> {
  if (!raw || typeof raw !== "string") throw new Error("URL is required");

  let u: URL;
  try { u = new URL(raw); }
  catch { throw new Error("Invalid URL"); }

  const allowedProtocols = policy.allowedProtocols ?? ["https:"];
  if (!allowedProtocols.includes(u.protocol)) {
    throw new Error(`Protocol ${u.protocol} not allowed`);
  }
  if (!u.hostname) throw new Error("Missing hostname");

  // Block userinfo credentials in URL (e.g., https://attacker:x@real-host/)
  // which some clients honor and can be used to confuse allow-list logic.
  if (u.username || u.password) {
    throw new Error("Credentials in URL are not allowed");
  }

  if (policy.allowedHostSuffixes && policy.allowedHostSuffixes.length > 0) {
    const host = u.hostname.toLowerCase();
    const ok = policy.allowedHostSuffixes.some(suffix => {
      const s = suffix.toLowerCase();
      return host === s || host.endsWith("." + s);
    });
    if (!ok) throw new Error(`Host ${host} is not in the allow-list`);
  }

  // URL spec wraps IPv6 addresses in brackets (e.g. "[::1]"); strip them so
  // net.isIP() recognises them correctly.
  const rawHost = u.hostname.startsWith("[") && u.hostname.endsWith("]")
    ? u.hostname.slice(1, -1)
    : u.hostname;

  if (net.isIP(rawHost) === 4) {
    if (isPrivateV4(rawHost)) throw new Error("Private IP not allowed");
  } else if (net.isIP(rawHost) === 6) {
    if (isPrivateV6(rawHost)) throw new Error("Private IP not allowed");
  } else {
    // Hostname — resolve all A/AAAA and check each.
    let records: Array<{ address: string; family: number }>;
    try {
      records = await lookup(u.hostname, { all: true });
    } catch {
      throw new Error("Hostname does not resolve");
    }
    for (const r of records) {
      if (r.family === 4 && isPrivateV4(r.address)) {
        throw new Error(`Hostname resolves to private IP ${r.address}`);
      }
      if (r.family === 6 && isPrivateV6(r.address)) {
        throw new Error(`Hostname resolves to private IP ${r.address}`);
      }
    }
  }
  return u;
}
