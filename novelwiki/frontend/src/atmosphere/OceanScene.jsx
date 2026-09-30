/* ============================================================
   OceanScene — a real-time moonlit sea (dawn in Pearl), in raw WebGL.

   Night: a deep sky with twinkling stars, a luminous moon with a halo, a
   sea in perspective built from a sum of directional swells, and the moon
   path — the "tide glass": a statistical glitter lobe that stays smooth
   toward the horizon and breaks into sparkling glints near the viewer.
   Low mist drifts over the horizon, and the camera sways with the pointer
   so the near water slides past a still sky (parallax).
   Dawn: a pale gold/rose sky, a silver-blue sea and a low sun with a
   golden path. Glows, mist and water tint follow --accent-h.

   Layout owns the geometry through custom properties on the host element:
     --ocean-horizon            horizon, as a fraction of the height from the top
     --ocean-moon-x/-y/-r       moon centre (fractions of width/height) + radius
     --ocean-sun-x/-y/-r        the same for the dawn sun
   so a media query can move the horizon and the DOM can stand on it.

   Budget: a pixel budget (~0.64MP fine pointers, ~0.32MP touch) upscaled
   by the compositor (the upscale softens), capped at 36fps, paused while
   the tab is hidden or the sea is scrolled away, a single still frame
   under prefers-reduced-motion, a CSS gradient when WebGL is unavailable
   or the context is lost, and the context is released on unmount.
   ============================================================ */
import React, { useEffect, useRef, useState } from "react";
import { oklchToLinear } from "./color.js";

const VERT = `
attribute vec2 aPos;
void main() { gl_Position = vec4(aPos, 0.0, 1.0); }
`;

const FRAG = `
precision highp float;

uniform vec2 uRes;
uniform float uTime;
uniform float uHorizon;   // horizon height from the bottom (0..1)
uniform vec2 uLight;      // moon/sun centre: x from the left, y from the bottom (0..1)
uniform float uLightR;    // disc radius as a fraction of the height
uniform vec2 uCam;        // camera offset (parallax), metres
uniform float uWake;      // entrance 0..1
uniform float uNight;     // 1 moonlit night, 0 dawn
uniform float uGlare;     // glitter gain
uniform float uDisc;      // disc brightness
uniform float uVignette;  // edge darkening
uniform float uPx;        // canvas pixels per CSS pixel (points keep their CSS size)
uniform vec3 uSkyTop;
uniform vec3 uSkyMid;
uniform vec3 uSkyLow;
uniform vec3 uHalo;
uniform vec3 uLightCol;
uniform vec3 uDeep;
uniform vec3 uShallow;
uniform vec3 uMist;
uniform vec3 uGlint;

const float FOCAL = 1.45;

float hash12(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
vec2 hash22(vec2 p) {
  vec3 p3 = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973));
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.xx + p3.yz) * p3.zy);
}
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  float a = hash12(i);
  float b = hash12(i + vec2(1.0, 0.0));
  float c = hash12(i + vec2(0.0, 1.0));
  float d = hash12(i + vec2(1.0, 1.0));
  return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0;
  float a = 0.5;
  for (int i = 0; i < 4; i++) {
    v += a * vnoise(p);
    p = p * 2.03 + vec2(1.7, 9.2);
    a *= 0.5;
  }
  return v;
}

/* Sky radiance in direction d (camera space, y up), with the light's halo. */
vec3 skyColor(vec3 d, vec3 ld) {
  float e = max(d.y, 0.0);
  vec3 c = mix(uSkyLow, uSkyMid, smoothstep(0.0, 0.2, e));
  c = mix(c, uSkyTop, smoothstep(0.12, 0.62, e));
  float a = sqrt(max(2.0 - 2.0 * dot(d, ld), 0.0));
  float glow = exp(-a * 70.0) * 0.55 + exp(-a * 18.0) * 0.85 + exp(-a * 6.0) * 0.3 + exp(-a * 3.2) * 0.045;
  c += uHalo * glow * (0.3 + 0.7 * uWake);
  float az = exp(-abs(d.x / max(d.z, 0.05) - ld.x / max(ld.z, 0.05)) * 1.6);
  c += uHalo * exp(-e * 30.0) * (0.05 + 0.3 * az);
  return c;
}

float starLayer(vec2 p, float scale, float density, float seed) {
  vec2 sp = p * scale + seed;
  vec2 ci = floor(sp);
  vec2 cf = fract(sp);
  float h = hash12(ci);
  if (h > density) return 0.0;
  vec2 pos = 0.18 + 0.64 * hash22(ci + 11.3);
  float mag = hash12(ci + 5.1);
  mag = mag * mag * mag;
  vec2 dp = (cf - pos) * (uRes.y / scale);
  // radius in CSS px, drawn in canvas px; sub-pixel stars fade by area instead
  float rad = (0.72 + 1.3 * mag) * uPx;
  float energy = min(1.0, rad * rad / 0.4);
  rad = max(rad, 0.62);
  float s = exp(-dot(dp, dp) / (rad * rad)) * energy;
  float tw = 0.55 + 0.45 * sin(uTime * (0.6 + 2.4 * hash12(ci + 2.9)) + h * 61.0);
  float order = h / density;
  float appear = smoothstep(order * 0.8, order * 0.8 + 0.2, uWake);
  return s * (0.08 + 1.25 * mag) * tw * appear;
}

void wave(vec2 xz, vec2 d, float L, float A, float ph, float T, float fl, float fd,
          inout vec2 g, inout float v, inout float hh) {
  float k = 6.2831853 / L;
  float w = sqrt(9.81 * k);
  float fp = length(vec2(d.x * fl, d.y * fd));
  float lod = 1.0 - smoothstep(0.1, 0.45, fp / L);
  float s = k * dot(d, xz) - w * T + ph;
  float ak = A * k;
  g += lod * ak * cos(s) * d;
  hh += lod * A * sin(s);
  v += (1.0 - lod * lod) * 0.5 * ak * ak;
}

float glints(vec2 xz, vec2 cs, float spread, vec2 greq, vec2 g, float fl, float fd, float seed) {
  vec2 cu = xz / cs + seed;
  vec2 ci = floor(cu);
  vec2 cf = fract(cu);
  float cellPx = min(cs.x / fl, cs.y / fd);
  float vis = smoothstep(3.5, 8.0, cellPx);
  if (vis <= 0.0) return 0.0;
  float h = hash12(ci);
  float tt = uTime * (0.8 + 2.3 * h) + h * 23.0;
  float ep = floor(tt);
  float env = sin(3.14159 * fract(tt));
  vec2 m = (hash22(ci + ep * 17.13) - 0.5) * spread;
  vec2 dm = greq - (g + m);
  float match = exp(-dot(dm, dm) / (2.0 * 0.04 * 0.04));
  vec2 off = 0.3 + 0.4 * hash22(ci + vec2(ep, 3.7));
  vec2 dpx = (cf - off) * cs / vec2(fl, fd);
  float dotS = exp(-dot(dpx, dpx) / 1.7) * min(1.0, uPx * uPx / 0.45);
  return match * dotS * env * env * vis;
}

vec3 tone(vec3 c) {
  const float k = 0.8;
  vec3 over = max(c - k, 0.0);
  return min(c, vec3(k)) + (1.0 - k) * (1.0 - exp(-over / (1.0 - k)));
}

void main() {
  vec2 fc = gl_FragCoord.xy;
  float H = uRes.y;
  vec2 p = vec2(fc.x - 0.5 * uRes.x, fc.y - uHorizon * H) / H;
  vec2 lp = vec2((uLight.x - 0.5) * uRes.x / H, uLight.y - uHorizon);
  vec3 rd = normalize(vec3(p, FOCAL));
  vec3 ld = normalize(vec3(lp, FOCAL));
  float px = 1.0 / H;
  vec3 col;

  if (p.y >= 0.0) {
    col = skyColor(rd, ld);
    float nearLight = smoothstep(uLightR * 1.4, uLightR * 6.0, length(p - lp));
    // a faint river of light across the upper sky, dusted with more stars
    vec2 bp = vec2(p.x * 0.94 - p.y * 0.34, p.x * 0.34 + p.y * 0.94);
    float bd = bp.y - 0.44 - 0.05 * sin(bp.x * 2.3);
    float river = exp(-bd * bd / 0.012) * smoothstep(0.05, 0.3, p.y);
    float dust = fbm(bp * vec2(2.2, 5.0) + 11.0);
    col += uHalo * river * smoothstep(0.35, 0.8, dust) * 0.16 * uNight * uWake;
    float stars = starLayer(p, 120.0, 0.16 + 0.3 * river, 3.0) * 0.55 + starLayer(p, 58.0, 0.2, 0.0) + starLayer(p, 23.0, 0.09, 7.0);
    vec3 starCol = mix(vec3(0.72, 0.82, 1.0), vec3(1.0, 0.9, 0.78), hash12(floor(p * 62.0) + 3.3));
    col += starCol * stars * uNight * smoothstep(0.012, 0.2, p.y) * nearLight;
    vec2 q = (p - lp) / uLightR;
    float r = length(q);
    float edge = px / uLightR * 1.2;
    float disc = 1.0 - smoothstep(1.0 - edge, 1.0 + edge, r);
    if (disc > 0.0) {
      // the moon's seas: broad dark maria and a fine speckle of craters
      float m = fbm(q * 0.95 + vec2(4.0, 1.3));
      float crater = vnoise(q * 9.0 + 2.7);
      float maria = (smoothstep(0.4, 0.6, m) * 0.42 + crater * 0.05) * uNight;
      float limb = mix(1.0, 1.0 - 0.26 * r * r * r, uNight);
      vec3 lc = uLightCol * mix(vec3(1.0), vec3(0.62, 0.66, 0.74), maria) * limb * uDisc;
      col = mix(col, lc, disc * smoothstep(0.04, 0.42, uWake));
    }
  } else {
    float camH = 2.3 + uCam.y;
    vec3 ro = vec3(uCam.x, camH, 0.0);
    vec3 rs = rd;
    rs.y = min(rs.y, -0.0015);
    float t = camH / -rs.y;
    vec2 xz = ro.xz + rs.xz * t;
    float pa = 1.0 / (H * FOCAL);
    float fl = t * pa;
    float fd = fl / max(-rs.y, 0.003);
    float T = uTime * 0.6;
    vec2 g = vec2(0.0);
    float v = 0.0;
    float hh = 0.0;
    wave(xz, vec2(0.148, -0.989), 9.5, 0.13, 0.0, T, fl, fd, g, v, hh);
    wave(xz, vec2(-0.447, -0.894), 5.6, 0.075, 1.7, T, fl, fd, g, v, hh);
    wave(xz, vec2(0.625, -0.781), 3.3, 0.046, 4.1, T, fl, fd, g, v, hh);
    wave(xz, vec2(-0.906, -0.423), 2.05, 0.027, 2.3, T, fl, fd, g, v, hh);
    wave(xz, vec2(0.302, -0.953), 1.24, 0.017, 5.2, T, fl, fd, g, v, hh);
    wave(xz, vec2(0.949, -0.316), 0.74, 0.0095, 0.9, T, fl, fd, g, v, hh);
    wave(xz, vec2(-0.6, -0.8), 0.45, 0.0058, 3.3, T, fl, fd, g, v, hh);
    wave(xz, vec2(0.1, -0.995), 0.27, 0.0034, 1.1, T, fl, fd, g, v, hh);
    vec3 n = normalize(vec3(-g.x, 1.0, -g.y));
    vec3 vv = -rs;
    float cv = max(dot(n, vv), 0.0);
    float F = 0.02 + 0.98 * pow(1.0 - cv, 5.0);
    vec3 rr = reflect(rs, n);
    rr.y = abs(rr.y) + 0.001;
    vec3 refl = skyColor(normalize(rr), ld);
    vec3 body = mix(uDeep, uShallow, clamp(hh * 2.6 + 0.3, 0.0, 1.0) * 0.55);
    col = mix(body, refl, F);

    // The moon path: a glitter lobe widened by the waves too fine to resolve.
    vec3 hv = normalize(ld + vv);
    float ch = max(dot(hv, n), 0.001);
    float ch2 = ch * ch;
    float tan2 = (1.0 - ch2) / ch2;
    float sig2 = 0.0034 + v;
    float D = exp(-tan2 / (2.0 * sig2)) / (6.2831853 * sig2 * ch2 * ch2);
    float Fh = 0.02 + 0.98 * pow(1.0 - max(dot(hv, vv), 0.0), 5.0);
    float spec = Fh * D / (4.0 * max(cv, 0.08));
    float u = clamp(-p.y / max(uHorizon, 0.01), 0.0, 1.0);
    float pathWake = smoothstep(0.0, 0.3, uWake * 1.35 - u);
    col += uGlint * spec * uGlare * 0.09 * pathWake;

    // Glints: facets that catch the light for a moment, near and mid water.
    vec2 greq = -hv.xz / max(hv.y, 0.02);
    float sv = sqrt(v);
    float gl = glints(xz, vec2(0.12, 0.36), 0.36, greq, g, fl, fd, 0.0)
             + glints(xz, vec2(0.46, 1.5), 0.36 + sv * 2.0, greq, g, fl, fd, 5.3);
    col += uGlint * gl * uGlare * 2.6 * pathWake;

    float fog = 1.0 - exp(-t * 0.016);
    vec3 fogCol = skyColor(normalize(vec3(rs.x, 0.0004, rs.z)), ld) * mix(0.9, 0.72, uNight);
    col = mix(col, fogCol, fog * 0.92);
  }

  // Low mist drifting over the horizon.
  float ay = abs(p.y);
  if (ay < 0.24) {
    vec2 mp = vec2(p.x * 1.7 + uTime * 0.014 + uCam.x * 0.035, p.y * 7.5);
    float warp = fbm(mp * 0.7 + vec2(uTime * 0.01, 3.1));
    float mn = fbm(mp + warp * 0.9);
    float band = exp(-ay * 15.0);
    float mist = band * smoothstep(0.38, 0.82, mn);
    col = mix(col, uMist, (mist * 0.38 + exp(-ay * 60.0) * 0.14) * (0.35 + 0.65 * uWake));
  }

  vec2 uv = fc / uRes;
  float vig = smoothstep(1.3, 0.3, length((uv - vec2(0.45, 0.56)) * vec2(1.05, 1.25)));
  col *= mix(1.0 - uVignette, 1.0, vig);

  col = pow(tone(max(col, 0.0)), vec3(1.0 / 2.2));
  col += (hash12(fc + fract(uTime) * 71.0) - 0.5) / 255.0;
  gl_FragColor = vec4(col, 1.0);
}
`;

const FPS = 36;
const WAKE_SECONDS = 2.8;
const STILL_TIME = 41.3;

const lin = (L, C, H) => oklchToLinear(L, C, H);

/* Theme palettes (linear sRGB), tinted by the accent hue. */
function palette(dawn, hue) {
  if (dawn) {
    return {
      night: 0, glare: 1.35, disc: 3.2, vignette: 0.06,
      skyTop: lin(0.78, 0.058, 258),
      skyMid: lin(0.86, 0.065, 16),
      skyLow: lin(0.92, 0.095, 70),
      halo: lin(0.78, 0.16, 60).map(v => v * 1.05),
      lightCol: lin(0.995, 0.03, 95),
      deep: lin(0.56, 0.045, hue + 48),
      shallow: lin(0.74, 0.05, hue + 10),
      mist: lin(0.96, 0.025, 80),
      glint: lin(0.98, 0.07, 82),
    };
  }
  return {
    night: 1, glare: 1, disc: 1.12, vignette: 0.34,
    skyTop: lin(0.105, 0.03, 270),
    skyMid: lin(0.165, 0.046, 264),
    skyLow: lin(0.29, 0.056, hue + 50),
    halo: lin(0.8, 0.06, hue + 24).map(v => v * 0.42),
    lightCol: lin(0.975, 0.022, 95),
    deep: lin(0.13, 0.038, hue + 56),
    shallow: lin(0.3, 0.07, hue),
    mist: lin(0.42, 0.04, hue + 42),
    glint: lin(0.96, 0.045, hue - 10),
  };
}

const KEYS = ["skyTop", "skyMid", "skyLow", "halo", "lightCol", "deep", "shallow", "mist", "glint"];
const SCALARS = ["night", "glare", "disc", "vignette"];

function readAccentHue() {
  const value = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--accent-h"));
  return Number.isFinite(value) ? value : 192;
}
const isDawn = () => document.documentElement.getAttribute("data-theme") === "light";

function num(styles, name, fallback) {
  const value = parseFloat(styles.getPropertyValue(name));
  return Number.isFinite(value) ? value : fallback;
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

export function OceanScene({ className = "" }) {
  const glHostRef = useRef(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const host = glHostRef.current;
    if (!host || failed) return undefined;

    // A fresh canvas per mount: a released context can never be reused.
    const canvas = document.createElement("canvas");
    canvas.className = "ocean-canvas";
    let gl = null;
    try {
      gl = canvas.getContext("webgl", {
        antialias: false, alpha: false, depth: false, stencil: false,
        premultipliedAlpha: false, powerPreference: "low-power", preserveDrawingBuffer: false,
      });
    } catch { gl = null; }
    if (!gl) { setFailed(true); return undefined; }

    let program;
    let vs;
    let fs;
    try {
      vs = compile(gl, gl.VERTEX_SHADER, VERT);
      fs = compile(gl, gl.FRAGMENT_SHADER, FRAG);
      program = gl.createProgram();
      gl.attachShader(program, vs);
      gl.attachShader(program, fs);
      gl.linkProgram(program);
      if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw new Error("link failed");
    } catch {
      const ext = gl.getExtension("WEBGL_lose_context");
      if (ext) ext.loseContext();
      setFailed(true);
      return undefined;
    }
    host.appendChild(canvas);
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(program, "aPos");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);

    const uniform = (name) => gl.getUniformLocation(program, name);
    const U = {
      res: uniform("uRes"), time: uniform("uTime"), horizon: uniform("uHorizon"),
      light: uniform("uLight"), lightR: uniform("uLightR"), cam: uniform("uCam"),
      wake: uniform("uWake"), night: uniform("uNight"), glare: uniform("uGlare"),
      disc: uniform("uDisc"), vignette: uniform("uVignette"), px: uniform("uPx"),
      skyTop: uniform("uSkyTop"), skyMid: uniform("uSkyMid"), skyLow: uniform("uSkyLow"),
      halo: uniform("uHalo"), lightCol: uniform("uLightCol"), deep: uniform("uDeep"),
      shallow: uniform("uShallow"), mist: uniform("uMist"), glint: uniform("uGlint"),
    };

    // Software rasterizers (blocklisted GPUs, VMs, remote desktops) get a far
    // lighter budget so the page stays responsive; a still frame keeps full size.
    let software = false;
    try {
      const info = gl.getExtension("WEBGL_debug_renderer_info");
      const renderer = String(gl.getParameter(info ? info.UNMASKED_RENDERER_WEBGL : gl.RENDERER) || "");
      software = /swiftshader|llvmpipe|softpipe|lavapipe|software/i.test(renderer);
    } catch { software = false; }

    const media = (query) => window.matchMedia?.(query) || { matches: false };
    const reduced = media("(prefers-reduced-motion: reduce)");
    const fine = media("(hover: hover) and (pointer: fine)");
    const coarse = media("(pointer: coarse)");
    const layout = { horizon: 0.56, moon: [0.4, 0.2, 0.03], sun: [0.4, 0.46, 0.04] };
    let target = palette(isDawn(), readAccentHue());
    let current = { ...target };
    let still = reduced.matches;
    let inView = true;
    let lost = false;
    let raf = 0;
    let last = 0;
    let time = 12 + Math.random() * 30;
    let wake = still ? 1 : 0;
    let wakeFrom = 0; // wall clock, so a slow GPU never lags the CSS choreography
    let cam = [0, 0];
    let camTarget = [0, 0];
    let painted = false;
    let pxScale = 1;

    const readLayout = () => {
      const cs = getComputedStyle(host);
      layout.horizon = num(cs, "--ocean-horizon", 0.56);
      layout.moon = [num(cs, "--ocean-moon-x", 0.4), num(cs, "--ocean-moon-y", 0.2), num(cs, "--ocean-moon-r", 0.03)];
      layout.sun = [num(cs, "--ocean-sun-x", 0.4), num(cs, "--ocean-sun-y", 0.46), num(cs, "--ocean-sun-r", 0.04)];
    };

    const resize = () => {
      const rect = host.getBoundingClientRect();
      const cssW = Math.max(1, rect.width);
      const cssH = Math.max(1, rect.height);
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const budget = software && !still ? 240000 : coarse.matches ? 320000 : 640000;
      const scale = Math.min(dpr, Math.sqrt(budget / (cssW * cssH)));
      const w = Math.max(2, Math.round(cssW * scale));
      const h = Math.max(2, Math.round(cssH * scale));
      pxScale = w / cssW;
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w;
        canvas.height = h;
        gl.viewport(0, 0, w, h);
      }
      readLayout();
    };

    const draw = () => {
      if (lost) return;
      const k = current.night;
      const mixv = (a, b) => a + (b - a) * k;
      const lx = mixv(layout.sun[0], layout.moon[0]);
      const ly = mixv(layout.sun[1], layout.moon[1]);
      const lr = mixv(layout.sun[2], layout.moon[2]);
      gl.uniform2f(U.res, canvas.width, canvas.height);
      gl.uniform1f(U.time, still ? STILL_TIME : time);
      gl.uniform1f(U.horizon, 1 - layout.horizon);
      gl.uniform2f(U.light, lx, 1 - ly);
      gl.uniform1f(U.lightR, lr);
      gl.uniform2f(U.cam, cam[0], cam[1]);
      gl.uniform1f(U.wake, wake);
      gl.uniform1f(U.px, pxScale);
      for (const key of SCALARS) gl.uniform1f(U[key], current[key]);
      for (const key of KEYS) gl.uniform3fv(U[key], current[key]);
      gl.drawArrays(gl.TRIANGLES, 0, 6);
      if (!painted) { painted = true; canvas.dataset.ready = "true"; }
    };

    const settle = (dt) => {
      const kc = 1 - Math.exp(-dt * 4.5);
      const next = {};
      for (const key of SCALARS) next[key] = current[key] + (target[key] - current[key]) * kc;
      for (const key of KEYS) next[key] = current[key].map((v, i) => v + (target[key][i] - v) * kc);
      current = next;
      const kp = 1 - Math.exp(-dt * 2.2);
      const drift = Math.sin(time * 0.05) * 0.5;
      cam = [cam[0] + (camTarget[0] + drift - cam[0]) * kp, cam[1] + (camTarget[1] - cam[1]) * kp];
    };

    const frameMs = 1000 / (software ? 24 : FPS);
    const loop = (now) => {
      raf = requestAnimationFrame(loop);
      if (last && now - last < frameMs - 2) return;
      const dt = last ? Math.min(0.1, (now - last) / 1000) : 1 / FPS;
      last = now;
      time += dt;
      if (!wakeFrom) wakeFrom = now - wake * WAKE_SECONDS * 1000;
      wake = Math.min(1, (now - wakeFrom) / (WAKE_SECONDS * 1000));
      settle(dt);
      draw();
    };

    const start = () => {
      cancelAnimationFrame(raf);
      if (lost) return;
      resize();
      if (still) {
        current = { ...target };
        wake = 1;
        cam = [0, 0];
        draw();
        return;
      }
      if (document.hidden || !inView) return;
      last = 0;
      wakeFrom = 0;
      raf = requestAnimationFrame(loop);
    };

    const refreshTarget = () => {
      target = palette(isDawn(), readAccentHue());
      readLayout();
      // Under the theme ripple the new frame is revealed at once: jump there.
      if (still || document.documentElement.dataset.vt === "theme" || document.hidden) {
        current = { ...target };
        draw();
      }
    };

    const onPointer = (e) => {
      if (!fine.matches || still) return;
      const x = e.clientX / window.innerWidth - 0.5;
      const y = e.clientY / window.innerHeight - 0.5;
      camTarget = [x * 1.8, -y * 0.5];
    };
    const onVisibility = () => start();
    const onReduced = () => { still = reduced.matches; start(); };
    const onLost = (e) => { e.preventDefault(); lost = true; cancelAnimationFrame(raf); setFailed(true); };

    const ro = typeof ResizeObserver !== "undefined"
      ? new ResizeObserver(() => { resize(); if (still || document.hidden || !inView) draw(); })
      : null;
    ro?.observe(host);
    const io = typeof IntersectionObserver !== "undefined"
      ? new IntersectionObserver(([entry]) => { inView = entry.isIntersecting; start(); })
      : null;
    io?.observe(host);
    const mo = new MutationObserver(refreshTarget);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "style"] });
    window.addEventListener("pointermove", onPointer, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    reduced.addEventListener?.("change", onReduced);
    canvas.addEventListener("webglcontextlost", onLost);
    start();

    return () => {
      cancelAnimationFrame(raf);
      ro?.disconnect();
      io?.disconnect();
      mo.disconnect();
      window.removeEventListener("pointermove", onPointer);
      document.removeEventListener("visibilitychange", onVisibility);
      reduced.removeEventListener?.("change", onReduced);
      canvas.removeEventListener("webglcontextlost", onLost);
      if (!lost) {
        gl.deleteBuffer(buffer);
        gl.deleteProgram(program);
        gl.deleteShader(vs);
        gl.deleteShader(fs);
        const ext = gl.getExtension("WEBGL_lose_context");
        if (ext) ext.loseContext();
      }
      canvas.remove();
    };
  }, [failed]);

  return (
    <div className={["ocean", failed ? "is-fallback" : "", className].filter(Boolean).join(" ")} aria-hidden="true">
      <div className="ocean-fallback" />
      <div className="ocean-gl" ref={glHostRef} />
    </div>
  );
}
