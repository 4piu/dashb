import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react-swc'

declare const __dirname: string
declare function require(moduleName: string): any

const { copyFileSync, existsSync, mkdirSync, readdirSync } = require('node:fs')
const { dirname, resolve } = require('node:path')

function copyThemeManifests() {
  return {
    name: 'copy-theme-manifests',
    closeBundle() {
      const themeRoot = resolve(__dirname, 'theme')
      const outRoot = resolve(__dirname, 'dist', 'theme')

      if (!existsSync(themeRoot)) {
        return
      }

      for (const themeId of readdirSync(themeRoot)) {
        const manifestPath = resolve(themeRoot, themeId, 'theme.json')
        const outputPath = resolve(outRoot, themeId, 'theme.json')

        if (!existsSync(manifestPath)) {
          continue
        }

        mkdirSync(dirname(outputPath), { recursive: true })
        copyFileSync(manifestPath, outputPath)
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  base: './',
  build: {
    target: 'safari15',
    cssTarget: 'safari15',
    outDir: 'dist',
    rollupOptions: {
      input: {
        index: resolve(__dirname, 'index.html'),
        debug: resolve(__dirname, 'theme/debug/index.html'),
      },
    },
  },
  plugins: [react(), copyThemeManifests()],
})
