// A compact unified line diff (jsdiff) of the current source against a proposal; long unchanged runs fold.
import { useMemo, useState } from 'react';
import { diffLines } from 'diff';
import { useT } from '../../i18n';

const CONTEXT = 3;

interface Row { t: '+' | '-' | ' '; text: string; old: number | null; new: number | null }
type Item = { kind: 'row'; row: Row } | { kind: 'fold'; rows: Row[]; id: number };

function splitLines(value: string): string[] {
  const lines = value.split('\n');
  if (lines.length && lines[lines.length - 1] === '') lines.pop();
  return lines;
}

export function diffRows(before: string, after: string): { rows: Row[]; add: number; del: number } {
  const rows: Row[] = [];
  let o = 1, n = 1, add = 0, del = 0;
  for (const part of diffLines(before, after)) {
    for (const text of splitLines(part.value)) {
      if (part.added) { rows.push({ t: '+', text, old: null, new: n++ }); add++; }
      else if (part.removed) { rows.push({ t: '-', text, old: o++, new: null }); del++; }
      else rows.push({ t: ' ', text, old: o++, new: n++ });
    }
  }
  return { rows, add, del };
}

function fold(rows: Row[]): Item[] {
  const items: Item[] = [];
  let i = 0, id = 0;
  while (i < rows.length) {
    if (rows[i].t !== ' ') { items.push({ kind: 'row', row: rows[i++] }); continue; }
    let j = i;
    while (j < rows.length && rows[j].t === ' ') j++;
    const run = rows.slice(i, j);
    const head = i === 0 ? 0 : CONTEXT, tail = j === rows.length ? 0 : CONTEXT;
    if (run.length > head + tail + 2) {
      run.slice(0, head).forEach(row => items.push({ kind: 'row', row }));
      items.push({ kind: 'fold', rows: run.slice(head, run.length - tail), id: id++ });
      run.slice(run.length - tail).forEach(row => items.push({ kind: 'row', row }));
    } else run.forEach(row => items.push({ kind: 'row', row }));
    i = j;
  }
  return items;
}

export function DiffView({ before, after, maxHeight }: { before: string; after: string; maxHeight?: number | string }) {
  const t = useT();
  const items = useMemo(() => fold(diffRows(before, after).rows), [before, after]);
  const [open, setOpen] = useState<Set<number>>(new Set());
  const line = (row: Row, key: string | number) => (
    <tr key={key} className={row.t === '+' ? 'diff-add' : row.t === '-' ? 'diff-del' : ''}>
      <td className="vz-diff-no">{row.old ?? ''}</td>
      <td className="vz-diff-no">{row.new ?? ''}</td>
      <td className="vz-diff-sign">{row.t === ' ' ? '' : row.t === '-' ? '−' : '+'}</td>
      <td className="vz-diff-text">{row.text || ' '}</td>
    </tr>
  );
  return (
    <div className="vz-diff" style={{ maxHeight }}>
      <table>
        <tbody>
          {items.map((it, k) => it.kind === 'row' ? line(it.row, k) : open.has(it.id)
            ? it.rows.map((row, r) => line(row, `${k}-${r}`))
            : (
              <tr key={k} className="vz-diff-fold">
                <td colSpan={4}>
                  <button type="button" onClick={() => setOpen(s => new Set(s).add(it.id))}>{t('vz.ai.unchanged', { n: it.rows.length })}</button>
                </td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}
