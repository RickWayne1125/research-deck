import { describe, expect, it } from 'vitest';
import { folderName, nameFromIdea } from './api';
import { waitsForStep } from '../state/stages';

describe('new projects', () => {
  it('names the folder the way the server does (start/create.py folder_name)', () => {
    expect(folderName('MoE 专家预取')).toBe('moe-专家预取');
    expect(folderName('  ../Weird: name?  ')).toBe('weird-name');
    expect(folderName('!!!')).toBe('project');
  });

  it('takes a name from the first line of the idea', () => {
    expect(nameFromIdea('# MoE expert prefetching\n\nMore text.')).toBe('MoE expert prefetching');
    expect(nameFromIdea('显存放不下全部专家时，用请求队列预取专家。目标：2 倍吞吐')).toBe('显存放不下全部专家时');
    expect(nameFromIdea('   \n  ')).toBe('');
  });
});

describe('stage rules', () => {
  it('keeps drafts of a later step waiting unless the rules are off', () => {
    expect(waitsForStep({ stage: 'S2' }, 'idea', 'strict')).toBe(true);
    expect(waitsForStep({ stage: 'S5' }, 'insight', 'ahead')).toBe(true);
    expect(waitsForStep({ stage: 'S1' }, 'idea', 'strict')).toBe(false);
    expect(waitsForStep({ stage: 'S2' }, 'insight', 'strict')).toBe(false);
    expect(waitsForStep({ stage: 'S6' }, 'idea', 'free')).toBe(false);
    expect(waitsForStep({ stage: 'S6' }, 'idea', undefined)).toBe(false);
  });
});
