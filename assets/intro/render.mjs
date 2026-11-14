// Rend intro.html image par image dans Chrome et encode le tout en mp4.
// Usage : node render.mjs [--nom "MonPort"] [--out intro.mp4]
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { parseArgs } from 'node:util';
import ffmpegPath from 'ffmpeg-static';
import puppeteer from 'puppeteer-core';

const here = path.dirname(fileURLToPath(import.meta.url));
const { values: args } = parseArgs({
  options: { nom: { type: 'string', default: 'MonPort' }, out: { type: 'string', default: 'intro.mp4' } },
});

const FPS = 60;
const DURATION = 3;
const W = 1920;
const H = 1080;
const SUPERSAMPLE = 2; // rendu en 4K puis réduit, pour des contours plus nets
const CHROME = process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const out = path.resolve(here, args.out);

const svg = await readFile(path.join(here, '../mascot/svg/01-wave.svg'), 'utf8');
const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: true,
  args: ['--force-color-profile=srgb', '--hide-scrollbars'],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: W, height: H, deviceScaleFactor: SUPERSAMPLE });
  await page.emulateMediaFeatures([{ name: 'prefers-reduced-motion', value: 'no-preference' }]);
  await page.goto(pathToFileURL(path.join(here, 'intro.html')).href, { waitUntil: 'networkidle0' });
  const info = await page.evaluate((s, n) => window.setup(s, n), svg, args.nom);
  if (!info.fontOk) throw new Error('Plus Jakarta Sans ne s’est pas chargée (réseau?)');
  console.log(`setup : décalage ${info.offset.toFixed(0)} px, ${info.anims} animations de Pépite`);

  const ffmpeg = spawn(
    ffmpegPath,
    [
      '-y', '-loglevel', 'error',
      '-f', 'image2pipe', '-framerate', String(FPS), '-i', '-',
      '-vf', `scale=w=${W}:h=${H}:flags=lanczos:out_color_matrix=bt709:out_range=tv,format=yuv420p`,
      '-c:v', 'libx264', '-preset', 'slow', '-crf', '14', '-profile:v', 'high',
      '-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709',
      '-movflags', '+faststart',
      out,
    ],
    { stdio: ['pipe', 'inherit', 'inherit'] },
  );

  const frames = FPS * DURATION;
  for (let i = 0; i < frames; i++) {
    await page.evaluate(t => window.renderFrame(t), i / FPS);
    const png = await page.screenshot({ type: 'png', optimizeForSpeed: true });
    if (!ffmpeg.stdin.write(png)) await once(ffmpeg.stdin, 'drain');
    if ((i + 1) % FPS === 0) console.log(`${i + 1}/${frames} images`);
  }
  ffmpeg.stdin.end();
  const [code] = await once(ffmpeg, 'close');
  if (code !== 0) throw new Error(`ffmpeg a échoué (code ${code})`);
  console.log(`→ ${out}`);
} finally {
  await browser.close();
}
