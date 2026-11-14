// The main column's layout classes: where a phone, a tablet and a desktop window (with or without the conversation)
// fall, by the column's own width.
import { describe, expect, it } from 'vitest';
import { mainClass } from './layout';

describe('mainClass', () => {
  it('classes the main column by its width', () => {
    expect(mainClass(393)).toBe('phone');           // an iPhone: the whole window
    expect(mainClass(559)).toBe('phone');
    expect(mainClass(560)).toBe('narrow');
    expect(mainClass(592)).toBe('narrow');          // an iPad in landscape with the conversation open
    expect(mainClass(720)).toBe('narrow');          // an iPad in portrait beside the icon rail
    expect(mainClass(900)).toBe('medium');
    expect(mainClass(1199)).toBe('medium');
    expect(mainClass(1232)).toBe('wide');           // a 1440 px window with the navigation
  });
});
