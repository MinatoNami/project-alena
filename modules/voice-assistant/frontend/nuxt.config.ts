// https://nuxt.com/docs/api/configuration/nuxt-config
export default defineNuxtConfig({
  compatibilityDate: '2025-07-15',
  devtools: { enabled: true },

  runtimeConfig: {
    public: {
      wsAudioUrl: process.env.NUXT_PUBLIC_WS_AUDIO_URL || 'ws://localhost:8080'
    }
  },

  modules: [
    '@nuxt/ui',
    '@nuxt/image',
    '@nuxt/eslint',
    '@nuxt/content',
    '@nuxt/test-utils'
  ]
})