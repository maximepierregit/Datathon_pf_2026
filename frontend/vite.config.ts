import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Les SVG de Pépite vivent dans ../assets/mascot : on autorise Vite à lire le dossier parent.
// /api va au serveur AgentCore local du backend (configuration « backend » de .claude/launch.json, port 8091).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    fs: { allow: ['..'] },
    proxy: { '/api': { target: 'http://localhost:8091', rewrite: (path) => path.replace(/^\/api/, '') } },
  },
})
