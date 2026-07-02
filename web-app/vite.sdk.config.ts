import { defineConfig } from 'vite'

declare const __dirname: string
declare function require(moduleName: string): any

const { resolve } = require('node:path')

// Builds the theme SDK a second time as a plain IIFE global
// (`window.DashbRuntime`), so a theme that's just static HTML/JS with no
// build step of its own can still use the shared WS/protocol client via
// `<script src="/theme-runtime.js"></script>`. Themes with their own
// bundler should instead `import` from `src/theme-sdk` directly - this
// build exists purely for that no-build-step case.
//
// Runs as a second, separate `vite build` invocation against the same
// `dist` output (see package.json) - emptyOutDir must stay false so it
// doesn't wipe the main app build that already ran.
export default defineConfig({
  build: {
    emptyOutDir: false,
    outDir: 'dist',
    lib: {
      entry: resolve(__dirname, 'src/theme-sdk/index.ts'),
      name: 'DashbRuntime',
      formats: ['iife'],
      fileName: () => 'theme-runtime.js',
    },
  },
})
