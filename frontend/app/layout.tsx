import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "IncidentLens | Forensic Review Workspace",
  description: "AI-assisted evidence review for recorded disengagements.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
