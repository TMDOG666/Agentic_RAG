import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  return {
    plugins: [vue()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target: process.env.VITE_DEV_PROXY_TARGET || 'http://127.0.0.1:8080',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, ''),
        },
      },
    },
  }
})
