import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server on 5174 (day7 uses 5173), API calls proxied to the validator backend on 8100.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8100',
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on('error', (_err, _req, res) => {
            if (res && 'writeHead' in res && !res.headersSent) {
              res.writeHead(503, { 'Content-Type': 'application/json' });
              res.end(JSON.stringify({ detail: 'Cannot reach the validator backend. Is it running on port 8100?' }));
            }
          });
        },
      },
    },
  },
})
