"use client";

import type { Resolver } from "@/lib/company";
import { useLang } from "@/lib/i18n";

// Renders a table cell's text as a button that opens the company's NodePanel —
// the same panel you get by clicking the company in the 3D graph — but only when
// the text actually names a company in the graph. Anything else renders as
// plain text, so a cell is never a dead link.
export default function CompanyLink({
  text,
  display,
  resolve,
  onOpen,
  className,
}: {
  text: string;
  /** What to show when `text` is not a company (e.g. its translation). Defaults to `text`. */
  display?: string;
  resolve: Resolver;
  onOpen: (id: string) => void;
  className?: string;
}) {
  const { t, name, lang } = useLang();
  const id = resolve(text); // always resolved on the ENGLISH cell text
  if (!id) return <>{display ?? text}</>;
  // In another language show the company's local name when there is one.
  const shown = lang !== "en" && name(id) !== id ? name(id) : text;
  return (
    <button
      type="button"
      className={"co-link" + (className ? " " + className : "")}
      title={id === text ? t("Open {name}", { name: name(id) }) : t("Open {name}", { name: name(id) }) + ` (${text})`}
      onClick={(e) => {
        e.stopPropagation();
        onOpen(id);
      }}
    >
      {shown}
    </button>
  );
}
