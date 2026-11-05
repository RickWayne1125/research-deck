// Deadline arithmetic for the header countdown (calendar days in local time).

/** "2027-04-15" is a calendar day in local time; anything with a time part is parsed as given. */
export function parseDeadline(s: string): number {
  const m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime() : Date.parse(s);
}

/** Whole days from today to the deadline (negative once it has passed); null without a valid deadline. */
export function daysUntil(deadline: string | null | undefined, now = new Date()): number | null {
  if (!deadline) return null;
  const ts = parseDeadline(deadline);
  if (!Number.isFinite(ts)) return null;
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const d = new Date(ts);
  const day = new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  return Math.round((day - today) / 86_400_000);
}
