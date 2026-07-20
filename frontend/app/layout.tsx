import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Dify Workflow Console",
  description: "Govern and operate Dify workflows",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
