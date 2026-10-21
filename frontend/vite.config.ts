/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  // The same proxy for `vite preview`, so a production build can be checked
  // against the local backend (headless captures use this: no HMR socket).
  preview: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './vitest.setup.ts',
    // The layout tests run in a real browser with Playwright (npm run test:layout).
    exclude: ['**/node_modules/**', 'e2e/**'],
    css: true,
    // Launch item 11: typing through userEvent can pass 5 s on a loaded machine; a passing test is no slower.
    testTimeout: 20_000,
  },
})
