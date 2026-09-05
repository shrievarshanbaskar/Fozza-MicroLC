import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 480_000, // a real testnet lock (~80 s) precedes every negotiation
  retries: 0,
  workers: 1, // the API and Groq are shared; keep specs serial
  use: { baseURL: process.env.E2E_BASE_URL || "http://localhost:3000", headless: true, viewport: { width: 1600, height: 1000 } },
  reporter: [["list"]],
});
