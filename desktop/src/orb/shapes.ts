// Point clouds for each orb shape. Every shape returns `count` xyz positions in roughly
// the unit sphere, so the orb can morph between any two shapes point by point.

export type ShapeId = "sphere" | "torus" | "cube" | "galaxy" | "helix" | "cloud";

export const SHAPES: { id: ShapeId; label: string }[] = [
  { id: "sphere", label: "Esfera" },
  { id: "torus", label: "Anillo" },
  { id: "cube", label: "Cubo" },
  { id: "galaxy", label: "Galaxia" },
  { id: "helix", label: "Hélice" },
  { id: "cloud", label: "Nube" },
];

// Deterministic random numbers, so a shape always looks the same for a given count.
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(rand: () => number): number {
  const u = Math.max(rand(), 1e-6);
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * rand());
}

function randomDirection(rand: () => number): [number, number, number] {
  const z = rand() * 2 - 1;
  const phi = rand() * Math.PI * 2;
  const r = Math.sqrt(1 - z * z);
  return [r * Math.cos(phi), z, r * Math.sin(phi)];
}

type PointFn = (rand: () => number, i: number, count: number) => [number, number, number];

const GENERATORS: Record<ShapeId, PointFn> = {
  // Dense shell with a soft inner volume: reads as a "bubble".
  sphere: (rand) => {
    const [x, y, z] = randomDirection(rand);
    const r = 1 - Math.pow(rand(), 4) * 0.45;
    return [x * r, y * r, z * r];
  },
  torus: (rand) => {
    const u = rand() * Math.PI * 2;
    const v = rand() * Math.PI * 2;
    const tube = 0.32 * Math.sqrt(rand());
    const ring = 0.78 + tube * Math.cos(v);
    // Tilted toward the viewer so the hole is visible.
    const x = ring * Math.cos(u);
    const y = tube * Math.sin(v);
    const z = ring * Math.sin(u);
    const tilt = 1.05;
    return [x, y * Math.cos(tilt) - z * Math.sin(tilt), y * Math.sin(tilt) + z * Math.cos(tilt)];
  },
  // Points on the faces of a cube, slightly rounded.
  cube: (rand) => {
    const s = 0.72;
    const face = Math.floor(rand() * 6);
    const a = (rand() * 2 - 1) * s;
    const b = (rand() * 2 - 1) * s;
    const sign = face % 2 === 0 ? 1 : -1;
    const depth = s * (1 - Math.pow(rand(), 6) * 0.25) * sign;
    if (face < 2) return [depth, a, b];
    if (face < 4) return [a, depth, b];
    return [a, b, depth];
  },
  // Three spiral arms around a bright core.
  galaxy: (rand, i) => {
    const arms = 3;
    const arm = i % arms;
    const t = Math.pow(rand(), 0.7);
    const radius = 0.08 + t * 1.05;
    const angle = (arm / arms) * Math.PI * 2 + t * 5.2 + gaussian(rand) * 0.18 * (1 - t * 0.5);
    const y = gaussian(rand) * 0.06 * (1 - t);
    const x = Math.cos(angle) * radius;
    const z = Math.sin(angle) * radius;
    const tilt = 1.0;
    return [x, y * Math.cos(tilt) - z * Math.sin(tilt), y * Math.sin(tilt) + z * Math.cos(tilt)];
  },
  // Double helix along the vertical axis, with rungs.
  helix: (rand, i) => {
    const t = rand();
    const y = (t * 2 - 1) * 1.05;
    const angle = t * Math.PI * 6;
    const strand = i % 5;
    if (strand === 4) {
      // Rung between both strands.
      const k = rand() * 2 - 1;
      return [Math.cos(angle) * 0.45 * k, y, Math.sin(angle) * 0.45 * k];
    }
    const offset = strand % 2 === 0 ? 0 : Math.PI;
    const jitter = 0.05;
    return [
      Math.cos(angle + offset) * 0.45 + gaussian(rand) * jitter,
      y + gaussian(rand) * jitter,
      Math.sin(angle + offset) * 0.45 + gaussian(rand) * jitter,
    ];
  },
  // Soft gaussian nebula.
  cloud: (rand) => {
    const s = 0.42;
    return [gaussian(rand) * s, gaussian(rand) * s * 0.85, gaussian(rand) * s];
  },
};

export function generateShape(shape: ShapeId, count: number): Float32Array {
  const rand = mulberry32(1337 + shape.length * 97);
  const positions = new Float32Array(count * 3);
  const generate = GENERATORS[shape];
  for (let i = 0; i < count; i++) {
    const [x, y, z] = generate(rand, i, count);
    positions[i * 3] = x;
    positions[i * 3 + 1] = y;
    positions[i * 3 + 2] = z;
  }
  return positions;
}
