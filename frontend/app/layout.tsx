import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VLens | Disengagement Review Assistant",
  description: "AI-assisted review for recorded disengagements.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
