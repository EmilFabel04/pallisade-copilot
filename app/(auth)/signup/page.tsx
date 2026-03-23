'use client';

import { useState, useEffect } from 'react';
import { signIn } from 'next-auth/react';
import { useRouter, useSearchParams } from 'next/navigation';
import Link from 'next/link';

export default function SignUpPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [formData, setFormData] = useState({
    name: '',
    email: '',
    password: '',
    confirmPassword: '',
    organizationName: '',
  });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [orgSsoOnly, setOrgSsoOnly] = useState(false);

  const inviteToken = searchParams.get('token');

  useEffect(() => {
    if (inviteToken) {
      fetch(`/api/team/invite/check?token=${inviteToken}`)
        .then((res) => res.json())
        .then((data) => {
          if (data.authPolicy === 'SSO_ONLY') {
            setOrgSsoOnly(true);
          }
        })
        .catch(() => {});
    }
  }, [inviteToken]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData(prev => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');

    // Validation
    if (formData.password !== formData.confirmPassword) {
      setError('Passwords do not match');
      setIsLoading(false);
      return;
    }

    if (formData.password.length < 8) {
      setError('Password must be at least 8 characters');
      setIsLoading(false);
      return;
    }

    try {
      const res = await fetch('/api/auth/signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: formData.name,
          email: formData.email,
          password: formData.password,
          organizationName: formData.organizationName || undefined,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || 'Something went wrong');
        return;
      }

      // Auto sign in after successful signup
      const signInResult = await signIn('credentials', {
        email: formData.email,
        password: formData.password,
        redirect: false,
      });

      if (signInResult?.error) {
        router.push('/login');
      } else {
        router.push('/onboarding');
        router.refresh();
      }
    } catch (err) {
      setError('An error occurred. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="w-full max-w-md">
      <div className="text-center mb-8">
        <Link href="/" className="inline-block">
          <img src="/pallisade_emblem.svg" alt="Pallisade" className="w-16 h-16 mx-auto mb-4" />
        </Link>
        <h1 className="text-2xl font-bold">Create your account</h1>
        <p className="text-[var(--muted)] mt-2">Start securing your organization today</p>
      </div>

      <div className="auth-card">
        {error && (
          <div className="mb-6 p-4 rounded-lg bg-red-950/40 border border-red-900/40 text-red-400 text-sm">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label htmlFor="name" className="block text-sm font-medium mb-2">
              Full name
            </label>
            <input
              id="name"
              name="name"
              type="text"
              value={formData.name}
              onChange={handleChange}
              required
              className="auth-input"
              placeholder="John Doe"
              autoComplete="name"
            />
          </div>

          <div>
            <label htmlFor="email" className="block text-sm font-medium mb-2">
              Work email
            </label>
            <input
              id="email"
              name="email"
              type="email"
              value={formData.email}
              onChange={handleChange}
              required
              className="auth-input"
              placeholder="you@company.com"
              autoComplete="email"
            />
          </div>

          <div>
            <label htmlFor="organizationName" className="block text-sm font-medium mb-2">
              Company name <span className="text-[var(--muted)] font-normal">(optional)</span>
            </label>
            <input
              id="organizationName"
              name="organizationName"
              type="text"
              value={formData.organizationName}
              onChange={handleChange}
              className="auth-input"
              placeholder="Acme Inc."
            />
          </div>

          {orgSsoOnly ? (
            <div className="space-y-4 text-center">
              <p className="text-sm text-[var(--muted)]">
                Your organization requires SSO. Sign in with one of the providers below.
              </p>
              <button onClick={() => signIn('google', { callbackUrl: '/dashboard' })} className="btn btn-secondary w-full justify-center">
                Continue with Google
              </button>
              <button onClick={() => signIn('github', { callbackUrl: '/dashboard' })} className="btn btn-secondary w-full justify-center">
                Continue with GitHub
              </button>
              <button onClick={() => signIn('microsoft-entra-id', { callbackUrl: '/dashboard' })} className="btn btn-secondary w-full justify-center">
                Continue with Microsoft
              </button>
            </div>
          ) : (
            <>
              <div>
                <label htmlFor="password" className="block text-sm font-medium mb-2">
                  Password
                </label>
                <input
                  id="password"
                  name="password"
                  type="password"
                  value={formData.password}
                  onChange={handleChange}
                  required
                  className="auth-input"
                  placeholder="At least 8 characters"
                  autoComplete="new-password"
                />
              </div>

              <div>
                <label htmlFor="confirmPassword" className="block text-sm font-medium mb-2">
                  Confirm password
                </label>
                <input
                  id="confirmPassword"
                  name="confirmPassword"
                  type="password"
                  value={formData.confirmPassword}
                  onChange={handleChange}
                  required
                  className="auth-input"
                  placeholder="••••••••"
                  autoComplete="new-password"
                />
              </div>

              <button
                type="submit"
                disabled={isLoading}
                className="btn btn-elevated w-full justify-center"
              >
                {isLoading ? (
                  <span className="flex items-center gap-2">
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Creating account...
                  </span>
                ) : (
                  'Create account'
                )}
              </button>

              <p className="text-xs text-center text-[var(--muted)]">
                By signing up, you agree to our{' '}
                <Link href="/terms" className="text-[var(--accent-2)] hover:underline">Terms of Service</Link>
                {' '}and{' '}
                <Link href="/privacy" className="text-[var(--accent-2)] hover:underline">Privacy Policy</Link>
              </p>
            </>
          )}
        </form>

        <p className="mt-8 text-center text-sm text-[var(--muted)]">
          Already have an account?{' '}
          <Link href="/login" className="text-[var(--accent-2)] hover:underline font-medium">
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}
