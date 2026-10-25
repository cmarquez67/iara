// Esfera animada da IARA. Componente isolado: só desenha.
// API: const orb = createOrb(canvas); orb.setState('idle'|'listening'|'thinking'|'speaking'); orb.setLevel(0..1)
// Para trocar o visual, substitua este arquivo mantendo a mesma API.

const PALETTES = {
  idle:      { hi: [169, 219, 230], lo: [59, 126, 166], glow: [90, 170, 205] },
  listening: { hi: [143, 245, 210], lo: [31, 156, 138], glow: [80, 230, 190] },
  thinking:  { hi: [195, 178, 255], lo: [90, 70, 200],  glow: [150, 120, 255] },
  speaking:  { hi: [255, 226, 154], lo: [224, 164, 58], glow: [255, 200, 110] },
};

// breath: amplitude da respiração; speed: velocidade interna; wobble: deformação da borda;
// gain: quanto o nível de áudio aumenta a esfera; swirl: velocidade das manchas internas.
const MOTION = {
  idle:      { breath: 0.035, breathRate: 0.55, wobble: 0.012, gain: 0.0,  swirl: 0.25 },
  listening: { breath: 0.015, breathRate: 0.9,  wobble: 0.03,  gain: 0.28, swirl: 0.6 },
  thinking:  { breath: 0.02,  breathRate: 1.6,  wobble: 0.025, gain: 0.0,  swirl: 1.8 },
  speaking:  { breath: 0.01,  breathRate: 0.9,  wobble: 0.045, gain: 0.34, swirl: 0.9 },
};

const lerp = (a, b, k) => a + (b - a) * k;
const rgba = (c, a) => `rgba(${c[0] | 0}, ${c[1] | 0}, ${c[2] | 0}, ${a})`;

export function createOrb(canvas) {
  const ctx = canvas.getContext('2d');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let state = 'idle';
  let targetLevel = 0;
  let level = 0;
  const color = structuredClone(PALETTES.idle);
  const motion = { ...MOTION.idle };
  let width = 0, height = 0, dpr = 1, raf = 0, last = performance.now(), t = 0;

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = canvas.clientWidth;
    height = canvas.clientHeight;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }

  function blendTowards(k) {
    const p = PALETTES[state];
    for (const key of ['hi', 'lo', 'glow']) {
      for (let i = 0; i < 3; i++) color[key][i] = lerp(color[key][i], p[key][i], k);
    }
    const m = MOTION[state];
    for (const key in m) motion[key] = lerp(motion[key], m[key], k);
  }

  function bodyPath(cx, cy, r) {
    const n = 120;
    const amp = motion.wobble * (1 + level * 3);
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const a = (i / n) * Math.PI * 2;
      const d =
        Math.sin(a * 3 + t * 1.3) * 0.5 +
        Math.sin(a * 5 - t * 1.7) * 0.3 +
        Math.sin(a * 2 + t * 0.7) * 0.2;
      const rr = r * (1 + amp * d);
      const x = cx + Math.cos(a) * rr;
      const y = cy + Math.sin(a) * rr;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.closePath();
  }

  function draw(now) {
    const dt = Math.min(0.05, (now - last) / 1000);
    last = now;
    t += dt * (reduceMotion ? 0.3 : 1);

    blendTowards(1 - Math.pow(0.02, dt)); // transição suave entre estados (~1 s)
    // ataque rápido, soltura lenta: acompanha sílabas sem tremer
    const k = targetLevel > level ? 1 - Math.pow(0.0005, dt) : 1 - Math.pow(0.08, dt);
    level = lerp(level, targetLevel, k);

    const cx = (width / 2) * dpr;
    const cy = (height * 0.44) * dpr;
    const base = Math.min(width, height) * 0.2 * dpr;
    const breath = Math.sin(t * motion.breathRate * Math.PI) * motion.breath;
    const r = base * (1 + breath + level * motion.gain);

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // halo
    const glow = ctx.createRadialGradient(cx, cy, r * 0.4, cx, cy, r * 2.4);
    glow.addColorStop(0, rgba(color.glow, 0.28 + level * 0.25));
    glow.addColorStop(1, rgba(color.glow, 0));
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    // corpo
    ctx.save();
    bodyPath(cx, cy, r);
    const body = ctx.createRadialGradient(cx - r * 0.35, cy - r * 0.4, r * 0.1, cx, cy, r * 1.05);
    body.addColorStop(0, rgba(color.hi, 1));
    body.addColorStop(1, rgba(color.lo, 1));
    ctx.fillStyle = body;
    ctx.fill();
    ctx.clip();

    // manchas internas: dão a sensação de líquido em movimento
    ctx.globalCompositeOperation = 'lighter';
    const s = t * motion.swirl;
    const blobs = [
      [Math.cos(s) * 0.45, Math.sin(s * 1.2) * 0.4, 0.75, color.hi, 0.35],
      [Math.cos(s * 0.8 + 2.1) * 0.5, Math.sin(s + 1.3) * 0.45, 0.65, color.glow, 0.3],
      [Math.cos(-s * 1.1 + 4.2) * 0.35, Math.sin(-s * 0.9 + 3.7) * 0.5, 0.55, [255, 255, 255], 0.12],
    ];
    for (const [ox, oy, size, c, a] of blobs) {
      const bx = cx + ox * r, by = cy + oy * r, br = r * size;
      const g = ctx.createRadialGradient(bx, by, 0, bx, by, br);
      g.addColorStop(0, rgba(c, a + level * 0.2));
      g.addColorStop(1, rgba(c, 0));
      ctx.fillStyle = g;
      ctx.fillRect(bx - br, by - br, br * 2, br * 2);
    }
    ctx.globalCompositeOperation = 'source-over';

    // brilho especular
    const spec = ctx.createRadialGradient(cx - r * 0.4, cy - r * 0.5, 0, cx - r * 0.4, cy - r * 0.5, r * 0.55);
    spec.addColorStop(0, 'rgba(255,255,255,0.35)');
    spec.addColorStop(1, 'rgba(255,255,255,0)');
    ctx.fillStyle = spec;
    ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
    ctx.restore();

    raf = requestAnimationFrame(draw);
  }

  resize();
  window.addEventListener('resize', resize);
  raf = requestAnimationFrame(draw);

  return {
    setState(next) {
      if (PALETTES[next]) state = next;
    },
    setLevel(value) {
      targetLevel = Math.max(0, Math.min(1, value || 0));
    },
    destroy() {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
    },
  };
}
