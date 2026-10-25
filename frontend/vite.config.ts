/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Puertos configurables para convivir con otros proyectos locales (por defecto 5173 / 8000).
const webPort = Number(process.env.WEB_PORT ?? 5173)
const apiPort = Number(process.env.API_PORT ?? 8000)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: webPort,
    strictPort: true,
    // Mismo origen para el navegador: las cookies HttpOnly de sesión viajan sin CORS.
    proxy: {
      '/api': { target: `http://127.0.0.1:${String(apiPort)}`, changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
