import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Magic Social Dashboard",
  description: "Post pipeline metrics and quality tracking",
};

function Nav() {
  return (
    <nav className="border-b border-border bg-card">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-6">
        <Link href="/" className="font-mono text-sm font-semibold tracking-tight">
          magic-social
        </Link>
        <div className="flex items-center gap-4 text-sm text-muted-foreground">
          <Link href="/" className="hover:text-foreground transition-colors">
            Overview
          </Link>
          <Link href="/posts" className="hover:text-foreground transition-colors">
            Posts
          </Link>
          <Link href="/health" className="hover:text-foreground transition-colors">
            Health
          </Link>
        </div>
      </div>
    </nav>
  );
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark`}
    >
      <body className="min-h-screen bg-background text-foreground antialiased">
        <Nav />
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
