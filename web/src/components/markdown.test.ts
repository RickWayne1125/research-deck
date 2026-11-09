import { describe, expect, it } from 'vitest';
import { projectFile, renderMarkdown } from './Markdown';

describe('links in a project document', () => {
  const base = { project: 'my proj', path: 'notes/survey.md' };

  it('names the project file a relative link points at', () => {
    expect(projectFile('../papers/a.pdf', 'notes/survey.md')).toEqual({ path: 'papers/a.pdf', hash: '' });
    expect(projectFile('a.pdf#page=3', 'papers/index.md')).toEqual({ path: 'papers/a.pdf', hash: '#page=3' });
    expect(projectFile('./b%20c.png?x=1', 'notes/survey.md')).toEqual({ path: 'notes/b c.png', hash: '' });
    expect(projectFile('/figures/f.svg', 'notes/deep/x.md')).toEqual({ path: 'figures/f.svg', hash: '' });
    expect(projectFile('../../x.pdf', 'notes/survey.md')).toBe('outside');
    for (const href of ['https://arxiv.org/abs/1', 'mailto:a@b.c', '//cdn.example/x.js', '#gaps', ''])
      expect(projectFile(href, 'notes/survey.md')).toBeNull();
  });

  it('opens a paper beside the document from the server, in a new tab', () => {
    const html = renderMarkdown('[PDF](../papers/smith2024paper.pdf)', base);
    expect(html).toContain('href="/api/projects/my%20proj/raw?path=papers%2Fsmith2024paper.pdf"');
    expect(html).toContain('target="_blank"');
    expect(renderMarkdown('[p. 3](../papers/a.pdf#page=3)', base)).toContain('raw?path=papers%2Fa.pdf#page=3"');
  });

  it('opens another document in the paper view', () => {
    const html = renderMarkdown('[the idea](idea.md)', base);
    expect(html).toContain('href="#/my%20proj/writing/notes/idea.md"');
    expect(html).not.toContain('target=');
  });

  it('shows pictures beside the document', () => {
    expect(renderMarkdown('![f](../figures/f.png)', base)).toContain('src="/api/projects/my%20proj/raw?path=figures%2Ff.png"');
  });

  it('leaves web links alone and keeps a link out of the project as text', () => {
    const web = renderMarkdown('[arXiv](https://arxiv.org/abs/1)', base);
    expect(web).toContain('href="https://arxiv.org/abs/1"');
    expect(web).toContain('target="_blank"');
    const out = renderMarkdown('[x](../../x.pdf)', base);
    expect(out).toContain('>x</a>');
    expect(out).not.toContain('href');
  });

  it('keeps links as written when no document is given (agent answers)', () => {
    expect(renderMarkdown('[a](b.pdf)')).toContain('href="b.pdf"');
  });
});

describe('HTML in a document', () => {
  it('drops comments, the outline file\'s tags included, and keeps other HTML as text', () => {
    const html = renderMarkdown([
      '# Outline', '', '<!-- one line of help', 'across two lines -->', '',
      '## 1 Intro <!-- rd:sec sec.intro -->', '', '- **1.1** One. <!-- rd:item claim.a -->',
      '', 'A <b>bold</b> claim and `<!-- kept in code -->`.', '', '<!-- not closed',
    ].join('\n'));
    expect(html).not.toContain('rd:item');
    expect(html).not.toContain('rd:sec');
    expect(html).not.toContain('one line of help');
    expect(html).not.toContain('<p></p>');
    expect(html).toContain('<h2>1 Intro </h2>');
    expect(html).toContain('<li><strong>1.1</strong> One. </li>');
    expect(html).toContain('A &lt;b&gt;bold&lt;/b&gt; claim');
    expect(html).toContain('<code>&lt;!-- kept in code --&gt;</code>');
    expect(html).toContain('&lt;!-- not closed');
  });
});
