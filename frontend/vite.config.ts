import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 20198,
    strictPort: true,
    // Allow access via public IP (e.g. http://116.202.210.102:20197/)
    allowedHosts: true,
    // Route API calls to the local uvicorn backend regardless of browser host.
    proxy: {
      '/api': {
        // Must match the uvicorn port (see backend scripts / e2e defaults).
        target: process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 20197
    ,
    strictPort: true,
    allowedHosts: true,
  },
})
