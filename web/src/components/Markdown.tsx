// Markdown with KaTeX math ($…$, $$…$$, \(…\), \[…\]). Used by the agent dock, previews and node notes.
// HTML in the source is escaped (agents' answers and project files are data, not markup).
import MarkdownIt from 'markdown-it';
import katex from 'katex';
import { memo, useMemo } from 'react';

const md = new MarkdownIt({ html: false, linkify: true, breaks: false, typographer: false });

// Links open outside the dashboard.
const defaultLink = md.renderer.rules.link_open ?? ((tokens, idx, options, _env, self) => self.renderToken(tokens, idx, options));
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  tokens[idx].attrSet('target', '_blank');
  tokens[idx].attrSet('rel', 'noreferrer noopener');
  return defaultLink(tokens, idx, options, env, self);
};

function renderMath(tex: string, display: boolean): string {
  try { return katex.renderToString(tex, { displayMode: display, throwOnError: false, strict: 'ignore', output: 'html' }); }
  catch { return `<code>${tex.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]!))}</code>`; }
}

/** Replace math with placeholders before markdown, then put rendered KaTeX back (keeps markdown from mangling TeX).
 *  Placeholders use private-use characters: markdown-it turns NUL into U+FFFD. */
export function renderMarkdown(src: string): string {
  const store: string[] = [];
  const keep = (html: string) => `\uE000${store.push(html) - 1}\uE000`;
  // Protect code first so $ inside code stays literal.
  const codes: string[] = [];
  let text = src.replace(/```[\s\S]*?```|`[^`\n]+`/g, m => `\uE001${codes.push(m) - 1}\uE001`);
  text = text
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => keep(renderMath(t, true)))
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, t) => keep(renderMath(t, true)))
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, t) => keep(renderMath(t, false)))
    .replace(/(^|[^\\$])\$([^\s$](?:[^$\n]*?[^\s$])?)\$(?!\d)/g, (_, pre, t) => pre + keep(renderMath(t, false)));
  text = text.replace(/\uE001(\d+)\uE001/g, (_, i) => codes[Number(i)]);
  const html = md.render(text);
  return html.replace(/\uE000(\d+)\uE000/g, (_, i) => store[Number(i)]);
}

export const Markdown = memo(function Markdown({ text, className }: { text: string; className?: string }) {
  const html = useMemo(() => renderMarkdown(text), [text]);
  return <div className={`md ${className ?? ''}`} dangerouslySetInnerHTML={{ __html: html }} />;
});
