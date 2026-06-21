import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Congress For Normal People",
  metadataBase: new URL("https://congress-for-normal-people.com"),
  description:
    "Track legislation, understand federal bills, and learn what your representatives support in plain English.",
  alternates: {
    canonical: "/"
  },
  openGraph: {
    title: "Congress For Normal People",
    description:
      "Plain-English federal legislation intelligence for voters who want to understand bills, representatives, and policy stakes.",
    url: "https://congress-for-normal-people.com",
    siteName: "Congress For Normal People",
    type: "website"
  },
  robots: {
    index: true,
    follow: true
  }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body suppressHydrationWarning>{children}</body>
    </html>
  );
}
