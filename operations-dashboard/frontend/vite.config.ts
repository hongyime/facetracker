import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    watch: {
      usePolling: process.env.CHOKIDAR_USEPOLLING === 'true',
      interval: 500,
    },
    proxy: {
      '/face-api': {
        target: process.env.DEV_FACETRACKER_TARGET || 'http://127.0.0.1:5454',
        rewrite: (path) => path.replace(/^\/face-api/, ''),
      },
      '/api': process.env.DEV_DASHBOARD_TARGET || 'http://127.0.0.1:8700',
      '/ws': {
        target: process.env.DEV_DASHBOARD_TARGET || 'http://127.0.0.1:8700',
        ws: true,
      },
    },
  },
});
