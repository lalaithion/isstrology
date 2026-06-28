/*
 * starfield.js
 * -------------------------------------------------------------------------
 * A self-contained, dependency-free animated background for a dark,
 * editorial space-themed site. Tasteful and restrained: faint parallax
 * stars with a barely-perceptible twinkle, plus a handful of muted,
 * slowly drifting planets you only really notice after staring a while.
 *
 * Usage: <script defer src="/static/starfield.js"></script>
 * The script creates and styles its own <canvas>; no markup required.
 * -------------------------------------------------------------------------
 */
(function () {
  'use strict';

  // ----------------------------------------------------------------------
  // Setup: create and style the canvas, append to <body>.
  // ----------------------------------------------------------------------
  const canvas = document.createElement('canvas');
  canvas.id = 'starfield';
  Object.assign(canvas.style, {
    position: 'fixed',
    inset: '0',
    width: '100vw',
    height: '100vh',
    zIndex: '-1',
    pointerEvents: 'none',
    display: 'block',
  });

  const ctx = canvas.getContext('2d');

  function attach() {
    if (document.body) {
      document.body.appendChild(canvas);
    } else {
      // <body> not parsed yet; wait for it.
      document.addEventListener('DOMContentLoaded', attach, { once: true });
    }
  }
  attach();

  // ----------------------------------------------------------------------
  // Configuration.
  // ----------------------------------------------------------------------

  // Reduced-motion users get a single static frame, no animation.
  const reducedMotionMQ = window.matchMedia('(prefers-reduced-motion: reduce)');

  // Parallax layers, ordered far -> near. Each layer gets a different
  // density weight, size range, brightness range, and scroll factor.
  const LAYERS = [
    { name: 'far',  weight: 0.55, minR: 0.4, maxR: 0.8, minA: 0.20, maxA: 0.45, scroll: 0.02 },
    { name: 'mid',  weight: 0.30, minR: 0.7, maxR: 1.2, minA: 0.30, maxA: 0.65, scroll: 0.05 },
    { name: 'near', weight: 0.15, minR: 1.2, maxR: 2.0, minA: 0.45, maxA: 0.90, scroll: 0.10 },
  ];

  // Density: stars per "area unit". We clamp the total to a sensible range
  // so tiny screens are sparse and huge screens don't get overcrowded.
  const STARS_PER_10K_PX = 0.95;   // ~0.95 stars per 100x100 px block
  const MIN_TOTAL_STARS = 250;
  const MAX_TOTAL_STARS = 600;

  // Star color palette. Mostly soft white / faint blue-white, with a small
  // sprinkle of warm (pale gold) and faint blue tones.
  function pickStarColor() {
    const r = Math.random();
    if (r < 0.08) return { r: 255, g: 225, b: 170 }; // ~8% warm pale gold
    if (r < 0.18) return { r: 180, g: 205, b: 255 }; // ~10% faint blue
    return { r: 240, g: 244, b: 255 };               // rest: soft blue-white
  }

  // Planets look like bright, slightly-tinted points of light (Venus, Mars,
  // Jupiter...), not blobs — a steady core with a faint bloom. What marks them
  // as planets is that they slowly wander against the fixed stars.
  const PLANET_COLORS = [
    { r: 255, g: 244, b: 214 }, // Venus — brilliant warm white
    { r: 235, g: 138, b: 92 },  // Mars — orange-red
    { r: 238, g: 228, b: 205 }, // Jupiter — pale cream
    { r: 232, g: 210, b: 158 }, // Saturn — pale gold
    { r: 205, g: 222, b: 255 }, // a cool blue-white
  ];

  // ----------------------------------------------------------------------
  // State.
  // ----------------------------------------------------------------------
  let dpr = 1;
  let viewW = 0;      // CSS pixels
  let viewH = 0;      // CSS pixels
  let stars = [];     // flat array, each tagged with its layer
  let planets = [];
  let rafId = null;
  let running = false;
  let lastTs = 0;     // rAF timestamp of previous frame (ms)
  let scrollY = window.scrollY || 0;

  // ----------------------------------------------------------------------
  // Field generation.
  // ----------------------------------------------------------------------

  function computeTotalStars() {
    const area = viewW * viewH;
    const raw = (area / 10000) * STARS_PER_10K_PX;
    return Math.round(Math.max(MIN_TOTAL_STARS, Math.min(MAX_TOTAL_STARS, raw)));
  }

  function buildStars() {
    stars = [];
    const total = computeTotalStars();

    for (const layer of LAYERS) {
      const count = Math.round(total * layer.weight);
      for (let i = 0; i < count; i++) {
        const color = pickStarColor();
        stars.push({
          layer,
          x: Math.random() * viewW,
          y: Math.random() * viewH,
          r: layer.minR + Math.random() * (layer.maxR - layer.minR),
          baseA: layer.minA + Math.random() * (layer.maxA - layer.minA),
          color,
          // Twinkle: slow sine on opacity, randomized phase + speed.
          twPhase: Math.random() * Math.PI * 2,
          twSpeed: 0.3 + Math.random() * 0.6,   // radians/second (slow)
          twAmp: 0.10 + Math.random() * 0.10,   // small amplitude
        });
      }
    }
  }

  function buildPlanets() {
    planets = [];
    // A few planets, scaled gently down on very small screens.
    const small = Math.min(viewW, viewH) < 560;
    const count = small ? 2 : 3 + Math.floor(Math.random() * 2); // 3..4

    // Shuffle colors so each planet differs.
    const colors = PLANET_COLORS.slice().sort(() => Math.random() - 0.5);

    for (let i = 0; i < count; i++) {
      // Slow wander: ~1–3 px/s, so you only notice the drift after a while.
      const speed = 1.2 + Math.random() * 1.8;
      const angle = Math.random() * Math.PI * 2;
      planets.push({
        x: Math.random() * viewW,
        y: Math.random() * viewH,
        r: 1.5 + Math.random() * 1.0,         // bright point, a touch larger than a star
        color: colors[i % colors.length],
        opacity: 0.85 + Math.random() * 0.15, // bright and steady
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed,
      });
    }
  }

  // ----------------------------------------------------------------------
  // Sizing / high-DPI handling.
  // ----------------------------------------------------------------------
  function resize() {
    dpr = window.devicePixelRatio || 1;
    viewW = window.innerWidth;
    viewH = window.innerHeight;

    // Backing store in device pixels; CSS box stays at viewport size.
    canvas.width = Math.round(viewW * dpr);
    canvas.height = Math.round(viewH * dpr);

    // Draw in CSS pixel coordinates.
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    buildStars();
    buildPlanets();
  }

  // ----------------------------------------------------------------------
  // Rendering.
  // ----------------------------------------------------------------------

  // Positive modulo helper for vertical wrapping.
  function wrap(value, max) {
    return ((value % max) + max) % max;
  }

  function drawStars(timeSec, animate) {
    for (const s of stars) {
      // Parallax: shift the whole layer by scroll * factor, then wrap so
      // the field tiles seamlessly and never shows gaps.
      const offset = animate ? scrollY * s.layer.scroll : 0;
      const y = wrap(s.y - offset, viewH);

      // Twinkle: gentle sine oscillation around the base opacity.
      let alpha = s.baseA;
      if (animate) {
        alpha = s.baseA + Math.sin(timeSec * s.twSpeed + s.twPhase) * s.twAmp;
        if (alpha < 0.02) alpha = 0.02;
        if (alpha > 1) alpha = 1;
      }

      const c = s.color;
      ctx.beginPath();
      ctx.arc(s.x, y, s.r, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${c.r}, ${c.g}, ${c.b}, ${alpha.toFixed(3)})`;
      ctx.fill();
    }
  }

  function drawPlanet(p) {
    const c = p.color;

    // Faint bloom around the point, so a bright planet reads as a steady star
    // with a little glow rather than a hard dot.
    const glowR = p.r * 4.5;
    const grad = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, glowR);
    grad.addColorStop(0.0, `rgba(${c.r}, ${c.g}, ${c.b}, ${(p.opacity * 0.45).toFixed(3)})`);
    grad.addColorStop(1.0, `rgba(${c.r}, ${c.g}, ${c.b}, 0)`);
    ctx.beginPath();
    ctx.arc(p.x, p.y, glowR, 0, Math.PI * 2);
    ctx.fillStyle = grad;
    ctx.fill();

    // Bright steady core (planets don't twinkle the way stars do).
    ctx.beginPath();
    ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
    ctx.fillStyle = `rgba(${c.r}, ${c.g}, ${c.b}, ${p.opacity.toFixed(3)})`;
    ctx.fill();
  }

  function render(timeSec, animate) {
    ctx.clearRect(0, 0, viewW, viewH);
    // Stars first (behind), then planets (in front but still subtle).
    drawStars(timeSec, animate);
    for (const p of planets) drawPlanet(p);
  }

  // ----------------------------------------------------------------------
  // Animation loop (delta-time, frame-rate independent).
  // ----------------------------------------------------------------------
  function frame(ts) {
    if (!running) return;

    if (!lastTs) lastTs = ts;
    const dt = Math.min((ts - lastTs) / 1000, 0.1); // seconds, clamped
    lastTs = ts;
    const timeSec = ts / 1000;

    // Drift planets, wrapping around edges with a radius margin so they
    // ease off and back on rather than popping.
    for (const p of planets) {
      p.x += p.vx * dt;
      p.y += p.vy * dt;
      const m = p.r;
      if (p.x < -m) p.x = viewW + m;
      else if (p.x > viewW + m) p.x = -m;
      if (p.y < -m) p.y = viewH + m;
      else if (p.y > viewH + m) p.y = -m;
    }

    render(timeSec, true);
    rafId = window.requestAnimationFrame(frame);
  }

  function start() {
    if (running || reducedMotionMQ.matches) return;
    running = true;
    lastTs = 0;
    rafId = window.requestAnimationFrame(frame);
  }

  function stop() {
    running = false;
    if (rafId !== null) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
  }

  // ----------------------------------------------------------------------
  // Static render for reduced-motion (one frame, no twinkle/drift/scroll).
  // ----------------------------------------------------------------------
  function renderStatic() {
    render(0, false);
  }

  // ----------------------------------------------------------------------
  // Events.
  // ----------------------------------------------------------------------

  // Debounced resize: rebuild the field for the new size.
  let resizeTimer = null;
  function onResize() {
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () {
      resize();
      if (reducedMotionMQ.matches) {
        renderStatic();
      }
      // If animating, the running loop picks up the new field automatically.
    }, 150);
  }

  function onScroll() {
    scrollY = window.scrollY || 0;
  }

  // Pause when the tab is hidden; resume when visible (saves CPU).
  function onVisibility() {
    if (reducedMotionMQ.matches) return;
    if (document.hidden) {
      stop();
    } else {
      start();
    }
  }

  // React to changes in the reduced-motion preference at runtime.
  function onReducedMotionChange() {
    if (reducedMotionMQ.matches) {
      stop();
      renderStatic();
    } else {
      start();
    }
  }

  // ----------------------------------------------------------------------
  // Init.
  // ----------------------------------------------------------------------
  function init() {
    resize();

    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onScroll, { passive: true });
    document.addEventListener('visibilitychange', onVisibility);

    // addEventListener on MediaQueryList (older Safari uses addListener).
    if (typeof reducedMotionMQ.addEventListener === 'function') {
      reducedMotionMQ.addEventListener('change', onReducedMotionChange);
    } else if (typeof reducedMotionMQ.addListener === 'function') {
      reducedMotionMQ.addListener(onReducedMotionChange);
    }

    if (reducedMotionMQ.matches) {
      renderStatic(); // single static frame, no loop
    } else {
      start();
    }
  }

  // Kick off once the DOM is ready enough to have measurements.
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
