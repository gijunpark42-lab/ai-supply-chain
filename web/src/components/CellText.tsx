"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { createPortal } from "react-dom";
import { t } from "@/lib/i18n";
import { SourceBadge } from "./SignalText";

export interface CellDetail {
  /** Source label the value came from, e.g. "Analog Devices Q3 FY2026 (08-19-2026)". */
  source?: string;
  /** The full signal paragraph behind the compact figure the table shows. */
  signal?: string;
}

/**
 * A table cell whose text CSS clamps to 1-3 lines (`.cell` in globals.css,
 * `.cell.tb-clamp` in Tables.css).
 *
 * The clamp keeps the tables dense, but the tail it cuts off is often where the
 * useful detail sits — you see "Rev $4.02B (+40% YoY); GM 72.5%; op margin…" and
 * the rest is gone. So this measures the clamp and, ONLY when the text is really
 * cut off, turns the cell into something you can open: the cell gets a "⋯" mark,
 * a zoom cursor, and click / Enter / Space reveals the whole value.
 *
 * Two ways to reveal it:
 *   • default — a dialog (best for the Screener, where a cell is a compact
 *     figure and the dialog can also show the full source paragraph);
 *   • `inline` — the cell expands in place and a second click / Escape
 *     collapses it again (best for the Timelines, where a cell IS the
 *     paragraph and you want to keep reading down the column).
 *
 * A cell that already fits keeps zero chrome — no marks on a table of short cells.
 *
 * The DOM stays exactly `<div class="cell">…</div>` so every existing rule (the
 * clamp itself, the mobile card layout, `.cb-source`) keeps applying unchanged.
 */
export default function CellText({
  text,
  label,
  subject,
  detail,
  className,
  children,
  inline = false,
}: {
  /** Plain text of the cell — also the dialog body. */
  text: string;
  /** Column name, shown as a chip in the dialog ("Guidance"). */
  label: string;
  /** Row subject, usually the company name, shown as the dialog title. */
  subject?: string;
  /** Optional richer source behind the value. */
  detail?: CellDetail;
  /** Extra classes for the cell div (e.g. "nowrap", "cb-source", "tb-clamp"). */
  className?: string;
  /** Rendered instead of `text` when the cell holds markup (a company link). */
  children?: ReactNode;
  /** Expand in place instead of opening a dialog. */
  inline?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [clipped, setClipped] = useState(false);
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);

  // A cell is clipped when its content is taller than the box (line-clamp) or
  // wider than it (nowrap + ellipsis). Re-measure on resize: the same cell fits
  // on a wide screen and overflows on a narrow one, and the tables are fluid.
  // Expanding an inline cell also changes its height, so the observer fires
  // and `clipped` drops to false while it is open.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // Loop guard. If a style rule ever makes the box change when `clipped`
    // toggles, measure → re-render → resize → measure would never settle and
    // the whole tab freezes. Measurements are coalesced to one per animation
    // frame, and if the value flips back and forth too often in a short window
    // we stop observing that cell (it keeps its last value) instead of hanging.
    let last: boolean | null = null;
    let flips = 0;
    let windowStart = performance.now();
    let raf = 0;
    let ro: ResizeObserver | null = null;
    const measure = () => {
      raf = 0;
      const next = el.scrollHeight > el.clientHeight + 1 || el.scrollWidth > el.clientWidth + 1;
      if (last !== null && next !== last) {
        const now = performance.now();
        if (now - windowStart > 1000) {
          windowStart = now;
          flips = 0;
        }
        if (++flips > 6 && ro) {
          ro.disconnect(); // give up on this cell rather than loop
          ro = null;
          return;
        }
      }
      last = next;
      setClipped(next);
    };
    const schedule = () => {
      if (!raf) raf = requestAnimationFrame(measure);
    };
    measure();
    ro = new ResizeObserver(schedule);
    ro.observe(el);
    return () => {
      if (raf) cancelAnimationFrame(raf);
      if (ro) ro.disconnect();
    };
  }, [text]);

  // Esc closes the dialog, like the node panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // An expanded inline cell no longer measures as clipped, but it must stay
  // interactive — otherwise there would be no way to collapse it again.
  const isExpanded = inline && expanded;
  const interactive = clipped || isExpanded;

  const activate = () => {
    if (inline) setExpanded((v) => !v);
    else setOpen(true);
  };

  const cls = ["cell", className, clipped ? "clipped" : "", isExpanded ? "tb-expanded" : ""]
    .filter(Boolean)
    .join(" ");

  // Accessible name for the button role: what pressing it will do.
  const ariaLabel = interactive
    ? subject
      ? t(isExpanded ? "Collapse {label} for {subject}" : "Show full {label} for {subject}", { label, subject })
      : t(isExpanded ? "Collapse {label}" : "Show full {label}", { label })
    : undefined;

  return (
    <>
      <div
        ref={ref}
        className={cls}
        // Only an interactive cell gets a tooltip: the full text while it is
        // clipped (a plain mouse hover), a hint once it is expanded.
        title={clipped ? text : isExpanded ? t("Click to collapse") : undefined}
        role={interactive ? "button" : undefined}
        tabIndex={interactive ? 0 : undefined}
        aria-label={ariaLabel}
        aria-expanded={inline && interactive ? isExpanded : undefined}
        onClick={(e) => {
          if (!interactive) return;
          // A company link inside the cell owns its own click (it opens the node
          // panel), so never hijack it.
          if ((e.target as HTMLElement).closest("button, a")) return;
          activate();
        }}
        onKeyDown={(e) => {
          if (!interactive) return;
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            activate();
          } else if (e.key === "Escape" && isExpanded) {
            setExpanded(false);
          }
        }}
      >
        {children ?? text}
      </div>

      {open && <CellDialog {...{ text, label, subject, detail }} onClose={() => setOpen(false)} />}
    </>
  );
}

/**
 * The reader. Rendered into <body> through a portal: the tables live inside
 * `.tbl-wrap`, which is an `overflow: auto` box, and a dialog rendered inside it
 * would be clipped and would scroll with the table.
 */
function CellDialog({
  text,
  label,
  subject,
  detail,
  onClose,
}: {
  text: string;
  label: string;
  subject?: string;
  detail?: CellDetail;
  onClose: () => void;
}) {
  // The portal target only exists in the browser, so mount before rendering.
  const [ready, setReady] = useState(false);
  useEffect(() => setReady(true), []);
  if (!ready) return null;

  // Only worth a second block when the underlying signal says more than the
  // figure already on screen.
  const extra = detail?.signal && detail.signal.trim() !== text.trim() ? detail.signal : null;

  return createPortal(
    <div className="cell-backdrop" onClick={onClose} role="presentation">
      <div
        className="cell-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${subject ? subject + " — " : ""}${label}`}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="panel-close" onClick={onClose} aria-label={t("Close")}>
          ✕
        </button>
        <div className="cell-modal-head">
          {subject && <span className="cell-modal-subject">{subject}</span>}
          <span className="tag">{label}</span>
        </div>
        <p className="cell-modal-body">{text}</p>
        {extra && (
          <div className="cell-modal-detail">
            <div className="cell-modal-detail-h">
              {t("Full signal")}
              {/* The source label is a proper name ("NVIDIA Q1 FY2027 …"); the
                  heading is uppercased, so it rides in its own normal-case span. */}
              {detail?.source && (
                <span className="cell-modal-src">
                  <SourceBadge label={detail.source} /> {detail.source}
                </span>
              )}
            </div>
            <p>{extra}</p>
          </div>
        )}
        {!extra && detail?.source && (
          <div className="cell-modal-detail-h" style={{ marginTop: "0.9rem" }}>
            {t("Source")}
            <span className="cell-modal-src">
              <SourceBadge label={detail.source} /> {detail.source}
            </span>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
