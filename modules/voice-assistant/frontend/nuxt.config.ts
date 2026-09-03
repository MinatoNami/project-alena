// https://nuxt.com/docs/api/configuration/nuxt-config
import tailwindcss from "@tailwindcss/vite";

export default defineNuxtConfig({
  compatibilityDate: "2025-07-15",
  devtools: { enabled: true },
  css: ["./app/assets/css/main.css"],
  runtimeConfig: {
    public: {
      // The backend proxies LM Studio; the browser never calls it directly.
      llmApiUrl:
        process.env.NUXT_PUBLIC_LLM_API_URL || "http://localhost:8001",
      wsAudioUrl:
        process.env.NUXT_PUBLIC_WS_AUDIO_URL || "ws://localhost:8000/ws",
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
