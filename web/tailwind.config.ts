import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // cyber-meow workspace palette
        bg: "#0a0e14",
        panel: "#11161f",
        border: "#1f2733",
        text: "#c9d1d9",
        muted: "#6e7681",
        // four cats
        planner: "#c9b8d9",   // 布偶:毛玻璃灰白紫
        executor: "#f0883e",  // 橘:亮橙
        reviewer: "#39c5cf",  // 狸:青蓝
        validator: "#3fb950", // 玄:矩阵绿(暗处金眸→绿)
        danger: "#f85149",
        warn: "#d29922",
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      animation: {
        "pulse-slow": "pulse 2s cubic-bezier(0.4,0,0.6,1) infinite",
        "shake": "shake 0.4s ease-in-out",
      },
      keyframes: {
        shake: {
          "0%,100%": { transform: "translateX(0)" },
          "25%": { transform: "translateX(-4px)" },
          "75%": { transform: "translateX(4px)" },
        },
      },
    },
  },
  plugins: [],
};
export default config;
