// What the panel needs from an open figure editor: save before leaving, and whether there is unsaved work.
export interface EditorHandle {
  save: () => Promise<boolean>;
  dirty: () => boolean;
}
