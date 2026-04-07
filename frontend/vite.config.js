import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const now = new Date()
// Format in Phoenix time (America/Phoenix = MST, UTC-7, no DST)
const phoenixOpts = { timeZone: 'America/Phoenix', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: true }
const phoenixParts = new Intl.DateTimeFormat('en-US', phoenixOpts).formatToParts(now)
const p = Object.fromEntries(phoenixParts.map(({ type, value }) => [type, value]))
const buildDate = `${p.year}-${p.month}-${p.day}`
const buildTime = `${p.hour}:${p.minute} ${p.dayPeriod} AZ`
// Version: commit short hash from git, fallback to date-based
import { execSync } from 'child_process'
let gitHash = 'local'
try { gitHash = execSync('git rev-parse --short HEAD').toString().trim() } catch {}

export default defineConfig({
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(gitHash),
    __BUILD_DATE__: JSON.stringify(`${buildDate} ${buildTime}`),
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
