// Markdown with KaTeX math ($…$, $$…$$, \(…\), \[…\]). Used by the agent dock, previews and node notes.
// HTML in the source is escaped (agents' answers and project files are data, not markup).
import MarkdownIt from 'markdown-it';
import katex from 'katex';
import { memo, useMemo } from 'react';
import { p } from '../api/client';

const md = new MarkdownIt({ html: false, linkify: true, breaks: false, typographer: false });

/** The project document being shown: its relative links and pictures name files beside it. */
export interface DocBase { project: string; path: string }
interface Env { base?: DocBase }

const SCHEME = /^[a-z][a-z0-9+.-]*:/i;
/** The documents the paper view opens itself; any other project file opens from the server in a new tab. */
const DOC_FILE = /\.(md|markdown|tex)$/i;

/** The project file a relative link in a document names ("../papers/a.pdf" from "notes/survey.md" → "papers/a.pdf"),
 *  with its "#page=3" kept. A leading "/" starts at the project folder. null when the link is not a project file (a web
 *  address, "#gaps"), "outside" when it climbs out of the project. */
export function projectFile(href: string, docPath: string): { path: string; hash: string } | 'outside' | null {
  if (!href || SCHEME.test(href) || href.startsWith('//') || href.startsWith('#')) return null;
  const hashAt = href.indexOf('#');
  const hash = hashAt < 0 ? '' : href.slice(hashAt);
  const target = href.slice(0, href.search(/[?#]|$/));
  const parts = target.startsWith('/') ? [] : docPath.split('/').slice(0, -1);
  for (const raw of target.split('/')) {
    let seg = raw;
    try { seg = decodeURIComponent(raw); } catch { /* a stray "%" stays as written */ }
    if (!seg || seg === '.') continue;
    if (seg === '..') { if (!parts.length) return 'outside'; parts.pop(); } else parts.push(seg);
  }
  return parts.length ? { path: parts.join('/'), hash } : null;
}

/** The server's copy of a project file (GET …/raw): the browser shows PDFs and pictures itself. */
export function rawUrl(project: string, path: string): string {
  return `${p(project, '/raw')}?path=${encodeURIComponent(path)}`;
}

/** The paper view's route for a document, the same as navigate('writing', path). */
function docRoute(project: string, path: string): string {
  return `#/${encodeURIComponent(project)}/writing/${path.split('/').map(encodeURIComponent).join('/')}`;
}

// Links open outside the dashboard, except a link to another document of the project, which the paper view opens.
// A link to any other project file opens the server's copy; one that leaves the project stays as text.
const defaultLink = md.renderer.rules.link_open ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.link_open = (tokens, idx, options, env: Env, self) => {
  const token = tokens[idx];
  const base = env?.base;
  const file = base ? projectFile(token.attrGet('href') ?? '', base.path) : null;
  if (file === 'outside') {
    token.attrs = (token.attrs ?? []).filter(([name]) => name !== 'href');
    return defaultLink(tokens, idx, options, env, self);
  }
  if (base && file && DOC_FILE.test(file.path)) {
    token.attrSet('href', docRoute(base.project, file.path));
    return defaultLink(tokens, idx, options, env, self);
  }
  if (base && file) token.attrSet('href', rawUrl(base.project, file.path) + file.hash);
  token.attrSet('target', '_blank');
  token.attrSet('rel', 'noreferrer noopener');
  return defaultLink(tokens, idx, options, env, self);
};

const defaultImage = md.renderer.rules.image!;
md.renderer.rules.image = (tokens, idx, options, env: Env, self) => {
  const base = env?.base;
  const file = base ? projectFile(tokens[idx].attrGet('src') ?? '', base.path) : null;
  if (base && file && file !== 'outside') tokens[idx].attrSet('src', rawUrl(base.project, file.path));
  return defaultImage(tokens, idx, options, env, self);
};

function renderMath(tex: string, display: boolean): string {
  try { return katex.renderToString(tex, { displayMode: display, throwOnError: false, strict: 'ignore', output: 'html' }); }
  catch { return `<code>${tex.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!))}</code>`; }
}

/** Replace math with placeholders before markdown, then put rendered KaTeX back (keeps markdown from mangling TeX).
 *  Placeholders use private-use characters: markdown-it turns NUL into U+FFFD.
 *  base: the project document being shown, so its relative links and pictures open the files they name. */
export function renderMarkdown(src: string, base?: DocBase): string {
  const store: string[] = [];
  const keep = (html: string) => `${store.push(html) - 1}`;
  // Protect code first so $ inside code stays literal.
  const codes: string[] = [];
  let text = src.replace(/```[\s\S]*?```|`[^`\n]+`/g, m => `${codes.push(m) - 1}`);
  text = text
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => keep(renderMath(t, true)))
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, t) => keep(renderMath(t, true)))
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, t) => keep(renderMath(t, false)))
    .replace(/(^|[^\\$])\$([^\s$](?:[^$\n]*?[^\s$])?)\$(?!\d)/g, (_, pre, t) => pre + keep(renderMath(t, false)));
  text = text.replace(/(\d+)/g, (_, i) => codes[Number(i)]);
  const env: Env = { base };
  const html = md.render(text, env);
  return html.replace(/(\d+)/g, (_, i) => store[Number(i)]);
}

export const Markdown = memo(function Markdown({ text, className, base }: { text: string; className?: string; base?: DocBase }) {
  const project = base?.project;
  const path = base?.path;
  const html = useMemo(
    () => renderMarkdown(text, project !== undefined && path !== undefined ? { project, path } : undefined),
    [text, project, path]);
  return <div className={`md ${className ?? ''}`} dangerouslySetInnerHTML={{ __html: html }} />;
});
