import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Anthropic-style warm neutral palette
        bg: "#F5F4EE",
        panel: "#FAF9F5",
        panel2: "#EFEEE6",
        border: "#E2DED3",
        text: "#2D2A26",
        muted: "#8B8479",
        accent: "#D97757", // clay/coral
        // four cats (readable on light bg)
        planner: "#7C5C99",
        executor: "#C2410C",
        reviewer: "#0E7490",
        validator: "#15803D",
        danger: "#B91C1C",
        warn: "#B45309",
      },
      fontFamily: {
        serif: ['"Iowan Old Style"', "Georgia", "Cambria", "serif"],
        sans: ["system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      animation: {
        "pulse-slow": "pulse 2.5s cubic-bezier(0.4,0,0.6,1) infinite",
        "fade-in": "fadeIn 0.25s ease-out",
      },
      keyframes: {
        fadeIn: { from: { opacity: "0", transform: "translateY(4px)" }, to: { opacity: "1", transform: "translateY(0)" } },
      },
    },
  },
  plugins: [],
};
export default config;
