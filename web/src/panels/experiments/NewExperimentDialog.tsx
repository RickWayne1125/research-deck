// "New experiment": a planned record (title, DAG node, command, config JSON, target). Nothing is submitted. The target's
// resource pool prices it: estimated hours × GPUs × the price of a GPU-hour there (shown, not stored).
import { useEffect, useMemo, useState } from 'react';
import { Button, Dialog } from '../../components/ui';
import { dagApi } from '../../dag/api';
import { useDagLabels } from '../../dag/encoding';
import { useI18n, useT } from '../../i18n';
import { amount, num, platformRate, rateText } from '../../pools/format';
import '../../pools/i18n';
import type { DagNode } from '../../types';
import { exApi, type ExRecord, type ExResources } from './api';

export function NewExperimentDialog({ pid, initialNode, initialTitle, onClose, onCreated }: {
  pid: string; initialNode?: string | null; initialTitle?: string; onClose: () => void; onCreated: (rec: ExRecord) => void;
}) {
  const t = useT();
  const { lang } = useI18n();
  const L = useDagLabels();
  const [title, setTitle] = useState(initialTitle ?? '');
  const [node, setNode] = useState(initialNode ?? '');
  const [command, setCommand] = useState('');
  const [config, setConfig] = useState('{\n  \n}');
  const [platform, setPlatform] = useState('');
  const [host, setHost] = useState('');
  const [gpus, setGpus] = useState(1);
  const [gpuType, setGpuType] = useState('');
  const [hours, setHours] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Suggestions only: the DAG's experiment nodes and the platforms/nodes/GPUs the resources view knows.
  const [expNodes, setExpNodes] = useState<DagNode[]>([]);
  const [resources, setResources] = useState<ExResources | null>(null);
  useEffect(() => {
    let alive = true;
    dagApi.graph(pid).then(g => { if (alive) setExpNodes(g.nodes.filter(n => n.kind === 'experiment')); }).catch(() => {});
    exApi.resources(pid).then(r => { if (alive) setResources(r); }).catch(() => {});
    return () => { alive = false; };
  }, [pid]);
  const plat = resources?.platforms.find(p => p.id === platform.trim().toLowerCase() || p.id === platform || p.label === platform);
  const hosts = useMemo(() => (plat ? plat.nodes : resources?.platforms.flatMap(p => p.nodes) ?? []), [plat, resources]);
  const gpuNames = useMemo(() => [...new Set(hosts.flatMap(n => n.gpus.map(g => g.name)))], [hosts]);
  // The chosen DAG node's spec fills in what is still empty: its platform and estimated hours.
  const spec = (expNodes.find(n => n.id === node.trim())?.facets?.spec?.value ?? null) as { est_hours?: unknown; platform?: unknown } | null;
  useEffect(() => {
    if (!spec) return;
    if (typeof spec.est_hours === 'number' && spec.est_hours > 0) setHours(h => h || String(spec.est_hours));
    if (typeof spec.platform === 'string' && spec.platform) setPlatform(p => p || String(spec.platform));
  }, [spec]);
  const estimate = useMemo(() => {
    if (!platform.trim() || !resources || resources.source !== 'pools') return null;
    if (!plat) return t('pl.n.noPool');
    const rate = platformRate(plat, host, gpuType);
    if (!rate) return null;
    const note = plat.pool && !plat.pool.here ? ` · ${t('pl.n.notHere')}` : '';
    if (rate.state === 'free') return t('pl.free') + note;
    if (rate.state === 'varies') return t('pl.n.pickMachine') + note;
    if (rate.state === 'unknown' || rate.amount == null || !rate.unit) return t('pl.unknownPrice') + note;
    const h = Number(hours);
    const g = Math.max(0, Math.floor(gpus) || 0);
    if (!(h > 0)) return rateText({ ...rate, item: 'gpu_hour', rule_amount: rate.amount, from: null, why: null }, t, lang) + note;
    return t('pl.n.est', { h: num(h, lang), g, cost: `≈ ${amount(h * g * rate.amount, rate.unit, lang)}` }) + note;
  }, [platform, resources, plat, host, gpuType, hours, gpus, t, lang]);

  const parsed = useMemo(() => {
    if (!config.trim()) return { ok: true as const, value: {} };
    try {
      const v = JSON.parse(config);
      return v && typeof v === 'object' && !Array.isArray(v) ? { ok: true as const, value: v as Record<string, unknown> } : { ok: false as const };
    } catch { return { ok: false as const }; }
  }, [config]);

  const submit = async () => {
    if (!title.trim() || !parsed.ok) return;
    setBusy(true);
    setError(null);
    try {
      const rec = await exApi.create(pid, {
        title: title.trim(), node_id: node.trim() || null, command: command.trim() || null, config: parsed.value,
        target: { platform: platform.trim(), node: host.trim(), gpus: Math.max(0, Math.floor(gpus) || 0), gpu_type: gpuType.trim() || null },
      });
      onCreated(rec);
    } catch (e) {
      setError(String((e as Error).message ?? e));
      setBusy(false);
    }
  };

  return (
    <Dialog title={t('ex.n.title')} onClose={onClose} width={620} footer={<>
      <span className="faint ex-small grow">{t('ex.n.hint')}</span>
      <Button onClick={onClose}>{t('common.cancel')}</Button>
      <Button variant="primary" onClick={submit} disabled={busy || !title.trim() || !parsed.ok}>{t('ex.n.create')}</Button>
    </>}>
      <div className="col ex-form">
        <label className="field"><span className="label">{t('ex.n.fTitle')}</span>
          <input className="input" value={title} onChange={e => setTitle(e.target.value)} placeholder={t('ex.n.fTitlePh')} autoFocus /></label>
        <label className="field"><span className="label">{t('ex.n.fNode')}</span>
          <input className="input mono" list="ex-new-nodes" value={node} onChange={e => setNode(e.target.value)} placeholder={t('ex.n.fNodePh')} />
          <datalist id="ex-new-nodes">{expNodes.map(n => <option key={n.id} value={n.id}>{L.title(n)}</option>)}</datalist></label>
        <label className="field"><span className="label">{t('ex.n.fCommand')}</span>
          <input className="input mono" value={command} onChange={e => setCommand(e.target.value)} placeholder={t('ex.n.fCommandPh')} /></label>
        <label className="field"><span className="label">{t('ex.n.fConfig')}</span>
          <textarea className={`textarea mono ex-json ${parsed.ok ? '' : 'invalid'}`} rows={6} value={config} spellCheck={false}
            onChange={e => setConfig(e.target.value)} aria-invalid={!parsed.ok} />
          {!parsed.ok && <span className="ex-small ex-bad">{t('ex.n.fConfigBad')}</span>}</label>
        <fieldset className="ex-fieldset">
          <legend className="label">{t('ex.n.target')}</legend>
          <div className="ex-grid4">
            <label className="field"><span className="faint ex-small">{t('ex.n.fPlatform')}</span>
              <input className="input" list="ex-new-platforms" value={platform} onChange={e => setPlatform(e.target.value)} />
              <datalist id="ex-new-platforms">{resources?.platforms.filter(p => p.status !== 'disabled' && p.pool?.here !== false).map(p => <option key={p.id} value={p.id}>{p.label}</option>)}</datalist></label>
            <label className="field"><span className="faint ex-small">{t('ex.n.fNodeName')}</span>
              <input className="input" list="ex-new-hosts" value={host} onChange={e => setHost(e.target.value)} />
              <datalist id="ex-new-hosts">{hosts.map(n => <option key={n.id} value={n.label} />)}</datalist></label>
            <label className="field"><span className="faint ex-small">{t('ex.n.fGpus')}</span>
              <input className="input num" type="number" min={0} max={64} value={gpus} onChange={e => setGpus(Number(e.target.value))} /></label>
            <label className="field"><span className="faint ex-small">{t('ex.n.fGpuType')}</span>
              <input className="input" list="ex-new-gpus" value={gpuType} onChange={e => setGpuType(e.target.value)} />
              <datalist id="ex-new-gpus">{gpuNames.map(g => <option key={g} value={g} />)}</datalist></label>
          </div>
          <div className="row wrap ex-estimate">
            <label className="field"><span className="faint ex-small">{t('pl.n.hours')}</span>
              <input className="input num" type="number" min={0} step="any" value={hours} onChange={e => setHours(e.target.value)} style={{ width: 120 }} /></label>
            {estimate && <div className="col" style={{ gap: 2 }}><span className="faint ex-small">{t('pl.n.estimate')}</span><span className="ex-small">{estimate}</span></div>}
          </div>
        </fieldset>
        {error && <div className="notice accent">{error}</div>}
      </div>
    </Dialog>
  );
}
