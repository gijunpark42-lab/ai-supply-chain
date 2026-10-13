// /privacy — the site's privacy policy. Google's OAuth consent screen (Sign in with
// Google) and X's developer app both ask for a public privacy-policy link, so this
// page exists mainly for them. Plain static text: no data, no client code.
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy Policy · Nodus42",
  description: "What Nodus42 collects and how it is used.",
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

export default function PrivacyPage() {
  return (
    <main style={box}>
      <h1 style={{ fontSize: "var(--fs-title)", marginBottom: 4 }}>Privacy Policy</h1>
      <p style={muted}>Last updated: October 13, 2026</p>

      <p>
        Nodus42 (nodus42.com) is a free supply-chain map for investors. This page explains
        what information the site collects and what it is used for.
      </p>

      <h2 style={h2}>Signing in</h2>
      <p>
        Only the Ask tab needs an account. Sign-in is handled by Clerk (clerk.com). When you
        sign in with Google, X or email, Clerk receives your email address, name and profile
        picture from that provider. We use them only to let you use Ask. We never get your
        Google or X password.
      </p>

      <h2 style={h2}>Questions you ask</h2>
      <p>
        A question you type into Ask is sent to Anthropic's Claude API to write the answer.
        Nodus42 does not save your questions or the answers.
      </p>

      <h2 style={h2}>Analytics</h2>
      <p>
        We use Vercel Web Analytics to count visitors, page views and a few clicks (opening a
        company, switching views, asking a question). It uses no cookies and never records
        the text of your questions.
      </p>

      <h2 style={h2}>Your browser</h2>
      <p>
        Settings like your language choice are kept in your own browser&apos;s local storage.
        They are not sent to us.
      </p>

      <h2 style={h2}>Sharing</h2>
      <p>
        We do not sell or rent your information and show no ads. It is shared only with the
        services named above (Clerk, Anthropic, Vercel) so the site can work.
      </p>

      <h2 style={h2}>Deleting your account</h2>
      <p>
        To delete your account, message us (see Contact below) and we will remove your
        sign-in record from Clerk.
      </p>

      <h2 style={h2}>Contact</h2>
      <p>
        Questions about this policy: message{" "}
        <a href="https://x.com/Nodus42" style={{ color: "var(--ap-blue)" }}>
          @Nodus42
        </a>{" "}
        on X.
      </p>
    </main>
  );
}
