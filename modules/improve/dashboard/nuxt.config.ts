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
      // The API binds to loopback. It approves recommendations, and an
      // approved recommendation is what authorises writing to a repository.
      apiBase: process.env.NUXT_PUBLIC_ALENA_API || 'http://127.0.0.1:9100',
    },
  },
  devServer: { host: '127.0.0.1', port: 3100 },
})
