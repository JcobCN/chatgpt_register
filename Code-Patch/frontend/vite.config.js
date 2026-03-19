import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const repoRoot = path.resolve(__dirname, '..')

function toWsOrigin(httpOrigin) {
  if (httpOrigin.startsWith('https://')) return httpOrigin.replace('https://', 'wss://')
  if (httpOrigin.startsWith('http://')) return httpOrigin.replace('http://', 'ws://')
  return httpOrigin
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, '')

  const frontendPort = Number(env.FRONTEND_PORT || 5173)
  const backendHost = (env.BACKEND_HOST || env.APP_HOST || '127.0.0.1').trim() || '127.0.0.1'
  const backendPort = Number(env.BACKEND_PORT || env.APP_PORT || 8000)
  const backendOrigin = (env.BACKEND_ORIGIN || `http://${backendHost}:${backendPort}`).trim()
  const backendWsOrigin = (env.BACKEND_WS_ORIGIN || toWsOrigin(backendOrigin)).trim()

  return {
    envDir: repoRoot,
    plugins: [vue()],
    server: {
      port: frontendPort,
      proxy: {
        '/api': {
          target: backendOrigin,
          changeOrigin: true,
        },
        '/ws': {
          target: backendWsOrigin,
          ws: true,
          changeOrigin: true,
        },
      },
    },
  }
})
