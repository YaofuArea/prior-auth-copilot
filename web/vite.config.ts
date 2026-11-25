import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // In development, the FastAPI server (uv run uvicorn api:app) answers /api.
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
