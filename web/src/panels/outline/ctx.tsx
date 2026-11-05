// The outline page's shared state: the outline, which item is selected, which sub-chains are open, what is being
// edited (an item's text, or a new item and where it goes), and `run`, which applies outline ops and reloads.
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { ApiError } from '../../api/client';
import { useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { useI18n } from '../../i18n';
import { outlineApi, type Item, type Outline, type OutlineOp, type OpsResult, type Step, type Task } from './api';
import { itemIndex, pathTo, taskIndex } from './model';

/** Where a new item goes: after an item (the next step), beside it (parallel), first, or at the end of the parent. */
export type At = { after: string } | { parallel: string } | { first: true } | Record<string, never>;
export type Editing = { kind: 'text'; id: string } | { kind: 'new'; parent: string; at: At; text?: string };
export type DialogSpec =
  | { kind: 'fork'; item: string }
  | { kind: 'abandon'; item: string; direction: string }
  | { kind: 'remove'; item: string }
  | { kind: 'task'; item?: string; task?: string }
  | { kind: 'link'; item: string }
  | { kind: 'leave'; phase: string };

interface OlValue {
  pid: string; o: Outline; lang: 'zh' | 'en';
  items: Map<string, Item>; tasks: Map<string, Task>;
  sel: string | null; select: (id: string | null, opts?: { reveal?: boolean }) => void;
  isOpen: (it: Item) => boolean; toggle: (id: string, open?: boolean) => void;
  showAbandoned: boolean; setShowAbandoned: (v: boolean) => void;
  editing: Editing | null; setEditing: (e: Editing | null) => void;
  run: (ops: OutlineOp[]) => Promise<OpsResult | null>;
  busy: boolean; error: string | null; setError: (e: string | null) => void; note: string | null;
  dialog: DialogSpec | null; openDialog: (d: DialogSpec | null) => void;
  reload: () => Promise<void>;
  /** The item above this one in its chain (what Tab puts it under), or null for the first. */
  itemBefore: (id: string) => string | null;
  /** The steps an item or a section holds. */
  stepsOf: (id: string) => Step[];
}

const Ctx = createContext<OlValue | null>(null);

export function errMsg(e: unknown): string {
  if (e instanceof ApiError) {
    const d = e.detail as { message?: string; error?: string } | string | null;
    return typeof d === 'string' ? d : d?.message ?? d?.error ?? e.message;
  }
  return String((e as Error)?.message ?? e);
}

function readJson<T>(key: string, fallback: T): T {
  try { const v = localStorage.getItem(key); return v ? (JSON.parse(v) as T) : fallback; } catch { return fallback; }
}
function writeJson(key: string, v: unknown): void {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* storage unavailable */ }
}

export function OutlineProvider({ o, children }: { o: Outline; children: ReactNode }) {
  const { projectId } = useApp();
  const { lang } = useI18n();
  const today = useToday();
  const pid = projectId!;
  const items = useMemo(() => itemIndex(o), [o]);
  const tasks = useMemo(() => taskIndex(o), [o]);
  const [sel, setSel] = useState<string | null>(null);
  // Sub-chains are folded below the first level unless opened (remembered per project in this browser).
  const openKey = `rd.outline.open.${pid}`;
  const [open, setOpen] = useState<Record<string, boolean>>(() => readJson(openKey, {}));
  useEffect(() => { setOpen(readJson(openKey, {})); }, [openKey]);
  const [showAbandoned, setShowAbandoned] = useState(false);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [dialog, openDialog] = useState<DialogSpec | null>(null);

  const toggle = useCallback((id: string, v?: boolean) => {
    setOpen(prev => { const next = { ...prev, [id]: v ?? !prev[id] }; writeJson(openKey, next); return next; });
  }, [openKey]);
  const isOpen = useCallback((it: Item) => open[it.id] ?? false, [open]);

  const select = useCallback((id: string | null, opts?: { reveal?: boolean }) => {
    setSel(id);
    if (id && opts?.reveal) {
      const path = pathTo(o, id);
      if (path) {
        setOpen(prev => {
          const next = { ...prev };
          for (const it of path.items.slice(0, -1)) next[it.id] = true;
          writeJson(openKey, next);
          return next;
        });
        if (path.items.some(i => i.state === 'abandoned')) setShowAbandoned(true);
      }
      window.setTimeout(() => document.getElementById(`ol-i-${id}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' }), 60);
    }
  }, [o, openKey]);

  const stepsOf = useCallback((id: string): Step[] => o.sections.find(s => s.id === id)?.items ?? items.get(id)?.children ?? [], [o, items]);
  const itemBefore = useCallback((id: string): string | null => {
    const it = items.get(id);
    if (!it) return null;
    const steps = stepsOf(it.parent);
    for (let si = 0; si < steps.length; si++) {
      const pos = steps[si].items.findIndex(x => x.id === id);
      if (pos > 0) return steps[si].items[pos - 1].id;
      if (pos === 0) return si > 0 ? steps[si - 1].items[steps[si - 1].items.length - 1].id : null;
    }
    return null;
  }, [items, stepsOf]);

  const reload = today.reloadOutline;
  const run = useCallback(async (ops: OutlineOp[]) => {
    setBusy(true); setError(null); setNote(null);
    try {
      const res = await outlineApi.ops(pid, ops, lang);
      if (!res.applied && res.proposal) setNote('proposed');
      await reload();
      return res;
    } catch (e) {
      setError(errMsg(e));
      return null;
    } finally { setBusy(false); }
  }, [pid, lang, reload]);

  const value = useMemo<OlValue>(() => ({
    pid, o, lang, items, tasks, sel, select, isOpen, toggle, showAbandoned, setShowAbandoned, editing, setEditing,
    run, busy, error, setError, note, dialog, openDialog, reload, itemBefore, stepsOf,
  }), [pid, o, lang, items, tasks, sel, select, isOpen, toggle, showAbandoned, editing, run, busy, error, note, dialog, reload, itemBefore, stepsOf]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useOl(): OlValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useOl outside OutlineProvider');
  return v;
}
