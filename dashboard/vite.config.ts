import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api/live': {
        target: 'https://prod-public-api.livescore.com',
        changeOrigin: true,
        rewrite: (path) => {
          const today = new Date().toISOString().slice(0, 10).replace(/-/g, '')
          return `/v1/api/app/date/soccer/${today}/0`
        },
      },
      '/api/live-now': {
        target: 'https://prod-public-api.livescore.com',
        changeOrigin: true,
        rewrite: () => '/v1/api/app/live/soccer/0',
      },
    },
  },
})
