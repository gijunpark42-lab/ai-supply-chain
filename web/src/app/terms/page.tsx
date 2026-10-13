// /terms — the site's terms of service. X's developer app needs a public terms link
// (with the privacy policy at /privacy) before it can share a user's email with
// Clerk. Plain static text, same look as /privacy.
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Terms of Service · Nodus42",
  description: "The terms for using Nodus42.",
};

const box: React.CSSProperties = {
  maxWidth: 720,
  margin: "0 auto",
  padding: "48px 16px 80px",
  color: "var(--ap-text)",
  lineHeight: 1.6,
  fontSize: "var(--fs-body)",
};
const h2: React.CSSProperties = { fontSize: "var(--fs-h)", margin: "28px 0 8px" };
const muted: React.CSSProperties = { color: "var(--ap-muted)" };

export default function TermsPage() {
  return (
    <main style={box}>
      <h1 style={{ fontSize: "var(--fs-title)", marginBottom: 4 }}>Terms of Service</h1>
      <p style={muted}>Last updated: October 13, 2026</p>

      <p>By using Nodus42 (nodus42.com) you agree to these terms.</p>

      <h2 style={h2}>Not investment advice</h2>
      <p>
        Nodus42 maps supply-chain relationships from company filings, earnings calls and
        news, for research and education. Nothing on the site, including Ask answers and
        news summaries, is investment, financial, legal or tax advice. Make your own
        decisions and check the original sources.
      </p>

      <h2 style={h2}>Accuracy</h2>
      <p>
        The map, figures, news summaries and Ask answers can be incomplete, out of date or
        wrong. Ask answers and summaries are written by AI. The site is provided as is,
        without warranties of any kind.
      </p>

      <h2 style={h2}>Your account</h2>
      <p>
        You need an account to use Ask. Keep your sign-in secure and do not misuse the
        service, for example by automated scraping or by trying to overload it. We may
        suspend accounts that do.
      </p>

      <h2 style={h2}>Liability</h2>
      <p>
        To the extent the law allows, Nodus42 is not liable for any loss that comes from
        using the site or relying on its content.
      </p>

      <h2 style={h2}>Changes</h2>
      <p>
        We may update these terms. The date at the top shows the latest version. See also
        the{" "}
        <Link href="/privacy" style={{ color: "var(--ap-blue)" }}>
          Privacy Policy
        </Link>
        .
      </p>

      <h2 style={h2}>Contact</h2>
      <p>
        Message{" "}
        <a href="https://x.com/Nodus42" style={{ color: "var(--ap-blue)" }}>
          @Nodus42
        </a>{" "}
        on X.
      </p>
    </main>
  );
}
