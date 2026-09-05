import type { Config } from "tailwindcss";

// "Trust Navy & Ink" design tokens — source of truth for the MicroLC UI.
const config: Config = {
  darkMode: "class",
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#0B1220",
        surface: "#111827",
        "surface-2": "#1E293B",
        primary: { DEFAULT: "#2454FF", hover: "#1D4ED8" },
        success: "#16A34A",
        error: "#EF4444",
        paper: "#F7F8FA",
      },
      fontFamily: {
        serif: ["var(--font-serif)", "Georgia", "serif"],
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      borderRadius: { card: "16px", btn: "10px", badge: "4px" },
      boxShadow: {
        standard: "0 20px 40px rgba(0,0,0,.1)",
        primary: "0 10px 20px rgba(36,84,255,.2)",
      },
      transitionTimingFunction: { std: "cubic-bezier(.4,0,.2,1)" },
      transitionDuration: { std: "300ms" },
    },
  },
  plugins: [],
};
export default config;
