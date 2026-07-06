import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MeowWork · 赛博喵工坊",
  description: "多智能体协作与监控系统",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh">
      <body>{children}</body>
    </html>
  );
}
