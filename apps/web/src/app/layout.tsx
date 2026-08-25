import type { Metadata } from "next";
import { Geist_Mono, Ubuntu } from "next/font/google";
import { QueryProvider } from "@/lib/query-provider";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

// Helvetica isn't on Google Fonts (Linotype/Monotype licensing — it can't
// be freely embedded for the web), so Ubuntu is the closest freely-licensed
// choice that renders consistently for every visitor rather than depending
// on what's installed locally.
const ubuntuSans = Ubuntu({
  variable: "--font-ubuntu-sans",
  subsets: ["latin"],
  weight: ["300", "400", "500", "700"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI Content Studio",
  description: "AI Marketing Manager — plan, create, publish, and measure your marketing.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${ubuntuSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background text-foreground">
        <QueryProvider>{children}</QueryProvider>
        <Toaster />
      </body>
    </html>
  );
}
