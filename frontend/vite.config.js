import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const now = new Date()
const buildDate = now.toISOString().slice(0, 10)  // YYYY-MM-DD
const buildTime = now.toISOString().slice(11, 16)  // HH:MM UTC
// Version: commit short hash from git, fallback to date-based
import { execSync } from 'child_process'
let gitHash = 'local'
try { gitHash = execSync('git rev-parse --short HEAD').toString().trim() } catch {}

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(gitHash),
    __BUILD_DATE__: JSON.stringify(`${buildDate} ${buildTime}z`),
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
