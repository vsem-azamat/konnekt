// Cuts an image to the cover's 1536×1024: fills it, then crops around `focus`
// (0..1 across the original). Returns the same point as a share of the cut
// image, which is what the article's `coverFocus` has to hold: the site crops
// the saved cover a second time around it for the link card.
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export const W = 1536, H = 1024;

export function cut(src, out, focus = 0.5, extra = []) {
  // Scale first, then measure: ffmpeg turns a photo with an EXIF rotation upright, so the
  // stored size ffprobe would report for the original can be the wrong way round.
  const dir = mkdtempSync(join(tmpdir(), 'cut-'));
  try {
    const scaled = join(dir, 'scaled.png');
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', src, '-vf', `scale=${W}:${H}:force_original_aspect_ratio=increase`, scaled]);
    const sw = Number(execFileSync('ffprobe', ['-v', 'error', '-show_entries', 'stream=width', '-of', 'csv=p=0', scaled], { encoding: 'utf8' }).trim());
    const left = Math.min(sw - W, Math.max(0, Math.round(focus * sw - W / 2)));
    execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', scaled, '-vf', `crop=${W}:${H}:${left}:(ih-${H})/2`, ...extra, out]);
    return Math.round(Math.min(1, Math.max(0, (focus * sw - left) / W)) * 1000) / 1000;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}
