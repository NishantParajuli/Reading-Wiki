/* ============================================================
   TideCanvas — the living water behind every shell screen.

   A domain-warped fbm field reads as slow aurora over deep water; thin
   caustic filaments drift through it; a faint moon-glow follows the pointer.
   Colours come from the book in focus (atmosphere store) or the accent hue.

   Budget: rendered at ~1/3 device resolution (the upscale *is* the blur),
   capped at 30fps, paused when hidden, a single still frame under reduced
   motion or the "still" ambient setting. Falls back to CSS gradients when
   WebGL is unavailable.
   ============================================================ */
import React, { useEffect, useRef, useState } from "react";
import { getAtmosphere, subscribeAtmosphere } from "./store.js";
import { oklchToSrgb } from "./color.js";

const VERT = `
attribute vec2 aPos;
varying vec2 vUv;
void main() { vUv = aPos * 0.5 + 0.5; gl_Position = vec4(aPos, 0.0, 1.0); }
`;

const FRAG = `
precision highp float;
varying vec2 vUv;
uniform vec2 uRes;
uniform float uTime;
uniform vec3 uBg;
uniform vec3 uA;
uniform vec3 uB;
uniform vec3 uC;
uniform vec2 uPointer;
uniform float uLight;
uniform float uIntensity;
uniform float uNight;

vec2 hash2(vec2 p) {
  p = vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)));
  return -1.0 + 2.0 * fract(sin(p) * 43758.5453123);
}
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(dot(hash2(i), f), dot(hash2(i + vec2(1.0, 0.0)), f - vec2(1.0, 0.0)), u.x),
             mix(dot(hash2(i + vec2(0.0, 1.0)), f - vec2(0.0, 1.0)), dot(hash2(i + vec2(1.0, 1.0)), f - vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  mat2 m = mat2(1.6, 1.2, -1.2, 1.6);
  for (int i = 0; i < 5; i++) { v += a * noise(p); p = m * p; a *= 0.5; }
  return v;
}

/* Soft, sparse stars that twinkle slowly — only at night, above the water. */
float stars(vec2 p, float t) {
  vec2 cell = floor(p * 46.0);
  vec2 f = fract(p * 46.0);
  float h = fract(sin(dot(cell, vec2(41.3, 289.1))) * 43758.5453);
  if (h < 0.955) return 0.0;
  vec2 c = vec2(fract(h * 13.7), fract(h * 7.3)) * 0.6 + 0.2;
  float d = length(f - c);
  float twinkle = 0.55 + 0.45 * sin(t * (0.6 + h * 1.8) + h * 40.0);
  return smoothstep(0.2, 0.0, d) * twinkle * (0.5 + h * 0.5);
}

void main() {
  vec2 uv = vUv;
  float aspect = uRes.x / uRes.y;
  vec2 p = vec2(uv.x * aspect, uv.y);
  float t = uTime * 0.03;

  vec2 q = vec2(fbm(p * 1.05 + vec2(0.0, t)), fbm(p * 1.05 + vec2(5.2, -t * 0.8)));
  vec2 r = vec2(fbm(p * 1.25 + 2.1 * q + vec2(1.7, 9.2) + t * 0.55),
                fbm(p * 1.25 + 2.1 * q + vec2(8.3, 2.8) - t * 0.45));
  float f = fbm(p * 1.15 + 2.0 * r);

  // Light pools toward the top of the room, like moonlight on the surface.
  float sky = smoothstep(-0.05, 1.05, uv.y);
  float aurora = smoothstep(-0.25, 0.55, f) * mix(0.35, 1.0, sky);
  vec3 col = uBg;
  col = mix(col, uA, clamp(aurora * 0.85, 0.0, 1.0) * uIntensity);
  col = mix(col, uB, clamp(length(q) * 0.9 - 0.15, 0.0, 1.0) * 0.5 * uIntensity);

  // Caustic filaments: thin bright seams in the warped field.
  float seam = abs(sin((r.x * 1.3 + r.y) * 8.5 + uTime * 0.18));
  float caustic = pow(1.0 - seam, 30.0) * smoothstep(0.15, 0.95, sky);
  col += uC * caustic * 0.1 * uIntensity;

  // Stars above the waterline at night, fading where the aurora is bright.
  float starMask = smoothstep(0.42, 0.95, uv.y) * (1.0 - clamp(aurora * 0.9, 0.0, 1.0));
  col += vec3(0.92, 0.95, 1.0) * stars(p, uTime) * starMask * uNight * 0.55;

  // Moon-glow under the pointer.
  float d = distance(p, vec2(uPointer.x * aspect, uPointer.y));
  col += mix(uA, uC, 0.5) * exp(-d * d * 5.0) * 0.07 * uIntensity;

  // Vignette toward the room's edges.
  float vig = smoothstep(1.35, 0.2, length((uv - vec2(0.5, 0.62)) * vec2(aspect * 0.72, 1.05)));
  col = mix(uBg * mix(0.8, 0.985, uLight), col, mix(0.45, 1.0, vig));

  // Dither to kill banding in the slow gradients.
  col += (fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) / 180.0;
  gl_FragColor = vec4(col, 1.0);
}
`;

function readAccentHue() {
  const raw = getComputedStyle(document.documentElement).getPropertyValue("--accent-h");
  const value = parseFloat(raw);
  return Number.isFinite(value) ? value : 192;
}

/* How much night sky shows: full after dark, half at dusk/dawn, none by day. */
function nightFactor(date = new Date()) {
  const h = date.getHours() + date.getMinutes() / 60;
  if (h >= 21 || h < 5) return 1;
  if (h >= 18.5) return (h - 18.5) / 2.5;
  if (h < 7) return 1 - (h - 5) / 2;
  return 0;
}

function targetColors() {
  const light = document.documentElement.getAttribute("data-theme") === "light";
  const { palette } = getAtmosphere();
  const accent = readAccentHue();
  const h1 = palette ? palette.h1 : accent;
  const h2 = palette ? palette.h2 : accent + 70;
  const c = palette ? palette.chroma : 0.1;
  if (light) {
    return {
      light: 1,
      bg: oklchToSrgb(0.978, 0.006, 88),
      a: oklchToSrgb(0.885, Math.min(0.09, c * 0.62), h1),
      b: oklchToSrgb(0.9, Math.min(0.08, c * 0.55), h2),
      c: oklchToSrgb(0.985, 0.03, h1 + 20),
      intensity: 0.9,
      night: 0,
    };
  }
  return {
    light: 0,
    bg: oklchToSrgb(0.155, 0.028, 262),
    a: oklchToSrgb(0.4, Math.min(0.14, c * 1.05), h1),
    b: oklchToSrgb(0.27, Math.min(0.12, c * 0.95), h2),
    c: oklchToSrgb(0.8, 0.09, h1 + 18),
    intensity: 1,
    night: nightFactor(),
  };
}

function readAmbientMode() {
  try { return localStorage.getItem("nw-ambient") || "living"; } catch { return "living"; }
}

function compile(gl, type, source) {
  const shader = gl.createShader(type);
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const info = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(info || "shader compile failed");
  }
  return shader;
}

export function TideCanvas({ className = "" }) {
  const canvasRef = useRef(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    let gl;
    try {
      gl = canvas.getContext("webgl", { antialias: false, alpha: false, depth: false, stencil: false, powerPreference: "low-power", preserveDrawingBuffer: false });
    } catch { gl = null; }
    if (!gl) { setFailed(true); return undefined; }

    let program;
    try {
      program = gl.createProgram();
      gl.attachShader(program, compile(gl, gl.VERTEX_SHADER, VERT));
      gl.attachShader(program, compile(gl, gl.FRAGMENT_SHADER, FRAG));
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("link failed");
    } catch {
      setFailed(true);
      return undefined;
    }
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(program, "aPos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const u = (name) => gl.getUniformLocation(program, name);
    const uni = {
      res: u("uRes"), time: u("uTime"), bg: u("uBg"), a: u("uA"), b: u("uB"), c: u("uC"),
      pointer: u("uPointer"), light: u("uLight"), intensity: u("uIntensity"), night: u("uNight"),
    };

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const coarse = window.matchMedia("(pointer: coarse)");
    let target = targetColors();
    let current = JSON.parse(JSON.stringify(target));
    let pointer = [0.5, 0.75];
    let pointerTarget = [0.5, 0.75];
    let raf = 0;
    let last = 0;
    let time = 12 + Math.random() * 40;
    let still = reduced.matches || readAmbientMode() !== "living";
    let lost = false;

    const resize = () => {
      const scale = coarse.matches ? 0.28 : 0.36;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = Math.max(2, Math.round(window.innerWidth * dpr * scale));
      const h = Math.max(2, Math.round(window.innerHeight * dpr * scale));
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w; canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
    };

    const lerp = (a, b, k) => a + (b - a) * k;
    const mix3 = (a, b, k) => [lerp(a[0], b[0], k), lerp(a[1], b[1], k), lerp(a[2], b[2], k)];

    const draw = () => {
      gl.uniform2f(uni.res, canvas.width, canvas.height);
      gl.uniform1f(uni.time, time);
      gl.uniform3fv(uni.bg, current.bg);
      gl.uniform3fv(uni.a, current.a);
      gl.uniform3fv(uni.b, current.b);
      gl.uniform3fv(uni.c, current.c);
      gl.uniform2f(uni.pointer, pointer[0], pointer[1]);
      gl.uniform1f(uni.light, current.light);
      gl.uniform1f(uni.intensity, current.intensity);
      gl.uniform1f(uni.night, current.night);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
    };

    const settle = (k) => {
      current = {
        light: lerp(current.light, target.light, k),
        intensity: lerp(current.intensity, target.intensity, k),
        night: lerp(current.night, target.night, k),
        bg: mix3(current.bg, target.bg, k),
        a: mix3(current.a, target.a, k),
        b: mix3(current.b, target.b, k),
        c: mix3(current.c, target.c, k),
      };
      pointer = [lerp(pointer[0], pointerTarget[0], k * 1.4), lerp(pointer[1], pointerTarget[1], k * 1.4)];
    };

    const loop = (now) => {
      raf = requestAnimationFrame(loop);
      if (now - last < 33) return; // ~30fps is plenty for slow water
      const dt = last ? Math.min(0.1, (now - last) / 1000) : 0.033;
      last = now;
      time += dt;
      settle(Math.min(1, dt * 2.2));
      draw();
    };

    const start = () => {
      cancelAnimationFrame(raf);
      resize();
      if (lost) return;
      if (still || document.hidden) {
        // Converge colours instantly and paint one calm frame.
        current = JSON.parse(JSON.stringify(target));
        pointer = pointerTarget.slice();
        draw();
        return;
      }
      last = 0;
      raf = requestAnimationFrame(loop);
    };

    const refreshTarget = () => {
      target = targetColors();
      if (still || document.hidden) { current = JSON.parse(JSON.stringify(target)); draw(); }
    };

    const onPointer = (e) => {
      pointerTarget = [e.clientX / window.innerWidth, 1 - e.clientY / window.innerHeight];
    };
    const onVisibility = () => start();
    const onResize = () => { resize(); if (still) draw(); };
    const onAmbient = () => { still = reduced.matches || readAmbientMode() !== "living"; start(); };
    // A lost context (GPU reset, too many contexts) falls back to CSS gradients.
    const onLost = (e) => { e.preventDefault(); lost = true; cancelAnimationFrame(raf); setFailed(true); };

    const observer = new MutationObserver(refreshTarget);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "style"] });
    const unsubscribe = subscribeAtmosphere(refreshTarget);
    window.addEventListener("pointermove", onPointer, { passive: true });
    window.addEventListener("resize", onResize);
    window.addEventListener("tg-ambient-change", onAmbient);
    document.addEventListener("visibilitychange", onVisibility);
    reduced.addEventListener?.("change", onAmbient);
    canvas.addEventListener("webglcontextlost", onLost);
    start();
    canvas.dataset.ready = "true";

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
      unsubscribe();
      window.removeEventListener("pointermove", onPointer);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("tg-ambient-change", onAmbient);
      document.removeEventListener("visibilitychange", onVisibility);
      reduced.removeEventListener?.("change", onAmbient);
      canvas.removeEventListener("webglcontextlost", onLost);
      const ext = gl.getExtension("WEBGL_lose_context");
      if (ext) ext.loseContext();
    };
  }, []);

  if (failed) return <div className={["ambient-fallback", className].filter(Boolean).join(" ")} aria-hidden="true" />;
  return <canvas ref={canvasRef} className={["ambient-canvas", className].filter(Boolean).join(" ")} aria-hidden="true" />;
}
