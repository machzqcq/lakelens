import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
      include: ['../../frontend/src/**'],
      exclude: ['../../frontend/src/main.tsx', '**/*.d.ts'],
    },
  },
  resolve: {
    alias: {
      // Tests under tests/frontend/src/ import from the real frontend src
      '@app': path.resolve(__dirname, '../../frontend/src'),
    },
  },
});
