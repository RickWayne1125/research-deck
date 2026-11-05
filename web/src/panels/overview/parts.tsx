// Small pieces Today shares: the node index, actor avatars, and plural / fallback strings.
import { Icon } from '../../components/icons';
import { useCallback } from 'react';
import { useI18n, useT } from '../../i18n';
import { actorKind, useDagLabels } from '../../dag/encoding';
import type { DagNode, NodeEval } from '../../dag-types';

/** What every section needs to resolve an id: the node (from the graph, dead ones included) and its evaluation. */
export interface NodeIndex { node: (id: string) => DagNode | undefined; ev: (id: string) => NodeEval | undefined }

/** Human / Claude / Codex / system, colored by actor (overview.css .ov-actor-*). */
export function ActorAvatar({ by, size = 20 }: { by: string | null | undefined; size?: number }) {
  const L = useDagLabels();
  const k = actorKind(by);
  return (
    <span className={`ov-avatar ov-actor-${k}`} title={`${L.actor(by)}${by ? ` · ${by}` : ''}`} style={{ width: size, height: size }}>
      <Icon name={k === 'human' ? 'user' : k === 'system' ? 'settings' : 'robot'} size={Math.round(size * 0.62)} />
    </span>
  );
}

/** t() with a fallback when the key has no entry (translate returns the key itself). */
export function tOr(t: (k: string, v?: Record<string, string | number>) => string, key: string, fallback: string, vars?: Record<string, string | number>): string {
  const s = t(key, vars);
  return s === key ? fallback : s;
}

/** t() for counts: in English, n === 1 uses "<key>.one" when it exists. {n} is always available to the string. */
export function usePlural(): (key: string, n: number, vars?: Record<string, string | number>) => string {
  const { t, lang } = useI18n();
  return useCallback((key, n, vars) => {
    const v = { n, ...vars };
    return lang === 'en' && n === 1 ? tOr(t, `${key}.one`, t(key, v), v) : t(key, v);
  }, [t, lang]);
}

export const errorMessage = (e: unknown): string => String((e as { message?: string })?.message ?? e);
