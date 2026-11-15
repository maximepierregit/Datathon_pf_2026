import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Les SVG de Pépite vivent dans ../assets/mascot : on autorise Vite à lire le dossier parent.
// /api va au serveur AgentCore local du backend (configuration « backend » de .claude/launch.json, port 8091).
// MONPORT_API=http://<ip de l'EC2> l'envoie plutôt au backend en ligne (nginx y publie déjà /api/).
declare const process: { env: Record<string, string | undefined> } // sans @types/node
const remote = process.env.MONPORT_API

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    fs: { allow: ['..'] },
    proxy: {
      '/api': remote
        ? { target: remote, changeOrigin: true }
        : { target: 'http://localhost:8091', rewrite: (path) => path.replace(/^\/api/, '') },
    },
  },
})
