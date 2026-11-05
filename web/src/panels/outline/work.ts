// Doing a task where its work happens: an experiment in Experiments (its runs, or a new run of its node), a figure in
// Paper › Figures, code in Code, literature in the survey's notes. A task can make what it needs: an experiment node at
// the stage of the task's phase (idea S1, insight S2, design S5, evaluation S6), or a survey of its topic. The task
// being worked on shows in a bar above those pages (state/today.tsx activeTask).
import { useCallback } from 'react';
import { FIGURES, useApp } from '../../state/app';
import { useToday } from '../../state/today';
import { useI18n } from '../../i18n';
import { dagApi } from '../../dag/api';
import { startApi } from '../../start/api';
import { vz } from '../visualization/api';
import { outlineApi, type Phase, type Task } from './api';
import { allItems, slugId } from './model';

/** The experiment stage and purpose a task's phase gives a new experiment node. */
export const PHASE_EXPERIMENT: Record<Phase, { stage: string; purpose: string }> = {
  idea: { stage: 'S1', purpose: 'reproduce' }, insight: { stage: 'S2', purpose: 'profile' },
  design: { stage: 'S5', purpose: 'microbench' }, evaluation: { stage: 'S6', purpose: 'eval' },
};

export function useWork() {
  const { projectId, navigate } = useApp();
  const { lang } = useI18n();
  const today = useToday();
  const pid = projectId!;

  /** Open where the task's work happens, and show the task above that page. */
  const go = useCallback(async (task: Task) => {
    const l = task.links ?? {};
    today.setActiveTask(task.id);
    if (task.type === 'exp') {
      const runs = (today.runs ?? []).filter(r => l.node && r.node_id === l.node);
      navigate('experiments', runs.length ? runs[0].id : l.node ? `new:${l.node}` : 'new');
    } else if (task.type === 'fig') {
      let fid = l.figure ?? null;
      if (!fid && l.node) {
        try { fid = (await vz.list(pid)).find(f => f.node_id === l.node)?.id ?? null; } catch { /* the gallery then */ }
      }
      navigate('writing', fid ? `${FIGURES}/${fid}` : FIGURES);
    } else if (task.type === 'code') {
      navigate('coding', l.path ?? null);
    } else {
      const sv = today.survey && (!l.survey || l.survey === today.survey.id) ? today.survey : null;
      navigate('writing', l.path ?? sv?.files.survey ?? 'notes/survey.md');
    }
  }, [navigate, pid, today]);

  /** A new experiment node for an experiment task (at its phase's stage), linked to it. */
  const makeExperiment = useCallback(async (task: Task) => {
    const phase = task.phase ?? today.outline?.project_phase ?? 'evaluation';
    const { stage, purpose } = PHASE_EXPERIMENT[phase];
    const taken = new Set((today.graph?.nodes ?? []).map(n => n.id));
    const id = slugId('exp', task.title, taken);
    await dagApi.ops(pid, [{ op: 'create', node: { id, kind: 'experiment', stage, purpose, status: 'active', title: { [lang]: task.title }, facets: {}, edges: [] } }],
      { rationale: `Experiment for the outline task “${task.title}”` });
    await outlineApi.updateTask(pid, task.id, { links: { ...task.links, node: id } });
    await Promise.all([today.reloadOutline(), Promise.resolve(today.reload())]);
    return id;
  }, [pid, lang, today]);

  /** A survey of a literature task's topic (the task and the items it serves), linked to it. */
  const startSurvey = useCallback(async (task: Task) => {
    const items = [...allItems(today.outline)].filter(i => task.items.includes(i.id));
    const idea = [task.title, '', ...items.map(i => `- ${i.num} ${i.text}`)].join('\n');
    const sv = await startApi.startSurvey(pid, { idea });
    await outlineApi.updateTask(pid, task.id, { status: 'doing', links: { ...task.links, survey: sv.id } });
    await today.reloadOutline();
    return sv;
  }, [pid, today]);

  return { go, makeExperiment, startSurvey };
}
