// JSON shapes shared with the backend (docs/API.md). The backend is the source of truth; keep both in step.

// ------------------------------------------------------------------ projects, files, events
/** Where an agent request comes from. Every origin talks to the project's one conversation (agents/sessions.py). */
export type PanelId = 'project' | 'writing' | 'coding' | 'experiments' | 'visualization';
/** The views: Outline (a research project's home), Today (overview; an engineering project's home), Map (dag),
 *  Experiments, Paper (writing, with the figures), Code (coding), Settings. */
export type ViewId = 'outline' | 'overview' | 'dag' | 'experiments' | 'writing' | 'coding' | 'settings';
export type StageId = 'idea' | 'motivation' | 'insight' | 'design' | 'evaluation' | 'writing';
export const STAGES: StageId[] = ['idea', 'motivation', 'insight', 'design', 'evaluation', 'writing'];

/** research: the full pipeline (the research map, stages and their gates). engineering: code, docs, runs and figures of
 *  a non-research effort (e.g. a PR); the map is hidden. `views` overrides the kind's default. */
export type ProjectKind = 'research' | 'engineering';
export interface ProjectSummary {
  id: string; root: string; demo: boolean; exists: boolean; name: string; summary: string;
  venue: string; deadline: string | null; stage: StageId; is_git: boolean;
  kind: ProjectKind; views: ViewId[] | null; state: string;      // state = the project's state folder under root
}
export interface ProjectConfig {
  name: string; kind: ProjectKind; views: ViewId[] | null;
  summary: string; venue: string; deadline: string | null; stage: StageId; language: string;
  paper: { main: string; dir: string }; code: { roots: string[] }; figures: { dir: string }; experiments: { dir: string };
  [k: string]: unknown;
}
export interface ProjectDetail extends ProjectSummary { config: ProjectConfig }

export interface TreeNode { path: string; name: string; kind: 'file' | 'dir'; size?: number; mtime?: number; children?: TreeNode[] }
export interface FileContent { path: string; content: string; sha: string; mtime: number }

export interface ProjectEvent { topic: string; project: string; payload: any }

export interface Health {
  ok: boolean; version: string; fake_agent: boolean;
  clis: Record<'claude' | 'codex', { path: string | null; version: string | null; ok: boolean }>;
  apps: Record<'drawio' | 'omnigraffle' | 'datagraph', { path: string | null; installed: boolean }>;
}

// ------------------------------------------------------------------ agents
export type ProviderId = 'claude' | 'codex';
export type Permission = 'read' | 'write';

export interface ModelInfo {
  id: string; label: string; efforts: string[]; default_effort: string;
  fast: boolean; fast_label?: string; description?: string;
}
export interface ProviderInfo { id: ProviderId; label: string; available: boolean; cli_path: string | null; version: string | null; models: ModelInfo[]; default_model: string }
export interface AgentCatalog { providers: ProviderInfo[] }

export interface ProviderSession {
  session_id: string | null; model: string; effort: string; fast: boolean; permission: Permission;
  title?: string; updated_at?: string | null;
}
export interface PanelBinding {
  active: ProviderId;
  claude: ProviderSession;
  codex: ProviderSession;
}
/** The project conversation's binding (older files may hold entries for other views; they are not used). */
export interface SessionsDoc { version: 1; panels: { project: PanelBinding } & Partial<Record<PanelId, PanelBinding>> }

export interface DiscoveredSession {
  provider: ProviderId; session_id: string; title: string; cwd: string; updated_at: string; turns: number; bound_to?: PanelId | null;
}

export interface RunContext {
  node_id?: string; file?: string; selection?: { text: string; start_line?: number; end_line?: number }; extra?: string;
}
export interface RunRequest {
  panel: PanelId; prompt: string; purpose?: string;      // chat | review | explain | figure | handoff | ...
  context?: RunContext;
  ephemeral?: boolean;                                    // one-shot: no session created or resumed
  provider?: ProviderId; model?: string; effort?: string; fast?: boolean; permission?: Permission;  // overrides
}
export interface RunStarted { run_id: string; provider: ProviderId | 'fake'; model: string; effort: string; fast: boolean; session_id: string | null }

export type AgentEvent =
  | { type: 'start'; provider: string; model: string; effort: string; fast: boolean; session_id: string | null; purpose: string }
  | { type: 'session'; session_id: string }
  | { type: 'text'; delta: string }
  | { type: 'thinking'; text?: string }
  | { type: 'tool'; name: string; detail?: string }
  | { type: 'usage'; input: number; output: number; cache_read?: number; cost?: number | null }
  | { type: 'error'; message: string }
  | { type: 'done'; ok: boolean; text: string; session_id: string | null; duration_ms: number; cancelled?: boolean };

export interface TranscriptEntry {
  ts: string; panel: PanelId; provider: ProviderId | 'fake'; session_id: string | null; role: 'user' | 'assistant' | 'handoff';
  text: string; run_id?: string; purpose?: string;
}

// ------------------------------------------------------------------ writing
export type ReviewPass = 'typo' | 'terminology' | 'wording' | 'consistency' | 'logic';
export const REVIEW_PASSES: ReviewPass[] = ['typo', 'terminology', 'wording', 'consistency', 'logic'];

export interface WritingDoc { path: string; title: string; kind: 'tex' | 'md'; words: number; updated_at: number; claims: number; stale_claims: number }
export interface Finding {
  id: string; pass: ReviewPass; kind: string;            // typo | grammar | punctuation | math | term | notation | number | claim | wording | logic-gap ...
  quote: string; before: string; replacement: string | null; reason: string; confidence: number;
  line?: number | null; related?: { quote: string; line?: number | null }[];
  status: 'open' | 'accepted' | 'rejected'; evidence_node?: string | null;
}
export interface ReviewResult { review_id: string; path: string; passes: ReviewPass[]; findings: Finding[]; status: 'running' | 'done' | 'error'; progress: Partial<Record<ReviewPass, 'pending' | 'running' | 'done' | 'error'>>; error?: string }
export interface GlossaryTerm { term: string; preferred: string; avoid: string[]; note?: string }
export interface LearnedRule { id: string; pass: ReviewPass | 'all'; text: string; on: boolean; created_at: string }
export interface DocVersion { id: string; label: string; created_at: string; source: 'snapshot' | 'git'; sha?: string }

// ------------------------------------------------------------------ coding
export interface GitStatus { is_repo: boolean; branch: string | null; head: string | null; dirty: { path: string; status: string }[]; ahead: number; behind: number }
export interface GitCommit { sha: string; short: string; subject: string; author: string; date: string; refs: string[]; node_ids?: string[] }
export interface DiffLine { t: '+' | '-' | ' '; old: number | null; new: number | null; text: string }
export interface DiffHunk { header: string; lines: DiffLine[] }
export interface DiffFile { path: string; old_path: string | null; status: 'A' | 'M' | 'D' | 'R'; additions: number; deletions: number; hunks: DiffHunk[]; binary?: boolean }
export interface DiffResult { from: string | null; to: string | null; files: DiffFile[] }
export interface ArchModule { id: string; path: string; label: string; kind: 'package' | 'module' | 'script' | 'config'; loc: number; component?: string | null }
export interface ArchComponent { id: string; label: string; node_id?: string | null; paths: string[]; description?: string }
export interface Architecture { modules: ArchModule[]; edges: { from: string; to: string; kind: 'import' | 'calls' | 'data' }[]; components: ArchComponent[]; generated_at: string }
export interface CodeFinding { id: string; file: string; line: number | null; severity: 'high' | 'medium' | 'low' | 'info'; title: string; body: string; suggestion?: string | null; status: 'open' | 'resolved' | 'dismissed' }

// ------------------------------------------------------------------ experiments and resources
export type ExperimentStatus = 'planned' | 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'unknown';
export interface Experiment {
  id: string; node_id: string | null; title: string; status: ExperimentStatus;
  freshness: 'fresh' | 'stale' | 'reusable' | 'unknown';   // from the DAG: does it need a rerun?
  stale_reasons?: string[];
  target: { platform: string; node: string; gpus: number; gpu_type?: string };
  config: Record<string, unknown>; code: { commit: string | null; footprint: string[] };
  dataset?: string | null; env?: string | null;
  metrics: Record<string, number | string>; started_at: string | null; finished_at: string | null;
  job_id?: string | null; logs_tail?: string[]; artifacts?: string[]; command?: string | null; progress?: number | null;
}
export interface GpuInfo { name: string; util: number | null; mem_used: number | null; mem_total: number | null; temp: number | null; power?: number | null }
export interface ResourceNode { id: string; label: string; status: 'online' | 'offline' | 'stale' | 'unknown'; gpus: GpuInfo[]; cpu?: number | null; ram?: number | null; running?: string[]; note?: string }
export interface Platform { id: string; label: string; kind: 'cloud' | 'lab' | 'home' | 'local'; status: 'ok' | 'degraded' | 'disabled' | 'unknown'; nodes: ResourceNode[]; quota?: Record<string, string | number>; cost?: { amount: number | null; currency: string; as_of: string | null; estimate: boolean } | null; note?: string }
export interface Resources { source: string; as_of: string; platforms: Platform[] }   // source 'demo' = made-up data

// ------------------------------------------------------------------ visualization
export type FigureKind = 'drawio' | 'matplotlib' | 'omnigraffle' | 'datagraph';
export interface Figure {
  id: string; title: string; kind: FigureKind; source: string; data: string[]; preview: string | null;
  updated_at: string | null; node_id?: string | null; caption?: string; status?: 'ok' | 'stale' | 'error' | 'unrendered';
}
export interface RenderResult { ok: boolean; preview: string | null; log: string; duration_ms: number }
export interface StyleTokens {
  font: { family: string; cjk: string[]; size_pt: number };
  palettes: { id: string; label: string; source: string; colors: { role: string; hex: string }[] }[];
  active_palette: string;
  roles: Record<string, { fill: string; stroke: string }>;
  series: string[];
}

// ------------------------------------------------------------------ research DAG
// See docs/DAG.md. Filled in from the DAG spec.
export * from './dag-types';
