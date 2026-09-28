"use client";

import { memo, useEffect, useId, useMemo, useRef, useState } from "react";
import type { VizNode } from "@/lib/types";
import { GROUP_NAMES } from "@/lib/taxonomy";
import { buildSearchIndex, searchNodes, loadRecent, pushRecent, type SearchHit } from "@/lib/search";
// The `.srch-*` styles live in Sidebar.css (this agent's shared stylesheet).
// Next's app router lets any client component import a global CSS file; the
// bundler includes it once no matter how many components import it.
import "./Sidebar.css";

interface Props {
  nodes: VizNode[]; // the companies to search over (pass the VISIBLE ones)
  onPick: (id: string) => void; // called with the node id the user chose
  onClear?: () => void; // optional: called when the ✕ button empties the box
  // Optional: Korean names per company ({ "SK Hynix": ["SK하이닉스", …] }) so Korean input works.
  aliases?: Record<string, string[]>;
  // Optional: called with the typed component and the ids of EVERY company that makes it
  // when the user picks the "show on graph" row. Without it that row is not offered.
  onPickGroup?: (label: string, ids: string[]) => void;
  placeholder?: string;
  inputId?: string;
  shortcut?: boolean;
}

// A component can have 100+ makers ("power"), and the user asked to see them all —
// the list scrolls (max-height in Sidebar.css).
const MAX_ROWS = 200;

// A typeahead search box: type a company name (English or Korean), ticker, product,
// component or sector and pick a result with the mouse or ↑ ↓ Enter. With an empty
// query it offers the last 8 picks (remembered in localStorage under "aisc.recent").
export default function SearchBox({
  nodes,
  onPick,
  onClear,
  aliases,
  onPickGroup,
  placeholder = "Search company, ticker, product…",
  inputId,
  shortcut = false,
}: Props) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0); // index of the highlighted row
  const [recent, setRecent] = useState<string[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId(); // stable ids for the aria wiring (input ↔ listbox ↔ option)

  // localStorage only exists in the browser, so read it after mount — never
  // during render (the server would produce different HTML and React would warn).
  useEffect(() => {
    setRecent(loadRecent());
  }, []);

  useEffect(() => {
    if (!shortcut) return;
    const focusSearch = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey ||
          target?.closest("input, textarea, select, [contenteditable='true'], [role='dialog']")) return;
      event.preventDefault();
      inputRef.current?.focus();
    };
    document.addEventListener("keydown", focusSearch);
    return () => document.removeEventListener("keydown", focusSearch);
  }, [shortcut]);

  // Built once per node list, not per keystroke.
  const index = useMemo(() => buildSearchIndex(nodes, aliases), [nodes, aliases]);
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);

  const query = q.trim();
  const result = useMemo(() => (query ? searchNodes(index, query, MAX_ROWS) : null), [query, index]);
  const rows: SearchHit[] = useMemo(() => {
    if (result) return result.hits;
    // Empty query → recent picks, but only the ones still in the current list.
    return recent
      .map((id) => byId.get(id))
      .filter((n): n is VizNode => !!n)
      .map((node) => ({ node, kind: "name" as const, why: null, score: 0 }));
  }, [result, recent, byId]);
  const showingRecent = !query && rows.length > 0;

  // The "show on graph" row for a component (2+ makers). It sits first in the list, so
  // the keyboard index counts it as row 0 and the companies start at `offset`.
  const group = onPickGroup && result?.group ? result.group : null;
  const offset = group ? 1 : 0;
  const total = rows.length + offset;

  // Whenever the list changes, highlight its first row again.
  useEffect(() => {
    setActive(0);
  }, [query, total]);

  // Keep the highlighted row scrolled into view while arrowing through a long list.
  useEffect(() => {
    if (!open) return;
    listRef.current
      ?.querySelector<HTMLElement>(`[data-idx="${active}"]`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active, open]);

  const pick = (id: string) => {
    setRecent(pushRecent(id));
    setQ(id); // leave the chosen name in the box so the user sees what is focused
    setOpen(false);
    onPick(id);
  };

  // Show every maker of the typed component on the graph. The text stays in the box.
  const pickGroup = () => {
    if (!group || !onPickGroup) return;
    setOpen(false);
    onPickGroup(group.label, group.ids);
  };

  const clear = () => {
    setQ("");
    setOpen(false);
    onClear?.();
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) setOpen(true);
      else setActive((a) => Math.min(a + 1, Math.max(total - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      if (open && group && active === 0) {
        e.preventDefault();
        pickGroup();
        return;
      }
      const hit = rows[active - offset] || rows[0];
      if (open && hit) {
        e.preventDefault();
        pick(hit.node.id);
      }
    } else if (e.key === "Escape") {
      if (open) {
        // We consumed this Esc (closing the list) — don't let a modal behind us
        // also react to it.
        e.preventDefault();
        e.stopPropagation();
        setOpen(false);
      } else if (q) {
        clear();
      }
    }
  };

  const activeId = open && active < total ? `${listId}-opt-${active}` : undefined;

  return (
    <div className="srch">
      <div className="srch-input-wrap">
        <input
          id={inputId}
          ref={inputRef}
          type="search"
          className="srch-input"
          role="combobox"
          aria-expanded={open}
          aria-controls={`${listId}-list`}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          aria-label="Search company, ticker, or product"
          aria-keyshortcuts={shortcut ? "/" : undefined}
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
          }}
          onFocus={(e) => {
            // Select the text so typing replaces a previous pick instead of appending.
            e.target.select();
            setOpen(true);
          }}
          onBlur={() => setOpen(false)}
          onKeyDown={onKeyDown}
        />
        {q && (
          <button
            type="button"
            className="srch-clear"
            aria-label="Clear search"
            // Keep pointer focus in the input; click also supports Enter/Space.
            onMouseDown={(e) => {
              e.preventDefault();
            }}
            onClick={() => {
              clear();
              inputRef.current?.focus();
            }}
          >
            ✕
          </button>
        )}
      </div>

      {open && (query || showingRecent) && (
        <div
          className="srch-list"
          id={`${listId}-list`}
          role="listbox"
          ref={listRef}
          // Clicking inside the list must not blur the input (blur closes the list
          // before the row's onClick could fire).
          onMouseDown={(e) => e.preventDefault()}
        >
          {showingRecent && <div className="srch-sec">Recent</div>}
          {rows.length === 0 && <div className="srch-empty">No company matches “{query}”</div>}
          {group && (
            <button
              type="button"
              id={`${listId}-opt-0`}
              role="option"
              tabIndex={-1}
              aria-selected={active === 0}
              data-idx={0}
              className={"srch-row srch-group" + (active === 0 ? " on" : "")}
              onMouseEnter={() => setActive(0)}
              onClick={pickGroup}
            >
              <span className="srch-group-icon" aria-hidden="true">◎</span>
              <span className="srch-name">
                “{group.label}”
                {group.terms.length > 0 && <span className="srch-group-terms"> → {group.terms.join(", ")}</span>}
              </span>
              <span className="srch-hint">
                {group.ids.length} companies · show on graph
              </span>
            </button>
          )}
          {rows.map((h, i) => (
            <ResultRow
              key={h.node.id}
              id={`${listId}-opt-${i + offset}`}
              idx={i + offset}
              hit={h}
              on={i + offset === active}
              onHover={setActive}
              onPick={pick}
            />
          ))}
          {rows.length > 0 && (
            <div className="srch-kbd">↑ ↓ to move · Enter to open · Esc to close</div>
          )}
        </div>
      )}
    </div>
  );
}

// One result row. memo() so hovering (which re-renders the parent to move the
// highlight) does not re-render every other row.
const ResultRow = memo(function ResultRow({
  id,
  idx,
  hit,
  on,
  onHover,
  onPick,
}: {
  id: string;
  idx: number;
  hit: SearchHit;
  on: boolean;
  onHover: (i: number) => void;
  onPick: (id: string) => void;
}) {
  const n = hit.node;
  const chains = n.chains.length;
  return (
    <button
      type="button"
      id={id}
      role="option"
      tabIndex={-1}
      aria-selected={on}
      data-idx={idx}
      className={"srch-row" + (on ? " on" : "")}
      onMouseEnter={() => onHover(idx)}
      onClick={() => onPick(n.id)}
    >
      <span className="srch-dot" style={{ background: n.color }} />
      <span className="srch-name">{n.id}</span>
      {n.ticker && <span className="srch-tick">{n.ticker}</span>}
      {(hit.kind === "product" || hit.kind === "ko") && hit.why && (
        <span className="srch-why" title={hit.why}>
          {hit.why}
        </span>
      )}
      <span className="srch-hint">
        {GROUP_NAMES[n.primary] || n.primary}
        {chains > 0 ? ` · ${chains} chain${chains === 1 ? "" : "s"}` : ""}
      </span>
    </button>
  );
});
