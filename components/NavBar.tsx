'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

const NAV_LINKS = [
  { href: '/how-it-works', label: 'How It Works' },
  { href: '/services', label: 'Pricing' },
  { href: '/blog', label: 'Blog' },
];

export function NavBar() {
  const pathname = usePathname();

  const isActive = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname.startsWith(href);
  };

  return (
    <header className="container">
      <nav className="nav">
        <Link href="/" className="brand">
          <img src="/pallisade_emblem.svg" alt="Pallisade" className="brand-emblem" />
          <span className="brand-text">PALLISADE</span>
        </Link>
        <div className="links">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={isActive(link.href) ? 'nav-link-active' : ''}
            >
              {link.label}
            </Link>
          ))}
          <Link href="/login" className="nav-link-muted">
            Log In
          </Link>
          <Link 
            href="/contact" 
            className={`cta ${isActive('/contact') ? 'cta-active' : ''}`}
          >
            Request Demo
          </Link>
        </div>
      </nav>
    </header>
  );
}
