// A light preview of LaTeX source, for reading, not typesetting: title, sections, paragraphs, lists, \emph / \textbf,
// math through KaTeX, \cite as [key], \ref as ?, figures and tables as placeholders with their captions.
// Everything from the source is escaped; only the tags written here reach the page.
import katex from 'katex';

export interface TexLabels { abstract: string; figure: string; table: string; algorithm: string; input: string; references: string; code: string }

const esc = (s: string) => s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!));

function renderMath(tex: string, display: boolean): string {
  const clean = tex.replace(/\\label\{[^}]*\}/g, '').replace(/\\nonumber|\\notag/g, '');
  try { return katex.renderToString(clean, { displayMode: display, throwOnError: false, strict: 'ignore', output: 'html', trust: false }); }
  catch { return `<code>${esc(tex)}</code>`; }
}

/** The content of the brace group at s[i] === '{' and the index after it; a lone token when there is no brace. */
function group(s: string, i: number): [string, number] {
  while (i < s.length && /\s/.test(s[i]) && s[i] !== '\n') i++;
  if (s[i] !== '{') {
    if (s[i] === '\\') { const m = /^\\([a-zA-Z]+|.)/.exec(s.slice(i)); return m ? [m[0], i + m[0].length] : ['', i]; }
    return [s[i] ?? '', i + 1];
  }
  let depth = 0;
  for (let j = i; j < s.length; j++) {
    const c = s[j];
    if (c === '\\') { j++; continue; }
    if (c === '{') depth++;
    else if (c === '}' && --depth === 0) return [s.slice(i + 1, j), j + 1];
  }
  return [s.slice(i + 1), s.length];
}

function optional(s: string, i: number): [string | null, number] {
  let j = i;
  while (j < s.length && s[j] === ' ') j++;
  if (s[j] !== '[') return [null, i];
  const end = s.indexOf(']', j);
  return end < 0 ? [null, i] : [s.slice(j + 1, end), end + 1];
}

const WRAP: Record<string, [string, string]> = {
  emph: ['<em>', '</em>'], textit: ['<em>', '</em>'], textsl: ['<em>', '</em>'], textbf: ['<strong>', '</strong>'],
  texttt: ['<code>', '</code>'], underline: ['<u>', '</u>'], textsc: ['<span class="wr-pv-sc">', '</span>'],
  mbox: ['', ''], text: ['', ''], textrm: ['', ''], textsf: ['', ''], textnormal: ['', ''],
};
const SYMBOLS: Record<string, string> = {
  ldots: '…', dots: '…', textendash: '–', textemdash: '—', LaTeX: 'LaTeX', TeX: 'TeX', today: '', quad: ' ', qquad: '  ',
  ' ': ' ', ',': ' ', ';': ' ', '!': '', '/': '', '-': '', '@': '', '%': '%', '&': '&amp;', '_': '_', '#': '#', '$': '$', '{': '{', '}': '}',
  textbackslash: '\\', S: '§', P: '¶', copyright: '©', 'textasciitilde': '~',
};
const DROP_WITH_ARG = new Set(['label', 'vspace', 'hspace', 'thanks', 'bibliographystyle', 'usepackage', 'documentclass', 'newcommand',
  'renewcommand', 'setlength', 'pagestyle', 'thispagestyle', 'graphicspath', 'definecolor', 'addbibresource']);

/** Inline LaTeX → HTML. Math was replaced by \u0000…\u0000 placeholders before. */
function inline(s: string): string {
  let out = '';
  let i = 0;
  while (i < s.length) {
    const c = s[i];
    if (c === '\u0000') {
      const end = s.indexOf('\u0000', i + 1);
      if (end < 0) { i++; continue; }
      out += s.slice(i, end + 1); i = end + 1; continue;
    }
    if (c === '\\') {
      const m = /^\\([a-zA-Z]+\*?|.)/.exec(s.slice(i));
      if (!m) { i++; continue; }
      const name = m[1].replace(/\*$/, '');
      i += m[0].length;
      if (name === '\\') { [, i] = optional(s, i); out += '<br>'; continue; }
      if (name in SYMBOLS) { out += SYMBOLS[name]; if (/^[a-zA-Z]+$/.test(name) && s[i] === '{' && s[i + 1] === '}') i += 2; continue; }
      if (name in WRAP) { const [arg, next] = group(s, i); out += WRAP[name][0] + inline(arg) + WRAP[name][1]; i = next; continue; }
      if (/^(cite|citep|citet|citealp|citeauthor|citeyear|parencite|textcite|autocite|nocite)$/.test(name)) {
        let next = i; let opt: string | null;
        [opt, next] = optional(s, next); [, next] = optional(s, next);
        const [keys, after] = group(s, next);
        out += name === 'nocite' ? '' : `<span class="wr-pv-cite">[${esc(keys.split(',').map(k => k.trim()).filter(Boolean).join(', '))}${opt ? ', ' + esc(opt) : ''}]</span>`;
        i = after; continue;
      }
      if (/^(ref|cref|Cref|autoref|pageref|nameref|vref)$/.test(name)) { const [, next] = group(s, i); out += '<span class="wr-pv-ref">?</span>'; i = next; continue; }
      if (name === 'eqref') { const [, next] = group(s, i); out += '<span class="wr-pv-ref">(?)</span>'; i = next; continue; }
      if (name === 'url') { const [u, next] = group(s, i); out += `<span class="wr-pv-url">${esc(u)}</span>`; i = next; continue; }
      if (name === 'href') { const [, a] = group(s, i); const [t, next] = group(s, a); out += inline(t); i = next; continue; }
      if (name === 'footnote') { const [t, next] = group(s, i); out += `<span class="wr-pv-fn">${inline(t)}</span>`; i = next; continue; }
      if (DROP_WITH_ARG.has(name)) { let next = i; [, next] = optional(s, next); [, next] = group(s, next); i = next; continue; }
      if (name === 'item') continue;
      // Any other command: keep its argument's text, drop the command.
      [, i] = optional(s, i);
      if (s[i] === '{') { const [arg, next] = group(s, i); out += inline(arg); i = next; }
      continue;
    }
    if (c === '{' || c === '}') { i++; continue; }
    if (c === '~') { out += ' '; i++; continue; }
    if (s.startsWith('``', i)) { out += '“'; i += 2; continue; }
    if (s.startsWith("''", i)) { out += '”'; i += 2; continue; }
    if (c === '`') { out += '‘'; i++; continue; }
    if (s.startsWith('---', i)) { out += '—'; i += 3; continue; }
    if (s.startsWith('--', i)) { out += '–'; i += 2; continue; }
    out += esc(c);
    i++;
  }
  return out;
}

/** The index of the \end{name} matching a \begin{name} whose body starts at `from` (nesting of the same name counted). */
function matchingEnd(s: string, name: string, from: number): [number, number] {
  const re = new RegExp(`\\\\(begin|end)\\{${name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\}`, 'g');
  re.lastIndex = from;
  let depth = 1;
  for (let m = re.exec(s); m; m = re.exec(s)) {
    depth += m[1] === 'begin' ? 1 : -1;
    if (depth === 0) return [m.index, m.index + m[0].length];
  }
  return [s.length, s.length];
}

/** Split a list body at its top-level \item. */
function items(body: string): { label: string | null; text: string }[] {
  const out: { label: string | null; text: string }[] = [];
  let depth = 0, start = -1, label: string | null = null;
  const re = /\\(begin|end)\{[^}]*\}|\\item\b/g;
  for (let m = re.exec(body); m; m = re.exec(body)) {
    if (m[1] === 'begin') depth++;
    else if (m[1] === 'end') depth--;
    else if (depth === 0) {
      if (start >= 0) out.push({ label, text: body.slice(start, m.index) });
      const [opt, next] = optional(body, m.index + m[0].length);
      label = opt; start = next;
      re.lastIndex = next;
    }
  }
  if (start >= 0) out.push({ label, text: body.slice(start) });
  return out;
}

const HEADING = /\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?(?:\[[^\]]*\])?\s*(?=\{)/g;
const HEAD_LEVEL: Record<string, number> = { part: 2, chapter: 2, section: 2, subsection: 3, subsubsection: 4, paragraph: 5, subparagraph: 5 };

function paragraphs(text: string, L: TexLabels): string {
  // Headings become their own blocks; \input / \include and the bibliography become placeholders.
  let src = '';
  let last = 0;
  HEADING.lastIndex = 0;
  for (let m = HEADING.exec(text); m; m = HEADING.exec(text)) {
    const [title, next] = group(text, m.index + m[0].length);
    src += text.slice(last, m.index) + `\n\n\u0001H${HEAD_LEVEL[m[1]]}\u0002${title}\u0001\n\n`;
    last = next;
    HEADING.lastIndex = next;
  }
  src += text.slice(last);
  src = src.replace(/\\(input|include)\{([^}]*)\}/g, (_, _c, f) => `\n\n\u0001P\u0002${L.input}: ${f}\u0001\n\n`)
    .replace(/\\(bibliography|printbibliography)(\{[^}]*\})?/g, `\n\n\u0001P\u0002${L.references}\u0001\n\n`)
    .replace(/\\(maketitle|tableofcontents|newpage|clearpage|centering|noindent|appendix|small|footnotesize|large|Large)\b/g, '');
  return src.split(/\n[ \t]*\n/).map(p => p.trim()).filter(Boolean).map(p => {
    const h = /^\u0001H(\d)\u0002([\s\S]*)\u0001$/.exec(p);
    if (h) return Number(h[1]) >= 5 ? `<div class="wr-pv-p"><strong>${inline(h[2])}</strong></div>` : `<h${h[1]}>${inline(h[2])}</h${h[1]}>`;
    const ph = /^\u0001P\u0002([\s\S]*)\u0001$/.exec(p);
    if (ph) return `<div class="wr-pv-ph">${esc(ph[1])}</div>`;
    return `<div class="wr-pv-p">${inline(p)}</div>`;
  }).join('\n');
}

function float(kind: string, body: string, L: TexLabels): string {
  const cap = /\\caption(?:\[[^\]]*\])?\s*(?=\{)/.exec(body);
  const caption = cap ? group(body, cap.index + cap[0].length)[0] : '';
  const file = /\\includegraphics(?:\[[^\]]*\])?\{([^}]*)\}/.exec(body)?.[1];
  const name = kind.startsWith('table') ? L.table : kind.startsWith('algorithm') ? L.algorithm : L.figure;
  return `<figure class="wr-pv-fig"><div class="wr-pv-ph"><span class="label">${esc(name)}</span>${file ? ` <span class="mono">${esc(file)}</span>` : ''}</div>`
    + (caption ? `<figcaption>${inline(caption)}</figcaption>` : '') + '</figure>';
}

function blocks(src: string, L: TexLabels): string {
  let html = '';
  let i = 0;
  const re = /\\begin\{([^}]+)\}/g;
  while (i < src.length) {
    re.lastIndex = i;
    const m = re.exec(src);
    if (!m) { html += paragraphs(src.slice(i), L); break; }
    html += paragraphs(src.slice(i, m.index), L);
    const name = m[1];
    const bodyStart = m.index + m[0].length;
    const [endAt, after] = matchingEnd(src, name, bodyStart);
    const body = src.slice(bodyStart, endAt);
    const base = name.replace(/\*$/, '');
    if (base === 'abstract') html += `<section class="wr-pv-abstract"><div class="label">${esc(L.abstract)}</div>${blocks(body, L)}</section>`;
    else if (/^(figure|table|algorithm|wrapfigure|subfigure)$/.test(base)) html += float(base, body, L);
    else if (base === 'tabular' || base === 'tabularx') html += `<div class="wr-pv-ph"><span class="label">${esc(L.table)}</span></div>`;
    else if (/^(itemize|enumerate|description)$/.test(base)) {
      const tag = base === 'enumerate' ? 'ol' : 'ul';
      html += `<${tag}>${items(body).map(it => `<li>${it.label ? `<strong>${inline(it.label)}</strong> ` : ''}${blocks(it.text, L)}</li>`).join('')}</${tag}>`;
    } else if (base === 'quote' || base === 'quotation') html += `<blockquote>${blocks(body, L)}</blockquote>`;
    else if (/^(verbatim|lstlisting|minted|Verbatim)$/.test(base)) html += `<pre class="wr-pv-code" aria-label="${esc(L.code)}">${esc(body.replace(/^\{[^}]*\}/, '').replace(/^\n/, ''))}</pre>`;
    else html += blocks(body, L);                 // document, center, minipage, theorem-like: their content
    i = after;
  }
  return html;
}

const MATH_ENVS = 'equation|equation\\*|align|align\\*|gather|gather\\*|multline|multline\\*|eqnarray|eqnarray\\*|displaymath|math';

export function renderTex(source: string, L: TexLabels): string {
  // Comments go first (a % inside math is written \%, so it survives).
  let s = source.replace(/(^|[^\\])%.*$/gm, '$1');
  const math: string[] = [];
  const keep = (html: string, display: boolean) => `\u0000${display ? 'D' : 'I'}${math.push(html) - 1}\u0000`;
  s = s.replace(new RegExp(`\\\\begin\\{(${MATH_ENVS})\\}([\\s\\S]*?)\\\\end\\{\\1\\}`, 'g'), (_, env: string, body: string) => {
    const e = env.replace('eqnarray', 'align').replace(/^(displaymath|math)$/, '');
    return '\n\n' + keep(renderMath(e ? `\\begin{${e}}${body}\\end{${e}}` : body, true), true) + '\n\n';
  })
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, t) => '\n\n' + keep(renderMath(t, true), true) + '\n\n')
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, t) => '\n\n' + keep(renderMath(t, true), true) + '\n\n')
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, t) => keep(renderMath(t, false), false))
    .replace(/(^|[^\\])\$((?:\\\$|[^$])+?)\$/g, (_, pre, t) => pre + keep(renderMath(t, false), false));

  // Title block from the preamble; the body is what \begin{document} holds when there is one.
  const titleAt = /\\title(?:\[[^\]]*\])?\s*(?=\{)/.exec(s);
  const authorAt = /\\author(?:\[[^\]]*\])?\s*(?=\{)/.exec(s);
  const title = titleAt ? group(s, titleAt.index + titleAt[0].length)[0] : '';
  const author = authorAt ? group(s, authorAt.index + authorAt[0].length)[0] : '';
  const begin = s.indexOf('\\begin{document}');
  let body = s;
  if (begin >= 0) {
    const [end] = matchingEnd(s, 'document', begin + '\\begin{document}'.length);
    body = s.slice(begin + '\\begin{document}'.length, end);
  } else {
    // A file without \begin{document} (a section file): drop the title and author commands from the body.
    for (const at of [authorAt, titleAt].filter((x): x is RegExpExecArray => !!x).sort((a, b) => b.index - a.index)) {
      body = body.slice(0, at.index) + body.slice(group(body, at.index + at[0].length)[1]);
    }
  }
  let html = '';
  if (title) html += `<h1>${inline(title)}</h1>`;
  if (author) html += `<div class="wr-pv-author">${inline(author.replace(/\s*\\and\b\s*/g, ' · '))}</div>`;
  html += blocks(body, L);
  return html.replace(/\u0000([DI])(\d+)\u0000/g, (_, _k, n) => math[Number(n)]);
}
