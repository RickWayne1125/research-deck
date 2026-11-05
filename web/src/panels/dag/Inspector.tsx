// The node inspector drawer (docs/DAG.md §8): header with status / freshness / flags and the status actions, then
// tabs Overview (facets, editable where allowed: every edit is a what-if first, Apply after), Edges, Cells, History,
// Why and Agent. A facet edit previews 300 ms after the last keystroke and paints the map in preview mode.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Icon } from '../../components/icons';
import { Markdown } from '../../components/Markdown';
import { Button, ErrorNote, IconButton } from '../../components/ui';
import { useRelTime, useT } from '../../i18n';
import { dagApi } from '../../dag/api';
import { FreshBadge, KIND_ICON, StatusBadge, useDagLabels } from '../../dag/encoding';
import type { DagNode, Facet, GraphResponse, NodeDetail, NodeEval, Op } from '../../dag-types';
import { ImpactBody, type ApplyArgs } from './ImpactPanel';
import { CellsTab, EdgesTab, HistoryTab, WhyTab, AgentTab } from './InspectorTabs';
import { isAction, isDead, lastAgent, shortFp } from './model';
import { errText, type PreviewApi, type PreviewReq } from './preview';

export const TABS = ['overview', 'edges', 'cells', 'history', 'why', 'agent'] as const;
export type InspectorTab = (typeof TABS)[number];
export const isTab = (v: string | undefined | null): v is InspectorTab => !!v && (TABS as readonly string[]).includes(v);

export interface InspectorProps {
  pid: string;
  id: string;
  graph: GraphResponse;
  tab: InspectorTab;
  onTab: (t: InspectorTab) => void;
  onClose: () => void;
  onSelect: (id: string, tab?: InspectorTab) => void;
  readOnly: boolean;
  preview: PreviewApi;
  previewBusy: boolean;
  onApplyPreview: (a: ApplyArgs) => void;
  onFork?: () => void;
  onHover: (ids: string[]) => void;
  onStatus: (id: string, action: StatusAction) => void;
  onRun: (ops: Op[], title: string) => Promise<void>;
  onAsk: (id: string, kind: 'explain' | 'fix' | 'free', text?: string) => void;
  onOpenCoding: () => void;
  applied: { key: string; n: number } | null;   // the last preview that was applied (closes its facet editor)
}

export type StatusAction = 'activate' | 'confirm' | 'reopen' | 'lock' | 'unlock' | 'refute' | 'abandon' | 'supersede' | 'revive';

/** The status actions a human may take from each status (docs/DAG.md §2.4). */
export function statusActions(n: DagNode): StatusAction[] {
  switch (n.status) {
    case 'proposed': return ['activate', 'confirm', 'refute', 'abandon'];
    case 'active': return ['confirm', 'refute', 'abandon', 'supersede'];
    case 'confirmed': return ['lock', 'reopen', 'abandon', 'supersede'];
    case 'locked': return ['unlock'];
    default: return ['revive'];
  }
}

export function Inspector(p: InspectorProps) {
  const t = useT();
  const L = useDagLabels();
  const rel = useRelTime();
  const node = p.graph.nodes.find(n => n.id === p.id) ?? null;
  const ev = p.graph.eval[p.id];
  const [detail, setDetail] = useState<NodeDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Details follow the graph digest, so a live 'dag' event refreshes the open node too.
  useEffect(() => {
    let alive = true;
    dagApi.node(p.pid, p.id).then(d => { if (alive) { setDetail(d); setError(null); } })
      .catch(e => { if (alive) { setDetail(null); setError(errText(e)); } });
    return () => { alive = false; };
  }, [p.pid, p.id, p.graph.digest]);

  if (!node) {
    return (
      <section className="dg-side-inner">
        <header className="dg-side-head"><span className="grow mono">{p.id}</span><IconButton icon="close" label={t('common.close')} onClick={p.onClose} /></header>
        <div className="dg-side-scroll"><div className="notice warn"><Icon name="warn" /><span>{t('dag.inspector.missing', { id: p.id })}</span></div></div>
      </section>
    );
  }

  const action = isAction(node);
  const tabs = TABS.filter(x => x !== 'cells' || action);
  const tab = tabs.includes(p.tab) ? p.tab : 'overview';
  const agent = lastAgent(node);

  return (
    <section className="dg-side-inner dg-inspector" aria-label={t('dag.inspector.aria', { id: node.id })}>
      <header className="dg-side-head dg-insp-head">
        <div className="col grow" style={{ gap: 4, minWidth: 0 }}>
          <div className="row" style={{ gap: 6 }}>
            <Icon name={KIND_ICON[node.kind]} size={13} />
            <span className="label">{L.kind(node.kind)} · {node.stage}{node.purpose ? ` · ${node.purpose}` : ''}</span>
            <CopyId id={node.id} />
          </div>
          <h2 className={`h2 dg-insp-title ${isDead(node.status) && node.status === 'refuted' ? 'is-strike' : ''}`}>{L.title(node)}</h2>
          <div className="row wrap" style={{ gap: 6 }}>
            <StatusBadge status={node.status} />
            <FreshBadge level={ev?.level} />
            <span className="badge mono" title={node.head?.vid}>r{node.head?.rev ?? 0}</span>
            {(ev?.flags ?? []).filter(f => f !== 'shaky').map(f => <span key={f} className={`badge ${f === 'lock_alert' || f === 'conflict' ? 'accent' : f === 'impl_lag' ? 'warn' : ''}`} title={t(`dag.flag.${f}`)}>{t(`dag.flagShort.${f}`)}</span>)}
            {agent && <span className={`dg-avatar is-${agent}`} title={L.actor(`agent:${agent}`)}><Icon name="robot" size={12} /></span>}
          </div>
        </div>
        <IconButton icon="close" label={t('common.close')} onClick={p.onClose} />
      </header>
      {!p.readOnly && <StatusBar node={node} onStatus={a => p.onStatus(node.id, a)} />}
      <div className="tabs dg-insp-tabs" role="tablist">
        {tabs.map(x => (
          <button key={x} type="button" role="tab" className="tab" aria-selected={tab === x} onClick={() => p.onTab(x)}>
            {t(`dag.tab.${x}`)}
            {x === 'edges' && (ev?.reasons ?? []).some(r => r.edge) && <span className="dot warn" />}
            {x === 'cells' && Object.values(ev?.cells ?? {}).some(c => c.level !== 'fresh') && <span className="dot warn" />}
          </button>
        ))}
      </div>
      <div className="dg-side-scroll">
        {error && <ErrorNote error={error} />}
        {tab === 'overview' && <OverviewTab {...p} node={node} ev={ev} detail={detail} rel={rel} />}
        {tab === 'edges' && <EdgesTab {...p} node={node} ev={ev} detail={detail} />}
        {tab === 'cells' && <CellsTab {...p} node={node} ev={ev} detail={detail} />}
        {tab === 'history' && <HistoryTab {...p} node={node} />}
        {tab === 'why' && <WhyTab {...p} node={node} ev={ev} />}
        {tab === 'agent' && <AgentTab {...p} node={node} ev={ev} />}
      </div>
    </section>
  );
}

function CopyId({ id }: { id: string }) {
  const t = useT();
  const [done, setDone] = useState(false);
  return (
    <button type="button" className="dg-copy mono" title={t('common.copy')} onClick={() => {
      navigator.clipboard?.writeText(id).then(() => { setDone(true); window.setTimeout(() => setDone(false), 1200); }).catch(() => {});
    }}>
      {id}<Icon name={done ? 'check' : 'link'} size={11} />
    </button>
  );
}

function StatusBar({ node, onStatus }: { node: DagNode; onStatus: (a: StatusAction) => void }) {
  const t = useT();
  const actions = statusActions(node);
  const icon: Partial<Record<StatusAction, string>> = { confirm: 'check', lock: 'lock', unlock: 'unlock', refute: 'close', revive: 'refresh', supersede: 'chevronRight', activate: 'play' };
  return (
    <div className="dg-statusbar row wrap">
      {actions.map((a, i) => (
        <Button key={a} size="sm" icon={icon[a]} variant={i === 0 && (a === 'confirm' || a === 'lock' || a === 'unlock') ? 'primary' : undefined}
          onClick={() => onStatus(a)} title={t(`dag.status.${a}Hint`)}>{t(`dag.status.${a}`)}</Button>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ overview

type OverviewProps = InspectorProps & { node: DagNode; ev?: NodeEval; detail: NodeDetail | null; rel: (iso: string | null | undefined) => string };

function OverviewTab(p: OverviewProps) {
  const t = useT();
  const L = useDagLabels();
  const { node, ev } = p;
  const reasons = ev?.reasons ?? [];
  const facetNames = Object.keys(node.facets ?? {});
  return (
    <div className="col dg-tab-body">
      {reasons.length > 0 && (
        <div className="dg-block">
          <div className="dg-block-head"><span className="label grow">{t('dag.overview.reasons')}</span><Button size="sm" variant="ghost" onClick={() => p.onTab('why')}>{t('dag.tab.why')}</Button></div>
          <ul className="dg-reasons">
            {reasons.slice(0, 6).map((r, i) => (
              <li key={i}><FreshBadge level={r.level} /> <span className="mono ellipsis" title={r.edge ?? r.addr}>{r.edge ?? r.addr ?? ''}</span>
                {(r.from != null || r.to != null) && <span className="dgx-fromto mono"><span>{shortFp(r.from)}</span><Icon name="chevronRight" size={10} /><span>{shortFp(r.to)}</span></span>}
                {r.note && <span className="faint dg-reason-note">{r.note}</span>}</li>
            ))}
          </ul>
        </div>
      )}
      {(ev?.shaky ?? []).length > 0 && (
        <div className="notice warn"><span className="dg-shaky" style={{ marginTop: 4 }} />
          <span>{t('dag.overview.shaky')} {ev!.shaky.map(id => <button key={id} type="button" className="dg-inline-link mono" onClick={() => p.onSelect(id)}>{id}</button>)}</span>
        </div>
      )}
      {node.lock && (
        <div className="dg-lockinfo"><Icon name="lock" size={13} />
          <span>{t('dag.overview.locked', { by: L.actor(node.lock.by), at: p.rel(node.lock.at) })}{node.lock.reason ? ` — ${node.lock.reason}` : ''}</span>
        </div>
      )}
      {node.status === 'superseded' && node.superseded_by && (
        <div className="notice"><Icon name="chevronRight" /><span>{t('dag.overview.supersededBy')} <button type="button" className="dg-inline-link mono" onClick={() => p.onSelect(node.superseded_by!)}>{node.superseded_by}</button></span></div>
      )}
      {node.alt_group && (
        <div className="faint">{t('dag.overview.altGroup')} <button type="button" className="dg-inline-link mono" onClick={() => p.onSelect(node.alt_group!)}>{node.alt_group}</button></div>
      )}
      {node.notes && <div className="dg-notes"><Markdown text={node.notes} /></div>}

      <div className="col" style={{ gap: 10 }}>
        <span className="label">{t('dag.overview.facets')}</span>
        {facetNames.length === 0 && <div className="muted">{t('dag.overview.noFacets')}</div>}
        {facetNames.map(name => <FacetRow key={name} {...p} name={name} facet={node.facets[name]} />)}
      </div>

      <dl className="kv dg-meta">
        {node.created && <><dt>{t('dag.overview.created')}</dt><dd>{L.actor(node.created.by)} · {p.rel(node.created.at)}</dd></>}
        {node.updated && <><dt>{t('dag.overview.updated')}</dt><dd>{L.actor(node.updated.by)} · {p.rel(node.updated.at)}{node.updated.via ? ` · ${node.updated.via}` : ''}</dd></>}
        <dt>{t('dag.overview.vid')}</dt><dd className="mono">{node.head?.vid} · {shortFp(node.head?.fp)}</dd>
      </dl>
    </div>
  );
}

// ---- facet editing: what-if first, apply after

const EDITABLE: Facet['type'][] = ['prose', 'text', 'json', 'bound'];

function display(v: unknown): string {
  if (v === undefined) return '';
  if (typeof v === 'string') return v;
  return JSON.stringify(v, null, 2);
}

/** Leaves of a bound value relative to its key: {min: 256, max: 2048} → [['min', 256], ['max', 2048]]. */
function leaves(v: unknown, prefix = ''): [string, unknown][] {
  if (v && typeof v === 'object' && !Array.isArray(v)) {
    return Object.entries(v as Record<string, unknown>).flatMap(([k, x]) => leaves(x, prefix ? `${prefix}.${k}` : k));
  }
  return [[prefix, v]];
}

function parseLoose(s: string): unknown {
  const v = s.trim();
  if (v === '') return '';
  try { return JSON.parse(v); } catch { return s; }
}

function FacetRow(p: OverviewProps & { name: string; facet: Facet }) {
  const t = useT();
  const { node, name, facet, preview } = p;
  const key = `edit:${node.id}#${name}`;
  const editable = !p.readOnly && EDITABLE.includes(facet.type) && !isDead(node.status);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [leafDraft, setLeafDraft] = useState<Record<string, string>>({});
  const [editorial, setEditorial] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const mine = preview.state?.key === key ? preview.state : null;

  const bind = facet.bind ?? '';
  const [bindFile, bindKey] = bind.includes('#') ? [bind.slice(0, bind.indexOf('#')), bind.slice(bind.indexOf('#') + 1)] : [bind, ''];
  const boundLeaves = useMemo(() => (facet.type === 'bound' ? leaves(facet.value) : []), [facet]);

  const start = () => {
    setEditing(true); setParseError(null); setEditorial(false);
    setDraft(display(facet.value));
    setLeafDraft(Object.fromEntries(boundLeaves.map(([k, v]) => [k, display(v)])));
  };
  const stop = useCallback(() => { setEditing(false); if (preview.state?.key === key) preview.discard(); }, [preview, key]);

  // Leave edit mode once this edit has been applied (the panel reports it).
  useEffect(() => { if (p.applied?.key === key) setEditing(false); }, [p.applied, key]);

  const request = (ops: Op[], fork: PreviewReq['fork']): PreviewReq => ({
    key, title: t('dag.edit.title', { id: node.id, facet: name }), ops, source: 'edit', node: node.id, inline: true, fork,
  });

  const changeText = (v: string) => {
    setDraft(v);
    if (v === display(facet.value)) { preview.discard(); setParseError(null); return; }
    let value: unknown = v;
    if (facet.type === 'json') {
      try { value = JSON.parse(v); setParseError(null); } catch (e) { setParseError(String((e as Error).message)); return; }
    }
    preview.update(request([{ op: 'edit', node: node.id, base_vid: node.head?.vid, set: { [name]: value }, editorial }], null));
  };
  const changeLeaf = (leaf: string, v: string) => {
    const next = { ...leafDraft, [leaf]: v };
    setLeafDraft(next);
    const ops: Op[] = [];
    const set: Record<string, unknown> = {};
    const orig = new Map(boundLeaves);
    for (const [k, s] of Object.entries(next)) {
      if (s === display(orig.get(k))) continue;
      const full = [bindKey, k].filter(Boolean).join('.');
      const value = parseLoose(s);
      ops.push({ op: 'config_edit', file: bindFile, key: full, value });
      set[full] = value;
    }
    if (!ops.length) { preview.discard(); return; }
    preview.update(request(ops, node.kind === 'design' ? { node: node.id, set } : null));
  };
  const toggleEditorial = (v: boolean) => {
    setEditorial(v);
    if (mine) preview.update({ ...mine, ops: mine.ops.map(o => (o.op === 'edit' ? { ...o, editorial: v } : o)) });
  };

  return (
    <div className={`dg-facet ${editing ? 'is-editing' : ''}`}>
      <div className="dg-facet-head">
        <span className="mono dg-facet-name">{name}</span>
        <span className="badge">{facet.type}</span>
        {facet.type === 'bound' && <span className="faint mono ellipsis" title={bind}>{bind}</span>}
        <span className="grow" />
        {editable && !editing && <Button size="sm" variant="ghost" icon="writing" onClick={start}>{t('common.edit')}</Button>}
        {editing && <Button size="sm" variant="ghost" onClick={stop}>{t('common.cancel')}</Button>}
      </div>
      {!editing && <FacetValue facet={facet} />}
      {editing && facet.type !== 'bound' && (
        <textarea className={`textarea ${facet.type === 'json' ? 'mono' : ''}`} rows={Math.min(12, Math.max(3, draft.split('\n').length + 1))}
          value={draft} onChange={e => changeText(e.target.value)} autoFocus aria-label={name} />
      )}
      {editing && facet.type === 'bound' && (
        <div className="dg-leaves">
          {boundLeaves.map(([k]) => (
            <label key={k || '_'} className="dg-leaf">
              <span className="mono faint">{[bindKey, k].filter(Boolean).join('.')}</span>
              <input className="input mono" value={leafDraft[k] ?? ''} onChange={e => changeLeaf(k, e.target.value)} />
            </label>
          ))}
          <div className="faint dg-hint">{t('dag.edit.boundHint', { file: bindFile })}</div>
        </div>
      )}
      {editing && parseError && <div className="notice accent"><Icon name="warn" /><span>{t('dag.edit.badJson', { msg: parseError })}</span></div>}
      {editing && (facet.type === 'prose' || facet.type === 'text') && (
        <label className="dg-editorial"><input type="checkbox" checked={editorial} onChange={e => toggleEditorial(e.target.checked)} />
          <span>{t('dag.edit.editorial')}</span><span className="faint">{t('dag.edit.editorialHint')}</span></label>
      )}
      {editing && node.status === 'locked' && <div className="notice warn"><Icon name="lock" /><span>{t('dag.edit.lockedHint')}</span></div>}
      {editing && node.status === 'confirmed' && !editorial && <div className="faint dg-hint">{t('dag.edit.demoteHint')}</div>}
      {editing && mine && (
        <div className="dg-inline-impact">
          <ImpactBody state={mine} busy={p.previewBusy} compact onApply={p.onApplyPreview} onDiscard={stop}
            onFork={mine.fork && p.onFork ? p.onFork : undefined} onHoverNodes={p.onHover} />
        </div>
      )}
      {editing && !mine && !parseError && <div className="faint dg-hint">{t('dag.edit.typeToPreview')}</div>}
    </div>
  );
}

export function FacetValue({ facet }: { facet: Facet }) {
  const t = useT();
  const v = facet.value;
  if (facet.type === 'prose' || facet.type === 'text') {
    return typeof v === 'string' && v ? <div className={`dg-facet-value ${facet.type === 'text' ? 'mono' : ''}`}>{v}</div> : <div className="faint">{t('common.none')}</div>;
  }
  if (facet.type === 'bound') {
    return <pre className="dg-facet-json mono">{v === undefined ? t('dag.facet.unresolved') : display(v)}</pre>;
  }
  if (v === undefined || v === null) return <div className="faint">{t('common.none')}</div>;
  if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') return <div className="dg-facet-value mono">{String(v)}</div>;
  return <pre className="dg-facet-json mono">{JSON.stringify(v, null, 2)}</pre>;
}

