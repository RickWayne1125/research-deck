// Typed client for the agents routes beyond the core ones (docs/API.md § Agents): discovery, transcript, handoff,
// the brief and the MCP registration snippets. The dock and Settings use these, never raw paths.
import { get, p, post, put } from '../api/client';
import type { DiscoveredSession, PanelBinding, PanelId, Permission, ProviderId, SessionsDoc, TranscriptEntry } from '../types';

/** A transcript line as the backend returns it (the core type plus what the agents slice adds). */
export interface DockEntry extends TranscriptEntry {
  imported?: boolean;                       // from the bound session's own log, not the dashboard
  model?: string | null; effort?: string | null; fast?: boolean | null;   // assistant lines: who answered
  kind?: 'note';                            // role 'handoff' + kind 'note': an agent's note for the other backend
  from?: ProviderId; to?: ProviderId; file?: string; smart?: boolean; messages?: number; by?: string;
}

export interface HandoffResult {
  file: string | null; summary: string; pending: boolean; panel: PanelId; from: ProviderId; to: ProviderId;
  smart: boolean; written_by?: string | null; error?: string | null; unchanged?: boolean;
}

export interface BriefResult { markdown: string; generated_at: string; path: string }

export interface HandoffsInfo {
  recent: { file: string; ts: string | null; panel: PanelId | null; from: ProviderId | null; to: ProviderId | null; kind: 'handoff' | 'note' }[];
  pending: { panel: PanelId; provider: ProviderId; bytes: number; file: string }[];
}

export interface McpConfig {
  claude: { mcpServers: Record<string, { command: string; args: string[]; env: Record<string, string> }> };
  codex: string;                            // config.toml snippet
  commands: { claude: string; codex: string };
  remove: { claude: string; codex: string };
  env: Record<string, string>;
  paths: { app_root: string; local_dir: string; project_root: string; research_dir: string; docs: string };
}

export interface BindingChange {
  provider?: ProviderId; model?: string; effort?: string; fast?: boolean; permission?: Permission;
  session_id?: string | null; new_session?: boolean; title?: string;
}

export interface RunSummary {
  run_id: string; status: 'running' | 'done' | 'error' | 'cancelled'; provider: string; model: string; effort: string;
  fast: boolean; panel: PanelId; purpose: string; session_id: string | null; started: number; finished: number | null; error: string | null;
}

export const agentApi = {
  sessions: (pid: string) => get<SessionsDoc>(p(pid, '/sessions')),
  bind: (pid: string, panel: PanelId, change: BindingChange) => put<PanelBinding>(p(pid, `/sessions/${panel}`), change),
  discover: (pid: string, provider?: ProviderId) => get<DiscoveredSession[]>(p(pid, '/sessions/discover'), { provider }),
  transcript: (pid: string, panel: PanelId, opts?: { limit?: number; imported?: boolean }) =>
    get<DockEntry[]>(p(pid, `/transcript/${panel}`), { limit: opts?.limit, import: opts?.imported ? 1 : undefined }),
  handoff: (pid: string, panel: PanelId, to: ProviderId, smart: boolean) => post<HandoffResult>(p(pid, '/handoff'), { panel, to, smart }),
  handoffs: (pid: string) => get<HandoffsInfo>(p(pid, '/handoffs')),
  brief: (pid: string) => get<BriefResult>(p(pid, '/brief')),
  mcpConfig: (pid: string) => get<McpConfig>('/api/mcp/config', { project: pid }),
  runs: (pid: string) => get<RunSummary[]>('/api/agent/runs', { project: pid }),
  cancel: (runId: string) => post<{ ok: boolean }>(`/api/agent/runs/${encodeURIComponent(runId)}/cancel`),
};
