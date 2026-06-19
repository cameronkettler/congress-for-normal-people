import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Civic Pulse",
  description: "Agentic civic intelligence for federal legislation"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
