// Inspector tabs other than Overview: Edges (seen vs current, Attest), Cells (freshness matrix, selected vs newest run,
// trace quality, GPU-h, platform, trace mismatches, select / exclude runs), History (versions with facet diffs and
// "Roll back to rK" → impact preview), Why (plain-language root-cause chains) and Agent (explain / propose a fix).
import { Fragment, useEffect, useMemo, useState } from 'react';
import { diffWords } from 'diff';
import { Icon } from '../../components/icons';
import { Button, Dialog, Spinner } from '../../components/ui';
import { useRelTime, useT } from '../../i18n';
import { dagApi, parseAddr } from '../../dag/api';
import { FreshBadge, useDagLabels } from '../../dag/encoding';
import type { CellEval, DagNode, NodeDetail, NodeEval, Reason, RunSummary, Version, WhyChain } from '../../dag-types';
import type { InspectorProps } from './Inspector';
import { edgeKey, edgeMoved, fmtGpuH, reasonsForEdge, shortFp } from './model';
import { errText } from './preview';

type TabProps = InspectorProps & { node: DagNode; ev?: NodeEval; detail?: NodeDetail | null };

// ------------------------------------------------------------------ Edges

export function EdgesTab(p: TabProps) {
  const t = useT();
  const { node, ev, detail } = p;
  const [busy, setBusy] = useState(false);
  const edges = node.edges ?? [];
  const attestable = edges.filter(e => e.type !== 'input' && e.type !== 'cites' && edgeMoved(ev, e) && !(e.predicate || e.kill_if)).map(edgeKey);
  const attest = async (keys: string[]) => {
    setBusy(true);
    try { await p.onRun([{ op: 'attest', node: node.id, edges: keys }], t('dag.revise.attestTitle', { id: node.id })); } finally { setBusy(false); }
  };
  return (
    <div className="col dg-tab-body">
      <div className="row">
        <span className="label grow">{t('dag.edges.out', { n: edges.length })}</span>
        {!p.readOnly && attestable.length > 1 && <Button size="sm" icon="check" disabled={busy} onClick={() => attest(attestable)}>{t('dag.edges.attestAll', { n: attestable.length })}</Button>}
      </div>
      {edges.length === 0 && <div className="muted">{t('dag.edges.none')}</div>}
      <ul className="dg-edges">
        {edges.map(e => {
          const k = edgeKey(e);
          const a = parseAddr(e.to);
          const rs = reasonsForEdge(ev, k);
          const moved = edgeMoved(ev, e);
          const worst = rs.find(r => r.level === 'broken') ?? rs.find(r => r.level === 'orphaned') ?? moved ?? rs[0];
          const current = moved?.to ?? null;
          return (
            <li key={k} className={`dg-edge-row ${moved ? 'is-moved' : ''}`}>
              <div className="row" style={{ gap: 6 }}>
                <span className={`dg-etype is-${e.type}`}>{t(`dag.edge.${e.type}`)}</span>
                {e.polarity && <span className={`badge ${e.polarity === 'refutes' ? 'accent' : 'ok'}`}>{t(`dag.edge.${e.polarity}`)}</span>}
                {a.scheme === 'node'
                  ? <button type="button" className="dg-inline-link mono ellipsis" onClick={() => p.onSelect(a.id)} title={e.to}>{a.id}{a.facet ? `#${a.facet}` : ''}{a.selector ? `[${a.selector}]` : ''}</button>
                  : <span className="mono ellipsis" title={e.to}>{e.to}</span>}
                <span className="grow" />
                {worst && <FreshBadge level={worst.level} />}
              </div>
              {(e.predicate || e.kill_if) && (
                <div className="faint mono">{e.predicate ? `${e.predicate.agg} ${e.predicate.op} ${e.predicate.rhs}` : `kill_if ${e.kill_if!.agg} ${e.kill_if!.op} ${e.kill_if!.rhs}`}
                  {ev?.values && Object.keys(ev.values).length > 0 && <span> · {Object.entries(ev.values).slice(0, 2).map(([k2, v]) => `${k2}=${v ?? '∅'}`).join(', ')}</span>}
                </div>
              )}
              {e.type !== 'input' && e.type !== 'cites' && (
                <div className="dg-seen mono">
                  <span title={e.seen}>{t('dag.edges.seen')} {shortFp(e.seen)}</span>
                  <Icon name="chevronRight" size={10} />
                  <span title={current ?? ''}>{t('dag.edges.current')} {moved ? shortFp(current) : t('dag.edges.same')}</span>
                  {e.pin && <span className="badge" title={e.pin}><Icon name="pin" size={10} />{t('dag.edges.pinned')}</span>}
                </div>
              )}
              {rs.filter(r => r.note).map((r, i) => <div key={i} className="muted dg-reason-note">{r.note}</div>)}
              {!p.readOnly && moved && attestable.includes(k) && (
                <div><Button size="sm" icon="check" disabled={busy} onClick={() => attest([k])} title={t('dag.revise.attestHint')}>{t('dag.edges.attest')}</Button></div>
              )}
            </li>
          );
        })}
      </ul>
      {detail?.dependents && detail.dependents.length > 0 && (
        <>
          <span className="label">{t('dag.edges.in', { n: detail.dependents.length })}</span>
          <ul className="dg-rows">
            {detail.dependents.map(d => (
              <li key={`${d.edge}:${d.id}`} className="dg-row">
                <span className={`dg-etype is-${d.edge}`}>{t(`dag.edge.${d.edge}`)}</span>
                <button type="button" className="dg-inline-link mono" onClick={() => p.onSelect(d.id)}>{d.id}</button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ Cells

export function CellsTab(p: TabProps) {
  const t = useT();
  const rel = useRelTime();
  const { node, ev, detail } = p;
  const cells = ev?.cells ?? {};
  const ids = Object.keys(cells).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
  const [open, setOpen] = useState<string | null>(null);
  const [exclude, setExclude] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const runsOf = (c: string) => detail?.runs?.[c] ?? [];
  const totalGpu = ids.reduce((s, c) => s + (cells[c].gpu_h ?? 0), 0);
  const platforms = [...new Set(ids.map(c => cells[c].platform).filter((x): x is string => !!x))];

  const select = async (cell: string, run: string | null) => {
    setError(null);
    try { await dagApi.select(p.pid, node.id, cell, run); } catch (e) { setError(errText(e)); }
  };

  if (!ids.length) return <div className="dg-tab-body muted">{t('dag.cells.none')}</div>;
  return (
    <div className="col dg-tab-body">
      <div className="row faint"><span className="grow">{t('dag.cells.summary', { n: ids.length, h: fmtGpuH(totalGpu) })}{platforms.length ? ` · ${platforms.join(', ')}` : ''}</span></div>
      {error && <div className="notice accent"><Icon name="warn" /><span>{error}</span></div>}
      <div className="dg-table-wrap">
        <table className="table dg-cells-table">
          <thead><tr>
            <th>{t('dag.cells.cell')}</th><th>{t('dag.cells.level')}</th><th>{t('dag.cells.selected')}</th><th className="num">GPU·h</th>
          </tr></thead>
          <tbody>
            {ids.map(c => {
              const ce: CellEval = cells[c];
              const runs = runsOf(c);
              const sel = runs.find(r => r.id === ce.run) ?? null;
              const newest = runs[0] ?? null;
              const isOpen = open === c;
              return (
                <Fragment key={c}>
                  <tr className={`dg-cell-tr ${isOpen ? 'is-open' : ''}`} onClick={() => setOpen(isOpen ? null : c)}>
                    <td className="mono"><Icon name={isOpen ? 'chevronDown' : 'chevronRight'} size={10} /> {c}</td>
                    <td>
                      <FreshBadge level={ce.level} />
                      {ce.reused && <span className="badge" title={t('dag.cells.reusedHint')}>{t('dag.cells.reused')}</span>}
                      {ce.cutoff && <span className="badge" title={t('dag.cells.cutoffHint')}>≈</span>}
                      {ce.impl_lag && <span className="badge warn" title={t('dag.flag.impl_lag')}>{t('dag.flagShort.impl_lag')}</span>}
                    </td>
                    <td className="mono" title={[ce.run, newest && newest.id !== ce.run ? `${t('dag.cells.newest')}: ${newest.id}` : null].filter(Boolean).join('\n')}>
                      {ce.run ? shortRun(ce.run) : '—'}{node.selected?.[c] && <Icon name="pin" size={10} />}
                      {newest && newest.id !== ce.run && <span className="badge" style={{ marginLeft: 4 }}>{t('dag.cells.newer')}</span>}
                    </td>
                    <td className="num">{fmtGpuH(ce.gpu_h ?? sel?.gpu_hours)}</td>
                  </tr>
                  {isOpen && (
                    <tr className="dg-cell-detail"><td colSpan={4}>
                      <CellDetail {...p} cell={c} ce={ce} runs={runs} onSelectRun={r => select(c, r)} onExclude={setExclude} rel={rel} />
                    </td></tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {exclude && <ExcludeDialog pid={p.pid} run={exclude} onClose={() => setExclude(null)} />}
    </div>
  );
}

const shortRun = (id: string) => (id.length > 16 ? `…${id.slice(-11)}` : id);

function CellDetail(p: TabProps & { cell: string; ce: CellEval; runs: RunSummary[]; onSelectRun: (r: string | null) => void; onExclude: (r: RunSummary) => void; rel: (s: string | null | undefined) => string }) {
  const t = useT();
  const L = useDagLabels();
  const { ce, runs } = p;
  const sel = runs.find(r => r.id === ce.run) ?? null;
  return (
    <div className="col dg-cell-detail-body">
      <dl className="kv dg-cell-kv">
        <dt>{t('dag.cells.selected')}</dt><dd className="mono">{ce.run ?? '—'}</dd>
        <dt>{t('dag.cells.newest')}</dt><dd className="mono">{runs[0]?.id ?? '—'}</dd>
        <dt>{t('dag.cells.platform')}</dt><dd className="mono">{ce.platform ?? sel?.platform ?? '—'}</dd>
        {sel?.trace_quality && <><dt>{t('dag.cells.trace')}</dt><dd><span className={`badge ${sel.trace_quality === 'traced' ? 'ok' : sel.trace_quality === 'coarse' ? 'warn' : ''}`}>{t(`dag.trace.${sel.trace_quality}`)}</span></dd></>}
      </dl>
      {ce.why.length > 0 && (
        <div className="col" style={{ gap: 4 }}>
          <span className="label">{t('dag.cells.mismatch', { n: ce.why.length })}</span>
          <ul className="dg-mismatch">
            {ce.why.map((r, i) => <Mismatch key={i} r={r} onCoding={p.onOpenCoding} onSelect={p.onSelect} />)}
          </ul>
        </div>
      )}
      <span className="label">{t('dag.cells.runs', { n: runs.length })}</span>
      {runs.length === 0 && <div className="muted">{t('dag.cells.noRuns')}</div>}
      <ul className="dg-runs-list">
        {runs.map(r => {
          const selected = r.id === ce.run;
          const usable = r.state === 'succeeded' && !r.excluded;
          return (
            <li key={r.id} className={`dg-run ${selected ? 'is-selected' : ''} ${r.excluded ? 'is-excluded' : ''}`}>
              <span className="mono ellipsis" title={r.id}>{r.id}</span>
              <span className={`badge ${r.state === 'succeeded' ? 'ok' : r.state === 'failed' || r.state === 'lost' ? 'accent' : ''}`}>{t(`dag.run.${r.state}`)}</span>
              <span className="faint">{L.actor(r.by)} · {p.rel(r.ended ?? r.started)}</span>
              <span className="faint num">{fmtGpuH(r.gpu_hours)} GPU·h</span>
              {r.platform && <span className="faint mono">{r.platform}</span>}
              {r.git?.head && <span className="faint mono" title={r.git.snapshot ?? ''}>{r.git.head.slice(0, 7)}{r.git.dirty ? '*' : ''}</span>}
              {r.excluded && <span className="badge warn" title={r.excluded.reason}>{t('dag.cells.excluded')}</span>}
              <span className="grow" />
              {!p.readOnly && usable && !selected && <Button size="sm" onClick={() => p.onSelectRun(r.id)} title={t('dag.cells.selectHint')}>{t('dag.cells.select')}</Button>}
              {!p.readOnly && selected && p.node.selected?.[p.cell] && <Button size="sm" variant="ghost" onClick={() => p.onSelectRun(null)}>{t('dag.cells.unpin')}</Button>}
              {!p.readOnly && usable && <Button size="sm" variant="ghost" onClick={() => p.onExclude(r)}>{t('dag.cells.exclude')}</Button>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Mismatch({ r, onCoding, onSelect }: { r: Reason; onCoding: () => void; onSelect: (id: string) => void }) {
  const t = useT();
  const addr = r.addr ?? r.edge ?? '';
  const a = parseAddr(addr);
  return (
    <li className="dg-mm">
      <span className={`dg-mm-scheme is-${a.scheme || 'spec'}`}>{a.scheme || r.level}</span>
      <span className="mono ellipsis" title={addr}>{a.scheme ? a.id + (a.facet ? `#${a.facet}` : '') : addr}</span>
      <span className="dgx-fromto mono"><span title={String(r.from ?? '')}>{shortFp(r.from)}</span><Icon name="chevronRight" size={10} /><span title={String(r.to ?? '')}>{shortFp(r.to)}</span></span>
      {r.note && <span className="faint">{r.note}</span>}
      {a.scheme === 'code' && <Button size="sm" variant="ghost" icon="coding" onClick={onCoding}>{t('dag.cells.openDiff')}</Button>}
      {a.scheme === 'node' && <Button size="sm" variant="ghost" onClick={() => onSelect(a.id)}>{t('common.open')}</Button>}
    </li>
  );
}

function ExcludeDialog({ pid, run, onClose }: { pid: string; run: RunSummary; onClose: () => void }) {
  const t = useT();
  const [reason, setReason] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true); setError(null);
    try { await dagApi.exclude(pid, run.id, reason.trim()); onClose(); } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  };
  return (
    <Dialog title={t('dag.cells.excludeTitle', { id: run.id })} onClose={onClose} footer={
      <><Button onClick={onClose}>{t('common.cancel')}</Button><Button variant="primary" onClick={submit} disabled={!reason.trim() || busy}>{t('dag.cells.exclude')}</Button></>
    }>
      <div className="col">
        <p className="muted" style={{ margin: 0 }}>{t('dag.cells.excludeBody')}</p>
        <label className="field"><span className="label">{t('dag.status.reason')}</span>
          <input className="input" value={reason} onChange={e => setReason(e.target.value)} placeholder={t('dag.cells.excludePh')} autoFocus /></label>
        {error && <div className="notice accent"><Icon name="warn" /><span>{error}</span></div>}
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ History

export function HistoryTab(p: TabProps) {
  const t = useT();
  const L = useDagLabels();
  const rel = useRelTime();
  const { node } = p;
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [withEdges, setWithEdges] = useState(false);

  useEffect(() => {
    let alive = true;
    dagApi.history(p.pid, node.id).then(v => { if (alive) { setVersions([...v].sort((a, b) => b.rev - a.rev)); setError(null); } })
      .catch(e => { if (alive) setError(errText(e)); });
    return () => { alive = false; };
  }, [p.pid, node.id, node.head?.vid]);

  const rollback = (v: Version) => p.preview.open({
    key: `rollback:${node.id}`, title: t('dag.history.rollbackTitle', { id: node.id, rev: v.rev }), source: 'rollback', node: node.id,
    ops: [{ op: 'rollback', node: node.id, to_vid: v.vid, edges: withEdges }],
  });

  if (error) return <div className="dg-tab-body"><div className="notice accent"><Icon name="warn" /><span>{error}</span></div></div>;
  if (!versions) return <div className="dg-tab-body row muted"><Spinner /> {t('common.loading')}</div>;
  return (
    <div className="col dg-tab-body">
      {!p.readOnly && versions.length > 1 && (
        <label className="dg-editorial"><input type="checkbox" checked={withEdges} onChange={e => setWithEdges(e.target.checked)} />
          <span>{t('dag.history.withEdges')}</span><span className="faint">{t('dag.history.withEdgesHint')}</span></label>
      )}
      <ol className="dg-versions">
        {versions.map(v => {
          const head = v.vid === node.head?.vid;
          return (
            <li key={v.vid} className={`dg-version ${head ? 'is-head' : ''}`}>
              <div className="row" style={{ gap: 6 }}>
                <span className="dg-rev mono">r{v.rev}</span>
                <span className="mono faint">{v.vid}</span>
                <span className="badge">{v.op}</span>
                {v.reverts && <span className="badge process" title={v.reverts}><Icon name="rollback" size={10} />{t('dag.history.reverts', { vid: v.reverts })}</span>}
                {head && <span className="badge solid">{t('dag.history.head')}</span>}
                <span className="grow" />
                {!p.readOnly && !head && <Button size="sm" icon="rollback" onClick={() => rollback(v)}>{t('dag.history.rollback', { rev: v.rev })}</Button>}
              </div>
              <div className="faint dg-version-meta">
                {L.actor(v.by)} · {rel(v.at)}{v.git ? ` · ${v.git.slice(0, 7)}` : ''}{v.via ? ` · ${v.via}` : ''} · {L.status(v.status)}
              </div>
              {(v.diff ?? []).map((d, i) => <FacetDiff key={i} facet={d.facet} from={d.from} to={d.to} />)}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function FacetDiff({ facet, from, to }: { facet: string; from: unknown; to: unknown }) {
  const parts = useMemo(() => {
    if (typeof from === 'string' && typeof to === 'string') return diffWords(from, to);
    return null;
  }, [from, to]);
  return (
    <div className="dg-fdiff">
      <span className="mono dg-facet-name">{facet}</span>
      {parts ? (
        <div className="dg-fdiff-text">{parts.map((x, i) => <span key={i} className={x.added ? 'diff-add' : x.removed ? 'diff-del' : ''}>{x.value}</span>)}</div>
      ) : (
        <div className="dg-fdiff-json mono"><span className="diff-del">{shortFp(from)}</span> <Icon name="chevronRight" size={10} /> <span className="diff-add">{shortFp(to)}</span></div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ Why

export function WhyTab(p: TabProps) {
  const t = useT();
  const { node, ev } = p;
  const cells = Object.keys(ev?.cells ?? {}).filter(c => ev!.cells![c].level !== 'fresh');
  const [cell, setCell] = useState<string>('');
  const [chains, setChains] = useState<WhyChain[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setChains(null);
    dagApi.explain(p.pid, node.id, cell || undefined).then(c => { if (alive) { setChains(c); setError(null); } })
      .catch(e => { if (alive) setError(errText(e)); });
    return () => { alive = false; };
  }, [p.pid, node.id, cell, p.graph.digest]);

  return (
    <div className="col dg-tab-body">
      {cells.length > 0 && (
        <label className="field"><span className="label">{t('dag.why.cell')}</span>
          <select className="select" value={cell} onChange={e => setCell(e.target.value)}>
            <option value="">{t('dag.why.allCells')}</option>
            {cells.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
      )}
      {error && <div className="notice accent"><Icon name="warn" /><span>{error}</span></div>}
      {!chains && !error && <div className="row muted"><Spinner /> {t('common.loading')}</div>}
      {chains && chains.length === 0 && <div className="muted">{ev?.level && ev.level !== 'fresh' ? t('dag.why.noChain') : t('dag.why.fresh')}</div>}
      {chains?.map((c, i) => (
        <div key={i} className="dg-block">
          <div className="dg-block-head"><FreshBadge level={c.level} />{c.cell && <span className="mono faint">{c.cell}</span>}</div>
          <p className="dg-why-text">{c.text}</p>
          {c.steps.length > 0 && (
            <ol className="dg-why-steps">
              {c.steps.map((s, j) => (
                <li key={j}>
                  <span className="mono ellipsis" title={s.addr}>{s.addr}</span>
                  {(s.from != null || s.to != null) && <span className="dgx-fromto mono"><span>{shortFp(s.from)}</span><Icon name="chevronRight" size={10} /><span>{shortFp(s.to)}</span></span>}
                  {s.note && <span className="faint">{s.note}</span>}
                </li>
              ))}
            </ol>
          )}
        </div>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ Agent

export function AgentTab(p: TabProps) {
  const t = useT();
  const { node, ev } = p;
  const [q, setQ] = useState('');
  const notFresh = !!ev?.level && ev.level !== 'fresh';
  return (
    <div className="col dg-tab-body">
      <p className="muted" style={{ margin: 0 }}>{t('dag.agent.intro')}</p>
      <div className="col" style={{ gap: 6 }}>
        <Button icon="sparkle" onClick={() => p.onAsk(node.id, 'explain')} disabled={!notFresh} title={notFresh ? undefined : t('dag.why.fresh')}>{t('dag.agent.explain')}</Button>
        <Button icon="sparkle" onClick={() => p.onAsk(node.id, 'fix')}>{t('dag.agent.fix')}</Button>
      </div>
      <label className="field"><span className="label">{t('dag.agent.ask')}</span>
        <textarea className="textarea" rows={3} value={q} onChange={e => setQ(e.target.value)} placeholder={t('dag.agent.askPh', { id: node.id })} /></label>
      <div><Button variant="primary" icon="send" disabled={!q.trim()} onClick={() => { p.onAsk(node.id, 'free', q.trim()); setQ(''); }}>{t('dag.agent.send')}</Button></div>
      <p className="faint" style={{ margin: 0, fontSize: 'var(--fs-xs)' }}>{t('dag.agent.note')}</p>
    </div>
  );
}
