import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The dev server proxies the API (and its event streams) to the Python backend on :8765.
export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: false } },
  },
  build: { outDir: 'dist', chunkSizeWarningLimit: 2500 },
});
