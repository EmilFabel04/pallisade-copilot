import { dirname } from 'path';
import { fileURLToPath } from 'url';
import { FlatCompat } from '@eslint/eslintrc';

const compat = new FlatCompat({ baseDirectory: dirname(fileURLToPath(import.meta.url)) });

const eslintConfig = [
  ...compat.extends('next/core-web-vitals', 'next/typescript'),
  {
    rules: {
      // ~1,200 existing `any`s — surfaced as warnings so they're visible
      // without blocking CI; tighten to "error" once they're paid down.
      '@typescript-eslint/no-explicit-any': 'warn',
    },
  },
  {
    // Tests use require() inside jest.isolateModules to reload modules
    // under different env vars.
    files: ['**/__tests__/**', '**/*.test.ts', '**/*.test.tsx'],
    rules: {
      '@typescript-eslint/no-require-imports': 'off',
    },
  },
  {
    ignores: [
      'node_modules/**',
      '.next/**',
      'out/**',
      'build/**',
      'next-env.d.ts',
      'scanner/**',
      '.worktrees/**',
      '.claude/**',
    ],
  },
];

export default eslintConfig;
