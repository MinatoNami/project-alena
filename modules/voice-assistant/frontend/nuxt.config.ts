// https://nuxt.com/docs/api/configuration/nuxt-config
import tailwindcss from "@tailwindcss/vite";

export default defineNuxtConfig({
  compatibilityDate: "2025-07-15",
  devtools: { enabled: true },
  css: ["./app/assets/css/main.css"],
  runtimeConfig: {
    public: {
      ollamaUrl: process.env.NUXT_PUBLIC_OLLAMA_URL || "http://10.8.0.1:11434",
      wsAudioUrl:
        process.env.NUXT_PUBLIC_WS_AUDIO_URL || "wss://10.8.0.1:8000/ws",
    },
  },
  vite: {
    plugins: [tailwindcss()],
  },

  modules: [
    "@nuxt/ui",
    "@nuxt/image",
    "@nuxt/eslint",
    "@nuxt/content",
    "@nuxt/test-utils",
  ],
});
