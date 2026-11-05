// A data file of a figure with a small preview table (first rows of a CSV/TSV), opened on demand.
import { useState } from 'react';
import { Icon } from '../../components/icons';
import { Spinner } from '../../components/ui';
import { useT } from '../../i18n';
import { errMessage, vz } from './api';

const MAX_ROWS = 30;

/** RFC 4180-ish: quoted fields, doubled quotes, commas (or tabs) inside quotes. */
export function parseDelimited(text: string, sep = text.split('\n', 1)[0].includes('\t') ? '\t' : ','): string[][] {
  const rows: string[][] = [];
  let row: string[] = [], field = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') { field += '"'; i++; }
      else if (c === '"') quoted = false;
      else field += c;
    } else if (c === '"' && field === '') quoted = true;
    else if (c === sep) { row.push(field); field = ''; }
    else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++;
      row.push(field); field = '';
      if (row.some(f => f !== '')) rows.push(row);
      row = [];
    } else field += c;
  }
  if (field !== '' || row.length) { row.push(field); if (row.some(f => f !== '')) rows.push(row); }
  return rows;
}

export function CsvPreview({ projectId, path }: { projectId: string; path: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [rows, setRows] = useState<string[][] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isTable = /\.(csv|tsv|txt)$/i.test(path);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && isTable) {
      setError(null);
      vz.readFile(projectId, path).then(f => setRows(parseDelimited(f.content))).catch(e => setError(errMessage(e)));
    }
  };

  const [head, ...body] = rows ?? [];
  return (
    <div className="vz-csv">
      <button type="button" className="vz-csv-head" onClick={toggle} aria-expanded={open}>
        <Icon name={open ? 'chevronDown' : 'chevronRight'} size={14} />
        <Icon name="file" size={14} />
        <span className="mono ellipsis grow">{path}</span>
        {rows && <span className="faint num" style={{ fontSize: 'var(--fs-xs)' }}>{t('vz.mpl.rows', { n: Math.min(MAX_ROWS, body.length), total: body.length })}</span>}
      </button>
      {open && isTable && (error ? <div className="notice accent">{t('vz.mpl.csvError', { msg: error })}</div>
        : !rows ? <div className="vz-pad"><Spinner /></div>
        : (
          <div className="vz-csv-table">
            <table className="table">
              <thead><tr>{head?.map((h, i) => <th key={i}>{h}</th>)}</tr></thead>
              <tbody>{body.slice(0, MAX_ROWS).map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="num">{c}</td>)}</tr>)}</tbody>
            </table>
          </div>
        ))}
    </div>
  );
}
