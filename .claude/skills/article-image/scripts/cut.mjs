// Cuts an image to the cover's 1536×1024: fills it, then crops around `focus`
// (0..1 across the original). Returns the same point as a share of the cut
// image, which is what the article's `coverFocus` has to hold: the site crops
// the saved cover a second time around it for the link card.
import { execFileSync } from 'node:child_process';

export const W = 1536, H = 1024;

export function cut(src, out, focus = 0.5, extra = []) {
  const [iw, ih] = execFileSync('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height', '-of', 'csv=p=0', src], { encoding: 'utf8' })
    .trim().split(',').map(Number);
  const s = Math.max(W / iw, H / ih);
  const sw = Math.round(iw * s);
  const left = Math.min(sw - W, Math.max(0, Math.round(focus * sw - W / 2)));
  const vf = `scale=${sw}:-2,crop=${W}:${H}:${left}:(ih-${H})/2`;
  execFileSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', src, '-vf', vf, ...extra, out]);
  return Math.round(Math.min(1, Math.max(0, (focus * sw - left) / W)) * 1000) / 1000;
}
