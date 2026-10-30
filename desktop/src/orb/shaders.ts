// GLSL for the orb. Every particle is moved on the GPU; the CPU only updates a few
// uniforms per frame (time, state weights, pointer, audio levels).

// 3D simplex noise by Ian McEwan, Ashima Arts (MIT license),
// https://github.com/ashima/webgl-noise
const SIMPLEX_NOISE = /* glsl */ `
vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 mod289(vec4 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
vec4 permute(vec4 x) { return mod289(((x * 34.0) + 1.0) * x); }
vec4 taylorInvSqrt(vec4 r) { return 1.79284291400159 - 0.85373472095314 * r; }
float snoise(vec3 v) {
  const vec2 C = vec2(1.0 / 6.0, 1.0 / 3.0);
  const vec4 D = vec4(0.0, 0.5, 1.0, 2.0);
  vec3 i = floor(v + dot(v, C.yyy));
  vec3 x0 = v - i + dot(i, C.xxx);
  vec3 g = step(x0.yzx, x0.xyz);
  vec3 l = 1.0 - g;
  vec3 i1 = min(g.xyz, l.zxy);
  vec3 i2 = max(g.xyz, l.zxy);
  vec3 x1 = x0 - i1 + C.xxx;
  vec3 x2 = x0 - i2 + C.yyy;
  vec3 x3 = x0 - D.yyy;
  i = mod289(i);
  vec4 p = permute(permute(permute(
            i.z + vec4(0.0, i1.z, i2.z, 1.0))
          + i.y + vec4(0.0, i1.y, i2.y, 1.0))
          + i.x + vec4(0.0, i1.x, i2.x, 1.0));
  float n_ = 0.142857142857;
  vec3 ns = n_ * D.wyz - D.xzx;
  vec4 j = p - 49.0 * floor(p * ns.z * ns.z);
  vec4 x_ = floor(j * ns.z);
  vec4 y_ = floor(j - 7.0 * x_);
  vec4 x = x_ * ns.x + ns.yyyy;
  vec4 y = y_ * ns.x + ns.yyyy;
  vec4 h = 1.0 - abs(x) - abs(y);
  vec4 b0 = vec4(x.xy, y.xy);
  vec4 b1 = vec4(x.zw, y.zw);
  vec4 s0 = floor(b0) * 2.0 + 1.0;
  vec4 s1 = floor(b1) * 2.0 + 1.0;
  vec4 sh = -step(h, vec4(0.0));
  vec4 a0 = b0.xzyw + s0.xzyw * sh.xxyy;
  vec4 a1 = b1.xzyw + s1.xzyw * sh.zzww;
  vec3 p0 = vec3(a0.xy, h.x);
  vec3 p1 = vec3(a0.zw, h.y);
  vec3 p2 = vec3(a1.xy, h.z);
  vec3 p3 = vec3(a1.zw, h.w);
  vec4 norm = taylorInvSqrt(vec4(dot(p0, p0), dot(p1, p1), dot(p2, p2), dot(p3, p3)));
  p0 *= norm.x; p1 *= norm.y; p2 *= norm.z; p3 *= norm.w;
  vec4 m = max(0.6 - vec4(dot(x0, x0), dot(x1, x1), dot(x2, x2), dot(x3, x3)), 0.0);
  m = m * m;
  return 42.0 * dot(m * m, vec4(dot(p0, x0), dot(p1, x1), dot(p2, x2), dot(p3, x3)));
}
`;

export const ORB_VERTEX = /* glsl */ `
${SIMPLEX_NOISE}
uniform float uTime;
uniform float uMorph;
uniform float uScale;
uniform float uSize;
uniform float uPixelRatio;
uniform float uTurbulence;
uniform float uBreathing;
uniform float uThinking;
uniform float uGathering;
uniform float uSpeaking;
uniform float uListening;
uniform float uHover;
uniform float uBurst;
uniform float uAlert;
uniform float uError;
uniform float uSpeechLevel;
uniform float uMicLevel;
uniform float uGlow;
uniform vec3 uPointer;
uniform vec3 uColorA;
uniform vec3 uColorB;
uniform vec3 uColorThinking;
uniform vec3 uColorGathering;
uniform vec3 uColorSpeaking;
uniform vec3 uColorListening;

attribute vec3 aTarget;
attribute vec4 aRandom;

varying vec3 vColor;
varying float vAlpha;

vec3 rotateY(vec3 p, float a) {
  float c = cos(a), s = sin(a);
  return vec3(c * p.x + s * p.z, p.y, -s * p.x + c * p.z);
}

void main() {
  float t = uTime;
  // Morph from the previous shape (position) to the current one (aTarget).
  float m = smoothstep(0.0, 1.0, clamp(uMorph * 1.25 - aRandom.x * 0.25, 0.0, 1.0));
  vec3 p = mix(position, aTarget, m);
  float r = length(p);
  float alpha = 1.0;

  // Idle breathing.
  p *= 1.0 + (sin(t * 0.8) * 0.025 + sin(t * 1.7 + aRandom.x * 6.2831) * 0.008) * uBreathing;

  // Organic motion: simplex noise, faster and stronger while thinking.
  float nt = t * (0.18 + uThinking * 0.5);
  vec3 n = vec3(
    snoise(p * 1.7 + vec3(nt, 0.0, 0.0)),
    snoise(p * 1.7 + vec3(0.0, nt, 7.1)),
    snoise(p * 1.7 + vec3(3.7, 0.0, nt))
  );
  p += n * 0.055 * uTurbulence * (1.0 + uThinking * 1.6 + uListening * 0.8);

  // Thinking: bounded twist (inner layers turn more) and a slight contraction.
  p = rotateY(p, uThinking * 1.3 * (1.3 - r * 0.8));
  p *= 1.0 - 0.09 * uThinking;
  p.y += sin(t * 2.4 + r * 6.0) * 0.02 * uThinking;

  // Gathering: a share of the particles stream in from far away, like data arriving.
  float share = uGathering * 0.5;
  if (aRandom.w < share) {
    float phase = fract(t * 0.32 + aRandom.z);
    float far = 1.0 + pow(1.0 - phase, 2.2) * 2.6;
    p *= mix(1.0, far, min(uGathering * 1.5, 1.0));
    alpha *= mix(1.0, smoothstep(0.0, 0.3, phase), uGathering);
  }

  // Speaking: rings travel outward; the voice level pushes them further.
  float wave = sin(r * 11.0 - t * 7.0) * 0.5 + 0.5;
  p *= 1.0 + uSpeaking * (0.035 * wave + uSpeechLevel * 0.16 * (0.4 + aRandom.y));

  // Listening: the microphone level makes the surface tremble.
  p *= 1.0 + uListening * (0.03 + uMicLevel * 0.42 * (0.25 + abs(n.x)));

  // Click burst: particles fly out, then settle back.
  p *= 1.0 + uBurst * (0.5 + aRandom.y * 1.3);

  vec4 world = modelMatrix * vec4(p * uScale, 1.0);

  // Hover: particles near the pointer move away and glow.
  vec2 d = world.xy - uPointer.xy;
  float dist = length(d);
  float near = exp(-dist * dist * 9.0) * uHover;
  world.xy += normalize(d + 1e-4) * near * 0.28;
  world.z += near * 0.18;
  world.xyz *= 1.0 + uHover * 0.012 * sin(r * 16.0 - t * 5.0);

  vec4 mv = viewMatrix * world;
  gl_Position = projectionMatrix * mv;
  float size = uSize * (0.55 + aRandom.x * 0.9) * (1.0 + near * 1.6 + uBurst * 0.5);
  // Clamp the depth so burst particles that fly toward the camera never become huge blobs.
  gl_PointSize = min(size * uPixelRatio * (9.0 / max(-mv.z, 1.0)), 48.0);

  // Color: gradient between the two base colors, tinted by each state.
  vec3 color = mix(uColorA, uColorB, smoothstep(-0.9, 0.9, p.y / max(uScale, 0.01) + (aRandom.z - 0.5) * 0.9));
  color = mix(color, uColorThinking, uThinking * (0.45 + 0.4 * sin(aRandom.x * 30.0 + t * 3.0)));
  if (aRandom.w < share) color = mix(color, uColorGathering, min(uGathering * 1.4, 1.0));
  color = mix(color, uColorSpeaking, uSpeaking * wave * 0.7);
  color = mix(color, uColorListening, uListening * (0.4 + uMicLevel * 0.6));
  color = mix(color, vec3(1.0, 0.72, 0.25), uAlert * (0.55 + 0.35 * sin(t * 4.0)));
  color = mix(color, vec3(1.0, 0.25, 0.3), uError * (0.6 + 0.4 * step(0.5, fract(t * 6.0 + aRandom.y))));
  color += near * 0.7;

  vColor = color;
  vAlpha = alpha * (0.3 + 0.7 * aRandom.y) * (0.55 + uGlow * 0.55);
}
`;

export const ORB_FRAGMENT = /* glsl */ `
uniform float uGlow;
varying vec3 vColor;
varying float vAlpha;

void main() {
  float d = length(gl_PointCoord - 0.5);
  if (d > 0.5) discard;
  float core = smoothstep(0.5, 0.0, d);
  float a = pow(core, 1.8 - uGlow * 0.9) * vAlpha;
  gl_FragColor = vec4(vColor * (0.75 + uGlow * 0.7), a);
}
`;

// Soft halo behind the orb; brighter when the assistant is busy or speaking.
export const HALO_VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

export const HALO_FRAGMENT = /* glsl */ `
uniform vec3 uColor;
uniform float uIntensity;
uniform float uTime;
varying vec2 vUv;
void main() {
  float d = length(vUv - 0.5) * 2.0;
  float glow = pow(max(1.0 - d, 0.0), 2.6);
  float ring = exp(-pow((d - 0.55) * 7.0, 2.0)) * 0.12 * (0.6 + 0.4 * sin(uTime * 0.7));
  gl_FragColor = vec4(uColor, (glow * 0.55 + ring) * uIntensity);
}
`;

// Background dust: tiny, slow particles that give depth.
export const DUST_VERTEX = /* glsl */ `
uniform float uTime;
uniform float uPixelRatio;
attribute float aSeed;
varying float vAlpha;
void main() {
  vec3 p = position;
  p.y += mod(uTime * 0.03 * (0.5 + aSeed) + aSeed * 10.0, 8.0) - 4.0;
  p.x += sin(uTime * 0.1 + aSeed * 20.0) * 0.15;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = (0.8 + aSeed * 1.4) * uPixelRatio * (6.0 / -mv.z);
  vAlpha = 0.12 + 0.25 * aSeed;
}
`;

export const DUST_FRAGMENT = /* glsl */ `
uniform vec3 uColor;
varying float vAlpha;
void main() {
  float d = length(gl_PointCoord - 0.5);
  if (d > 0.5) discard;
  gl_FragColor = vec4(uColor, smoothstep(0.5, 0.0, d) * vAlpha);
}
`;
