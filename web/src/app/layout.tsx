import type { Metadata, Viewport } from "next";
import { Analytics } from "@vercel/analytics/next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Nodus42",
  description:
    "The global AI & semiconductor web — every supplier, customer, and deal, connected.",
};

// Phones render at a fake 980px viewport unless we say otherwise, which would
// shrink the whole app to unreadable. `viewportFit: cover` lets the CSS below
// use env(safe-area-inset-*) to dodge the notch / home indicator.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#0a0c10",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {children}
        {/* Vercel Web Analytics: visitors + page views (cookieless). The project's
            Analytics tab on vercel.com shows them; custom click events are sent
            with track() in page.tsx and AskGraph.tsx. */}
        <Analytics />
      </body>
    </html>
  );
}
