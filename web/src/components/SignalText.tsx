"use client";

// SignalText.tsx — the compact way a signal / contract is shown (added 2026-10-04).
//
// Signals run long (median ~500 characters, some 3,000), so a company panel with
// dozens of them was a wall of text. Every entry now reads in this order:
//
//   [Earnings] 08-26-2026  Q2 FY2027            ← source-type badge, date, source
//   supply 70% vs demand 100%; …                ← the entry's `figure` = headline
//   'Our entire supply chain is challenged…     ← the signal, clamped to 2 lines
//   More ▾                                      ← only when something is cut off
//
// Nothing is summarised or rewritten: the figure was written by the enricher, the
// signal is the full original text (just visually clamped), and translations,
// the evidence button and the source label are unchanged.
//
// Pieces:
//   <SourceBadge label=… />      the coloured "Earnings / 8-K / Deck / Q&A …" chip
//   <SignalBody headline text /> headline + clamped text + More/Less toggle
//   ExpandAllContext             a panel-wide "Expand all" switch (NodePanel)

import {
  createContext,
  useContext,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { t } from "@/lib/i18n";
import { SOURCE_HINT, sourceType } from "@/lib/sourceKind";
import "./SignalText.css";

/** The source-type chip for one source label ("Earnings", "8-K", "Deck" …). */
export function SourceBadge({ label }: { label: string }) {
  const { kind, badge } = sourceType(label);
  return (
    <span className={"sx-badge sx-k-" + kind} title={t(SOURCE_HINT[kind])}>
      {t(badge)}
    </span>
  );
}

/**
 * A source label shown on ONE line, cut with "…" when it does not fit (`short`
 * is the trimmed form, e.g. "Goldman Sachs Communacopia + Technology Confe…").
 * Only when it is really cut off does it become a control: click, tap, Enter
 * or Space shows the FULL label ("Cisco Goldman Sachs … 2026 (09-08-2026)") on
 * its own line; again hides it. A label that fits stays plain text.
 */
export function SourceText({ label, short, className = "" }: { label: string; short: string; className?: string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [cut, setCut] = useState(false);
  const [open, setOpen] = useState(false);

  // Measured while closed (the open form wraps, so it is never "cut").
  // The same element is kept in both states, so the observer stays attached.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || open) return;
    const measure = () => setCut(el.scrollWidth > el.clientWidth + 1);
    measure();
    return watchSize(el, measure);
  }, [label, short, open]);

  const interactive = cut || open;
  const toggle = () => setOpen((o) => !o);
  return (
    <span
      ref={ref}
      className={className + " sx-src" + (interactive ? " sx-src-cut" : "") + (open ? " sx-src-open" : "")}
      title={open ? t("Click to collapse") : label}
      role={interactive ? "button" : undefined}
      tabIndex={interactive ? 0 : undefined}
      aria-expanded={interactive ? open : undefined}
      aria-label={interactive && !open ? t("Show full source: {label}", { label }) : undefined}
      onClick={interactive ? toggle : undefined}
      onKeyDown={
        interactive
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                toggle();
              }
            }
          : undefined
      }
    >
      {open ? label : short}
    </span>
  );
}

/** true = every SignalBody inside shows its full text ("Expand all"). */
export const ExpandAllContext = createContext(false);

// ── One shared ResizeObserver for every SignalBody on the page ──────────────
// A company panel can hold 100+ entries. Each one registers a callback; the
// observer collects the elements that changed size and runs their callbacks
// once, in the next animation frame (so a burst of resizes = one measurement).
const callbacks = new Map<Element, () => void>();
const queued = new Set<() => void>();
let observer: ResizeObserver | null = null;
let frame = 0;

function watchSize(el: Element, onResize: () => void): () => void {
  if (typeof ResizeObserver === "undefined") return () => {};
  if (!observer) {
    observer = new ResizeObserver((entries) => {
      for (const e of entries) {
        const fn = callbacks.get(e.target);
        if (fn) queued.add(fn);
      }
      if (!frame)
        frame = requestAnimationFrame(() => {
          frame = 0;
          const fns = [...queued];
          queued.clear();
          fns.forEach((fn) => fn());
        });
    });
  }
  callbacks.set(el, onResize);
  observer.observe(el);
  return () => {
    callbacks.delete(el);
    observer?.unobserve(el);
  };
}

// Is the text taller than `lines` lines? scrollHeight is the FULL content height
// both while clamped (overflow: hidden) and while open, so one test serves both —
// the "Less" button only appears on text that really was cut.
function tallerThan(el: HTMLElement, lines: number): boolean {
  const cs = getComputedStyle(el);
  const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.45;
  return el.scrollHeight > Math.ceil(lh * lines) + 2;
}

/**
 * A headline (the entry's figure, optional) over a text clamped to `lines`
 * lines. A More / Less button appears only when something is actually cut off;
 * `footer` (tags…) shares the button's row so a short entry adds no extra line.
 */
export function SignalBody({
  headline,
  text,
  lines = 2,
  headLines = 2,
  footer,
}: {
  headline?: string;
  text: string;
  lines?: number;
  headLines?: number;
  footer?: ReactNode;
}) {
  const all = useContext(ExpandAllContext);
  // The reader's own choice for THIS entry; null = follow "Expand all". A new
  // Expand all / Collapse all click resets it (state adjusted during render, the
  // React-documented way to derive state from a changed prop — no extra frame).
  const [own, setOwn] = useState<{ all: boolean; open: boolean | null }>({ all, open: null });
  if (own.all !== all) setOwn({ all, open: null });
  const open = own.all === all && own.open !== null ? own.open : all;

  const headRef = useRef<HTMLDivElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const [long, setLong] = useState(false);
  const id = useId();

  useLayoutEffect(() => {
    const els: [HTMLElement, number][] = [];
    if (headRef.current) els.push([headRef.current, headLines]);
    if (textRef.current) els.push([textRef.current, lines]);
    // Loop guard (same idea as CellText): if a layout ever made the answer flip
    // back and forth — e.g. the panel's scrollbar appearing and disappearing as
    // the button row comes and goes — stop measuring rather than spin.
    let last: boolean | null = null;
    let flips = 0;
    let since = performance.now();
    let stop = false;
    const measure = () => {
      if (stop) return;
      const next = els.some(([el, n]) => tallerThan(el, n));
      if (last !== null && next !== last) {
        const now = performance.now();
        if (now - since > 1000) {
          since = now;
          flips = 0;
        }
        if (++flips > 6) stop = true;
      }
      last = next;
      setLong(next);
    };
    measure();
    const undo = els.map(([el]) => watchSize(el, measure));
    return () => undo.forEach((fn) => fn());
  }, [text, headline, lines, headLines]);

  return (
    <>
      <div id={id} className="sx-body">
        {headline && (
          <div ref={headRef} className={"sx-head" + (open ? "" : " sx-clamp")} style={open ? undefined : { WebkitLineClamp: headLines }}>
            {headline}
          </div>
        )}
        {text && (
          <div ref={textRef} className={"sx-text" + (open ? "" : " sx-clamp")} style={open ? undefined : { WebkitLineClamp: lines }}>
            {text}
          </div>
        )}
      </div>
      {(long || footer) && (
        <div className="sx-foot">
          {long && (
            <button
              type="button"
              className="sx-more"
              aria-expanded={open}
              aria-controls={id}
              onClick={() => setOwn({ all, open: !open })}
            >
              {open ? t("Less") : t("More")}
              <span aria-hidden="true">{open ? " ▴" : " ▾"}</span>
            </button>
          )}
          {footer}
        </div>
      )}
    </>
  );
}
