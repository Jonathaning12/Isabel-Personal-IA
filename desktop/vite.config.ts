import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// Strict Content Security Policy for the packaged app. Only in builds: the dev server
// needs inline scripts for hot reload. 'unsafe-eval' is required by the Vosk speech engine
// (Emscripten) used for the local wake word; the app loads only local code, never evals
// text, and keeps contextIsolation + sandbox, so the trade-off is documented and accepted.
const csp = (): Plugin => ({
  name: "csp",
  apply: "build",
  transformIndexHtml: (html) =>
    html.replace(
      "<head>",
      `<head>\n    <meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'wasm-unsafe-eval' 'unsafe-eval' blob:; worker-src 'self' blob:; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' isabel-model: data:; media-src 'self' blob:; object-src 'none'; base-uri 'none'" />`,
    ),
});

// The renderer is built to dist/ and loaded by Electron from disk (relative paths).
// In a plain browser (`npm run preview`), /api is proxied to the local assistant API,
// so the UI can be tried without Electron.
export default defineConfig({
  base: "./",
  plugins: [react(), csp()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  // One local bundle (three.js and the Vosk WebAssembly speech engine); size warnings do
  // not apply to a desktop app loaded from disk.
  build: { outDir: "dist", emptyOutDir: true, chunkSizeWarningLimit: 8000 },
});
