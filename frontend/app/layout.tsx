import type { Metadata } from "next";
import { AuthGuard } from "../components/AuthGuard";
import "./globals.css";

export const metadata: Metadata = {
  title: "VLens",
  description: "AI-assisted evidence review for recorded disengagements.",
  icons: {
    icon: "/images/logo.png",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body><AuthGuard>{children}</AuthGuard></body>
    </html>
  );
}
