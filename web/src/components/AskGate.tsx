"use client";

import type { ReactNode } from "react";
import { ClerkLoading, SignedIn, SignedOut, SignInButton, SignUpButton, UserButton } from "@clerk/nextjs";
import { useLang } from "@/lib/i18n";
import "./AskGraph.css";

// AskGate — Ask is for signed-in visitors only (user, 2026-10-13).
//   Signed out: a short note with "Sign in" / "Create account", which open Clerk's
//   pop-up (Google, X, or an email account).
//   Signed in: the Ask view itself, with the account button above it.
// The API routes check the same session (app/api/ask/*), so a request that skips
// this screen is still refused.
export default function AskGate({ children }: { children: ReactNode }) {
  const { t } = useLang();
  return (
    <>
      <ClerkLoading>
        <p className="caption">{t("Loading…")}</p>
      </ClerkLoading>
      <SignedOut>
        <div className="ask ask-gate">
          <h3>{t("Sign in to ask")}</h3>
          <p>{t("Ask is for signed-in members. Sign in with Google or X, or create a free account with your email.")}</p>
          <div className="ask-gate-actions">
            <SignInButton mode="modal">
              <button type="button" className="btn">{t("Sign in")}</button>
            </SignInButton>
            <SignUpButton mode="modal">
              <button type="button" className="btn">{t("Create account")}</button>
            </SignUpButton>
          </div>
        </div>
      </SignedOut>
      <SignedIn>
        <div className="ask-account">
          <UserButton />
        </div>
        {children}
      </SignedIn>
    </>
  );
}
