// sourceKind.ts — what kind of document a source label points at.
//
// Every quarterly_data `quarter` and every contract `source` is a label in one
// canonical shape per pipeline (enrich skill §5), for example
//
//   NVIDIA Q2 FY2027 (08-26-2026)                          earnings call
//   Lumentum 8-K (08-11-2026)                              SEC filing
//   Credo Goldman Sachs conference 2026 (09-10-2026)       investor conference
//   Supermicro press release: Supermicro Now Shipping … (09-23-2026)
//   Quanta IR presentation: MOPS 238220260813E001 (08-13-2026)
//
// The words BEFORE the first ": " say what kind of document it is; after the
// colon comes that document's own title. So the rules only look at that head:
// "SUMCO press release: ANNUAL REPORT 2025" is a press release, not a report.
//
// One caveat: a DART periodic report deliberately shares the call shape
// ("SK Hynix Q2 FY2026 (08-14-2026)"), so the label alone cannot tell a Korean
// quarterly report from a call. That group is therefore called "Earnings"
// (call or quarterly report), never "Call".
//
// Pure functions, no React — safe to call from lib/chain2d.ts innerHTML code too.

export type SourceKind = "call" | "conference" | "filing" | "release" | "deck" | "disclosure" | "qa" | "other";

export interface SourceType {
  kind: SourceKind; // coarse group: badge colour + the NodePanel filter chips
  badge: string; // short English badge text ("8-K", "Deck") — pass it through t() to show it
}

// The groups in display order, with their (English) chip names.
export const SOURCE_KINDS: { kind: SourceKind; label: string }[] = [
  { kind: "call", label: "Earnings" },
  { kind: "conference", label: "Conferences" },
  { kind: "filing", label: "Filings" },
  { kind: "release", label: "Releases" },
  { kind: "deck", label: "Decks" },
  { kind: "disclosure", label: "Disclosures" },
  { kind: "qa", label: "Q&A" },
  { kind: "other", label: "Other" },
];

// What each group means — the badge tooltip (English; pass it through t()).
export const SOURCE_HINT: Record<SourceKind, string> = {
  call: "Earnings call or quarterly report",
  conference: "Investor conference or company event",
  filing: "Regulatory filing or periodic report",
  release: "Company press release",
  deck: "Company presentation (IR deck)",
  disclosure: "Exchange disclosure (MOPS, TDnet, DART, announcements)",
  qa: "Management answers to investor questions",
  other: "Third-party note or web page",
};

// The source-document date every label ends with.
const LABEL_DATE = /\s*\(\d{2}-\d{2}-\d{4}\)/;
// SEC form names — the badge shows the form itself.
const SEC_FORM = /\b(8-K|10-K|10-Q|20-F|6-K|40-F|S-1|F-1|424B\d?)\b/;

// First match wins, so the ORDER matters: a "results briefing Q&A" is Q&A, not a
// deck; a "results announcement" is a report, not a bare announcement.
const RULES: [RegExp, SourceKind, string][] = [
  [/\bpress release\b/i, "release", "Release"],
  [/\bTDnet\b/, "disclosure", "TDnet"],
  [/\bMOPS monthly revenue\b/i, "disclosure", "Monthly sales"],
  [/\bMOPS material information\b/i, "disclosure", "Material info"],
  [/\bDART supply contract\b/i, "disclosure", "Supply contract"],
  [/Q&A|\bIR activity record\b/i, "qa", "Q&A"],
  [/\b(briefing (transcript|script)|earnings call|analyst call)\b/i, "call", "Earnings"],
  [/\bQ[1-4] FY\d{4}\b/, "call", "Earnings"],
  [/\b(presentation|briefing|meeting materials?|management plan|business update|investor update)\b/i, "deck", "Deck"],
  [/\bregulatory filing\b/i, "filing", "Filing"],
  [/\b(report|results|earnings release|handbook|financial statements|prospectus)\b/i, "filing", "Report"],
  [/\bannouncement\b/i, "disclosure", "Announcement"],
  [/\b(conference|summit|forum|symposium|keynote|investor day|analyst day|expo)\b/i, "conference", "Conference"],
  [/\b(note|press)$/i, "other", "Note"], // legacy third-party notes ("Goldman Sachs optical note")
  [/\bpage$/i, "other", "Web page"], // a company's product / milestones page
];

/** The kind of document behind a source label (see the header comment). */
export function sourceType(label: string | null | undefined): SourceType {
  const text = (label || "").replace(LABEL_DATE, "").trim();
  const colon = text.indexOf(": ");
  const head = colon >= 0 ? text.slice(0, colon) : text;

  const sec = SEC_FORM.exec(head);
  // A release is checked first: "ECOC 2026 press release" mentions no form, but a
  // release headline could, and the head decides.
  if (sec && !/\bpress release\b/i.test(head)) return { kind: "filing", badge: sec[1] };
  for (const [re, kind, badge] of RULES) if (re.test(head)) return { kind, badge };
  // Events are labelled "[Company] [Event] [YYYY]" — e.g. "Meta connect 2026",
  // "AMD Advancing AI 2026" — so a colon-less head ending in a year is an event.
  if (colon < 0 && /\b(19|20)\d{2}$/.test(head)) return { kind: "conference", badge: "Conference" };
  return { kind: "other", badge: "Other" };
}

/**
 * The part of a label worth showing next to its badge and date: the date is
 * dropped, and when the label belongs to `company` (the panel's own company) its
 * name and the document-kind words go too —
 *   "NVIDIA Q2 FY2027 (08-26-2026)"                 → "Q2 FY2027"
 *   "SK Hynix IR presentation: Q2 2026 results (…)" → "Q2 2026 results"
 * A label of ANOTHER company keeps its full text, so you still see whose call or
 * release a deal came from. Returns "" when nothing is left beyond the badge
 * ("Lumentum 8-K" → "8-K" = the badge).
 */
export function sourceDetail(label: string | null | undefined, company?: string): string {
  let s = (label || "").replace(LABEL_DATE, "").trim();
  if (company && s.startsWith(company + " ")) {
    s = s.slice(company.length + 1);
    const colon = s.indexOf(": ");
    if (colon >= 0) s = s.slice(colon + 2);
  }
  return s.toLowerCase() === sourceType(label).badge.toLowerCase() ? "" : s;
}
