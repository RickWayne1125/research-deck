// Pure parts of the Writing panel: locating a finding's quote (mirrors writing/findings.py), word counts (mirrors
// writing/docs.py) and the light LaTeX preview.
import { describe, expect, it } from 'vitest';
import { lineAt, locate, wordCount } from './text';
import { renderTex, type TexLabels } from './texPreview';

const TEXT = 'Alpha beta the cache.\nThe cache is   warm here and the cache\nis cold.\n';
const L: TexLabels = { abstract: 'Abstract', figure: 'Figure', table: 'Table', algorithm: 'Algorithm', input: 'Input', references: 'References', code: 'Code' };

describe('locate', () => {
  it('picks the occurrence whose preceding text ends like `before`', () => {
    const first = TEXT.indexOf('the cache');
    const last = TEXT.lastIndexOf('the cache');
    expect(locate(TEXT, 'the cache', 'and ')).toEqual({ from: last, to: last + 9 });
    expect(locate(TEXT, 'the cache', 'Alpha beta ')).toEqual({ from: first, to: first + 9 });
  });
  it('falls back to the occurrence nearest a hint, then to loose whitespace', () => {
    const last = TEXT.lastIndexOf('the cache');
    expect(locate(TEXT, 'the cache', '', last - 3)).toEqual({ from: last, to: last + 9 });
    const at = locate(TEXT, 'is warm here', '')!;
    expect(TEXT.slice(at.from, at.to)).toBe('is   warm here');
    expect(locate(TEXT, 'absent', '')).toBeNull();
    expect(locate(TEXT, '', '')).toBeNull();
  });
  it('counts lines', () => {
    expect(lineAt(TEXT, 0)).toBe(1);
    expect(lineAt(TEXT, TEXT.indexOf('is cold'))).toBe(3);
  });
});

describe('wordCount', () => {
  it('skips LaTeX commands, keys and comments', () => {
    expect(wordCount('\\section{System Design}\nThe prefetcher reads ahead~\\cite{flexgen}.\n% a comment here\n', 'tex')).toBe(6);
    expect(wordCount('Costs 50\\% less', 'tex')).toBe(3);
  });
  it('counts CJK characters one each and skips front matter and code in Markdown', () => {
    expect(wordCount('---\ntitle: x\n---\n# Research plan\n\nFirst we 测量 the cache.\n\n```py\ncode words\n```\n', 'md')).toBe(8);
  });
});

describe('renderTex', () => {
  const doc = [
    '\\documentclass{article}', '\\title{Tiered \\emph{KV} Caching}', '\\author{Ada \\and Alan}', '\\begin{document}', '\\maketitle',
    '\\begin{abstract}', 'We cut latency by $1.7\\times$. % hidden comment', '\\end{abstract}',
    '\\section{Intro}', 'See~\\cite{vllm, flexgen} and Figure~\\ref{fig:a}; it is \\textbf{fast} --- really.',
    '\\begin{figure}', '\\includegraphics{figures/a.pdf}', '\\caption{The \\emph{arch}.}', '\\label{fig:a}', '\\end{figure}',
    '\\begin{itemize}', '\\item one', '\\item two <b>', '\\end{itemize}', '\\end{document}',
  ].join('\n');
  const html = renderTex(doc, L);
  it('renders the title block, sections and inline markup', () => {
    expect(html).toContain('<h1>Tiered <em>KV</em> Caching</h1>');
    expect(html).toContain('Ada · Alan');
    expect(html).toContain('<h2>Intro</h2>');
    expect(html).toContain('<strong>fast</strong> — really.');
    expect(html).toContain('class="wr-pv-abstract"');
  });
  it('shows citations as [key], references as ? and floats as placeholders', () => {
    expect(html).toContain('[vllm, flexgen]');
    expect(html).toContain('<span class="wr-pv-ref">?</span>');
    expect(html).toContain('figures/a.pdf');
    expect(html).toContain('<figcaption>The <em>arch</em>.</figcaption>');
    expect(html).toMatch(/<ul><li>.*one.*<\/li><li>.*two.*<\/li><\/ul>/s);
  });
  it('renders math with KaTeX, drops comments and escapes the source', () => {
    expect(html).toContain('class="katex"');
    expect(html).not.toContain('hidden comment');
    expect(html).toContain('two &lt;b&gt;');
    expect(html).not.toContain('<b>');
  });
  it('previews a section file without a document environment', () => {
    const part = renderTex('\\section{Design}\nThe \\texttt{Prefetcher} reads ahead.\n\n\\input{sections/eval}', L);
    expect(part).toContain('<h2>Design</h2>');
    expect(part).toContain('<code>Prefetcher</code>');
    expect(part).toContain('Input: sections/eval');
  });
});
