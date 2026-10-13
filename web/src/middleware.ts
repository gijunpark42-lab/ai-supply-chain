// Clerk reads the visitor's sign-in session here, so the Ask API routes can check it
// with auth() (user, 2026-10-13: Ask is for signed-in users only). It runs ONLY on
// /api/ask and /api/ask/rewrite; every other page, API route and file is served
// without it.
import { clerkMiddleware } from "@clerk/nextjs/server";

export default clerkMiddleware();

export const config = {
  matcher: ["/api/ask(.*)"],
};
