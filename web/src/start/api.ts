// New projects from an idea and the early survey (docs/API.md § New projects, § Survey).
import { get, p, patch, post } from '../api/client';
import type { ProjectSummary } from '../types';

export type SurveySource = 'arxiv' | 'semantic_scholar' | 'openalex';
export type StageMode = 'strict' | 'ahead' | 'free';
export const SOURCES: SurveySource[] = ['arxiv', 'semantic_scholar', 'openalex'];
export const SOURCE_LABEL: Record<SurveySource, string> = { arxiv: 'arXiv', semantic_scholar: 'Semantic Scholar', openalex: 'OpenAlex' };

export interface NewProjectSettings {
  dir: string;                      // as the user wrote it (~/Research)
  dir_expanded: string;             // where that points now
  default_dir: string;              // this system's default
  git_init: boolean;
  /** Where a new project keeps its papers: files in the project, or a Zotero collection (Settings → Zotero). */
  literature: 'files' | 'zotero';
  survey: { sources: SurveySource[]; count: number; download_pdfs: boolean; papers_dir: string };
  stage_mode: StageMode;
}

export type SurveyStep = 'frame' | 'search' | 'select' | 'download' | 'draft' | 'write';
export const SURVEY_STEPS: SurveyStep[] = ['frame', 'search', 'select', 'download', 'draft', 'write'];
export type StepState = 'pending' | 'running' | 'done' | 'error' | 'skipped';

export interface SurveyPaper {
  n: number; key: string; title: string; authors: string[]; year: number | null; venue: string | null;
  url: string | null; role: 'competitor' | 'baseline' | 'related' | 'background'; takeaway: string; delta: string;
  closes_gap: boolean; status: 'pending' | 'running' | 'done' | 'failed' | 'link'; file: string | null; error?: string;
  node: string | null; existing: boolean;
  /** With Zotero as the project's backend: the item, and its PDF attachment. */
  zotero?: string; zotero_pdf?: string;
}

export interface Survey {
  id: string;
  status: 'running' | 'done' | 'error' | 'cancelled';
  step: SurveyStep;
  steps: Record<SurveyStep, StepState>;
  created_at: string; finished_at: string | null;
  error: string | null; warnings: string[];
  idea_file: string | null; lang: 'zh' | 'en';
  options: { sources: SurveySource[]; count: number; download_pdfs: boolean; papers_dir: string };
  title: string | null; summary: string | null; queries: string[];
  search: { found: number; sources: Record<string, { found: number; failed: number; error: string | null }> } | null;
  candidates: number;
  papers: SurveyPaper[];
  nodes: string[];
  files: { bib?: string; index?: string; survey?: string };
  agent: { provider: string; model: string; effort: string } | null;
}

export interface NewProjectBody {
  name: string;
  idea: string;
  file?: { name: string; content_base64: string } | null;
  folder?: string | null;
  survey: { enabled: boolean; count?: number; download_pdfs?: boolean };
}
export interface NewProjectResult {
  project: ProjectSummary; root: string; created: boolean; idea_file: string; upload: string | null; survey: Survey | null;
  /** Why the survey did not start (Zotero not reachable, for example); the project exists all the same. */
  survey_error?: string | null;
}

export const startApi = {
  settings: () => get<NewProjectSettings>('/api/settings/new-projects'),
  saveSettings: (change: Partial<Omit<NewProjectSettings, 'survey' | 'dir'>> & { dir?: string | null; survey?: Partial<NewProjectSettings['survey']> }) =>
    patch<NewProjectSettings>('/api/settings/new-projects', change),
  create: (body: NewProjectBody) => post<NewProjectResult>('/api/projects/new', body),
  survey: (pid: string) => get<Survey | null>(p(pid, '/survey')),
  startSurvey: (pid: string, body: { idea?: string; count?: number; download_pdfs?: boolean } = {}) => post<Survey>(p(pid, '/survey'), body),
  cancelSurvey: (pid: string) => post<{ ok: boolean }>(p(pid, '/survey/cancel')),
};

/** The folder name the server makes from a project name (start/create.py folder_name). */
export function folderName(name: string): string {
  const s = name.normalize('NFC').trim().toLowerCase()
    .replace(/[^\p{L}\p{N}_-]+/gu, '-').replace(/-{2,}/g, '-').replace(/^[-_.]+|[-_.]+$/g, '');
  return s.slice(0, 60) || 'project';
}

/** A name for the project from the idea: its first line, without Markdown marks, at most 40 characters. */
export function nameFromIdea(idea: string): string {
  const line = idea.split('\n').map(l => l.replace(/^[#>*\-\s]+/, '').trim()).find(Boolean) ?? '';
  const cut = line.split(/[。．.!?！？;；:：,，]/)[0].trim();
  return (cut || line).slice(0, 40);
}

/** Read a File as base64 (no data: prefix). */
export function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).replace(/^data:[^,]*,/, ''));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}
