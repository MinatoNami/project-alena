export default defineNuxtConfig({
  compatibilityDate: '2025-01-01',
  devtools: { enabled: false },
  modules: ['@nuxt/ui'],
  css: ['~/assets/css/main.css'],
  // Single-page app: there is no server-side data here, and rendering on the
  // server would mean the Nuxt process needing the API at build time.
  ssr: false,
  runtimeConfig: {
    public: {
      // Empty means origin-relative, which is what the built app wants: the
      // API serves it, so the browser is same-origin and CORS never enters
      // into it. `npm run dev` runs on its own port and needs the absolute
      // URL, which the start script sets.
      apiBase: process.env.NUXT_PUBLIC_ALENA_API || '',
    },
  },
  devServer: { host: '127.0.0.1', port: 3100 },
})
