// Three.js scene for the thought orb. Framework-agnostic: React only creates it, feeds it
// settings/state, and disposes it. All animation runs in requestAnimationFrame.

import * as THREE from "three";
import { DUST_FRAGMENT, DUST_VERTEX, HALO_FRAGMENT, HALO_VERTEX, ORB_FRAGMENT, ORB_VERTEX } from "./shaders";
import type { OrbSettings } from "./settings";
import { generateShape } from "./shapes";

export type OrbState = "idle" | "thinking" | "gathering" | "speaking" | "listening" | "alert" | "error";

/** Live audio levels (0–1), written by the voice code and read every frame. */
export interface AudioLevels {
  speech: number;
  mic: number;
}

type Weights = Record<"thinking" | "gathering" | "speaking" | "listening" | "alert" | "error" | "hover", number>;

const DUST_COUNT = 700;
const MORPH_SECONDS = 1.4;
const INTRO_SECONDS = 2.4;

// Exponential smoothing that does not depend on the frame rate.
const approach = (current: number, target: number, rate: number, dt: number) =>
  current + (target - current) * (1 - Math.exp(-rate * dt));

export class OrbEngine {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(42, 1, 0.1, 50);
  private points: THREE.Points<THREE.BufferGeometry, THREE.ShaderMaterial>;
  private halo: THREE.Mesh<THREE.PlaneGeometry, THREE.ShaderMaterial>;
  private dust: THREE.Points<THREE.BufferGeometry, THREE.ShaderMaterial>;
  private raycaster = new THREE.Raycaster();
  private plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
  private pointerNdc = new THREE.Vector2(10, 10);
  private pointerWorld = new THREE.Vector3(10, 10, 0);
  private resizeObserver: ResizeObserver;
  private frame = 0;
  private lastTime = performance.now();
  private time = 0;
  private morph = 1;
  private intro = 0;
  private burst = 0;
  private hovering = false;
  private pointerInside = false;
  private state: OrbState = "idle";
  private weights: Weights = { thinking: 0, gathering: 0, speaking: 0, listening: 0, alert: 0, error: 0, hover: 0 };
  private smoothSpeech = 0;
  private smoothMic = 0;
  private reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  private settings: OrbSettings;

  constructor(
    private container: HTMLElement,
    settings: OrbSettings,
    private levels: AudioLevels,
    private onHoverChange: (hovering: boolean) => void,
  ) {
    this.settings = settings;
    this.renderer = new THREE.WebGLRenderer({ antialias: false, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setClearColor(0x000000, 0);
    container.appendChild(this.renderer.domElement);
    this.camera.position.set(0, 0, 4.2);

    this.points = this.createOrb(settings);
    this.halo = this.createHalo();
    this.dust = this.createDust();
    this.scene.add(this.halo, this.dust, this.points);
    this.applySettings(settings);

    const canvas = this.renderer.domElement;
    canvas.addEventListener("pointermove", this.onPointerMove);
    canvas.addEventListener("pointerleave", this.onPointerLeave);
    canvas.addEventListener("pointerdown", this.onPointerDown);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.frame = requestAnimationFrame(this.tick);
  }

  // ---- public API -------------------------------------------------------------------

  setState(state: OrbState) {
    this.state = state;
  }

  setSettings(next: OrbSettings) {
    const prev = this.settings;
    this.settings = next;
    if (next.particleCount !== prev.particleCount) {
      this.rebuildOrb(next);
    } else if (next.shape !== prev.shape) {
      this.morphTo(next);
    }
    this.applySettings(next);
  }

  /** Trigger the particle burst (also used when the user clicks the orb). */
  pulse() {
    this.burst = Math.max(this.burst, 1);
  }

  dispose() {
    cancelAnimationFrame(this.frame);
    this.resizeObserver.disconnect();
    const canvas = this.renderer.domElement;
    canvas.removeEventListener("pointermove", this.onPointerMove);
    canvas.removeEventListener("pointerleave", this.onPointerLeave);
    canvas.removeEventListener("pointerdown", this.onPointerDown);
    for (const obj of [this.points, this.halo, this.dust]) {
      obj.geometry.dispose();
      obj.material.dispose();
    }
    // Release the WebGL context now (dev reloads and StrictMode remounts would pile them up).
    this.renderer.forceContextLoss();
    this.renderer.dispose();
    canvas.remove();
  }

  // ---- scene construction -----------------------------------------------------------

  private orbGeometry(settings: OrbSettings, from: Float32Array): THREE.BufferGeometry {
    const count = settings.particleCount;
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(from, 3));
    geometry.setAttribute("aTarget", new THREE.BufferAttribute(generateShape(settings.shape, count), 3));
    const random = new Float32Array(count * 4);
    for (let i = 0; i < random.length; i++) random[i] = Math.random();
    geometry.setAttribute("aRandom", new THREE.BufferAttribute(random, 4));
    // Particles move far outside their rest shape (bursts, streams): skip frustum culling.
    geometry.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 10);
    return geometry;
  }

  /** Scattered start positions for the intro: particles assemble when the app opens. */
  private scattered(count: number): Float32Array {
    const out = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 2.5 + Math.random() * 3;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(Math.random() * 2 - 1);
      out[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      out[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      out[i * 3 + 2] = r * Math.cos(phi);
    }
    return out;
  }

  private createOrb(settings: OrbSettings) {
    const uniforms: Record<string, THREE.IUniform> = {};
    for (const name of [
      "uTime", "uMorph", "uScale", "uSize", "uPixelRatio", "uTurbulence", "uBreathing", "uThinking",
      "uGathering", "uSpeaking", "uListening", "uHover", "uBurst", "uAlert", "uError", "uSpeechLevel",
      "uMicLevel", "uGlow",
    ]) {
      uniforms[name] = { value: 0 };
    }
    for (const name of ["uColorA", "uColorB", "uColorThinking", "uColorGathering", "uColorSpeaking", "uColorListening"]) {
      uniforms[name] = { value: new THREE.Color() };
    }
    uniforms.uPointer = { value: new THREE.Vector3(10, 10, 0) };
    const material = new THREE.ShaderMaterial({
      vertexShader: ORB_VERTEX,
      fragmentShader: ORB_FRAGMENT,
      uniforms,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    this.morph = 0;
    this.intro = 0;
    return new THREE.Points(this.orbGeometry(settings, this.scattered(settings.particleCount)), material);
  }

  private rebuildOrb(settings: OrbSettings) {
    const old = this.points.geometry;
    // Keep the transition smooth: start from a soft cloud and morph into the shape.
    this.points.geometry = this.orbGeometry(settings, generateShape("cloud", settings.particleCount));
    old.dispose();
    this.morph = 0;
  }

  private morphTo(settings: OrbSettings) {
    const geometry = this.points.geometry;
    const current = geometry.getAttribute("aTarget") as THREE.BufferAttribute;
    const previous = geometry.getAttribute("position") as THREE.BufferAttribute;
    // If a morph is still running, start from where each particle is now. This mirrors the
    // shader's staggered per-particle easing, so changing shape mid-morph never jumps.
    const start = new Float32Array(current.array as Float32Array);
    if (this.morph < 1) {
      const from = previous.array as Float32Array;
      const random = (geometry.getAttribute("aRandom") as THREE.BufferAttribute).array as Float32Array;
      for (let p = 0; p < start.length / 3; p++) {
        const x = Math.min(1, Math.max(0, this.morph * 1.25 - random[p * 4] * 0.25));
        const m = x * x * (3 - 2 * x); // smoothstep
        for (let k = p * 3; k < p * 3 + 3; k++) start[k] = from[k] + (start[k] - from[k]) * m;
      }
    }
    previous.copyArray(start);
    previous.needsUpdate = true;
    current.copyArray(generateShape(settings.shape, settings.particleCount));
    current.needsUpdate = true;
    this.morph = 0;
  }

  private createHalo() {
    const material = new THREE.ShaderMaterial({
      vertexShader: HALO_VERTEX,
      fragmentShader: HALO_FRAGMENT,
      uniforms: { uColor: { value: new THREE.Color() }, uIntensity: { value: 0 }, uTime: { value: 0 } },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(5.5, 5.5), material);
    mesh.position.z = -0.6;
    return mesh;
  }

  private createDust() {
    const positions = new Float32Array(DUST_COUNT * 3);
    const seeds = new Float32Array(DUST_COUNT);
    for (let i = 0; i < DUST_COUNT; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 14;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 8;
      positions[i * 3 + 2] = -1 - Math.random() * 6;
      seeds[i] = Math.random();
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
    const material = new THREE.ShaderMaterial({
      vertexShader: DUST_VERTEX,
      fragmentShader: DUST_FRAGMENT,
      uniforms: { uTime: { value: 0 }, uPixelRatio: { value: 1 }, uColor: { value: new THREE.Color() } },
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const dust = new THREE.Points(geometry, material);
    dust.frustumCulled = false;
    return dust;
  }

  private applySettings(s: OrbSettings) {
    const u = this.points.material.uniforms;
    u.uColorA.value.set(s.colorPrimary);
    u.uColorB.value.set(s.colorSecondary);
    u.uColorThinking.value.set(s.colorThinking);
    u.uColorGathering.value.set(s.colorGathering);
    u.uColorSpeaking.value.set(s.colorSpeaking);
    u.uColorListening.value.set(s.colorListening);
    u.uSize.value = s.particleSize;
    u.uGlow.value = s.glow;
    this.halo.material.uniforms.uColor.value.set(s.colorPrimary).lerp(new THREE.Color(s.colorSecondary), 0.4);
    this.dust.material.uniforms.uColor.value.set(s.colorPrimary).lerp(new THREE.Color("#ffffff"), 0.5);
    this.dust.visible = s.ambientDust;
  }

  // ---- input --------------------------------------------------------------------------

  private onPointerMove = (event: PointerEvent) => {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointerNdc.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    this.pointerInside = true;
  };

  private onPointerLeave = () => {
    this.pointerInside = false;
    this.pointerNdc.set(10, 10);
  };

  private onPointerDown = () => {
    if (this.hovering) this.pulse();
  };

  private resize() {
    const { clientWidth: w, clientHeight: h } = this.container;
    if (w === 0 || h === 0) return;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    // Keep the orb fully visible in narrow windows.
    this.camera.position.z = w / h < 1 ? 4.2 / Math.max(w / h, 0.55) : 4.2;
    this.camera.updateProjectionMatrix();
    const ratio = this.renderer.getPixelRatio();
    this.points.material.uniforms.uPixelRatio.value = ratio;
    this.dust.material.uniforms.uPixelRatio.value = ratio;
  }

  // ---- animation loop -----------------------------------------------------------------

  private tick = (now: number) => {
    this.frame = requestAnimationFrame(this.tick);
    if (document.hidden) {
      this.lastTime = now;
      return;
    }
    const dt = Math.min((now - this.lastTime) / 1000, 0.05);
    this.lastTime = now;
    const s = this.settings;
    const speed = s.speed * (this.reducedMotion ? 0.4 : 1);
    this.time += dt * speed;

    // Pointer → world position on the orb's plane, and hover detection.
    if (this.pointerInside) {
      this.raycaster.setFromCamera(this.pointerNdc, this.camera);
      this.raycaster.ray.intersectPlane(this.plane, this.pointerWorld);
    } else {
      this.pointerWorld.set(10, 10, 0);
    }
    const hovering = this.pointerInside && this.pointerWorld.length() < 1.15 * s.size;
    if (hovering !== this.hovering) {
      this.hovering = hovering;
      this.onHoverChange(hovering);
    }

    // State weights ease toward their targets, so transitions never jump.
    const target = (state: OrbState, amount: number) => (this.state === state ? amount : 0);
    const w = this.weights;
    w.thinking = approach(w.thinking, target("thinking", s.thinking), 3, dt);
    w.gathering = approach(w.gathering, target("gathering", s.gathering), 3, dt);
    w.speaking = approach(w.speaking, target("speaking", s.speaking), 4, dt);
    w.listening = approach(w.listening, target("listening", s.listening), 5, dt);
    w.alert = approach(w.alert, target("alert", 1), 3, dt);
    w.error = approach(w.error, target("error", 1), 6, dt);
    w.hover = approach(w.hover, hovering ? s.hover : 0, 6, dt);
    this.smoothSpeech = approach(this.smoothSpeech, this.levels.speech, 12, dt);
    this.smoothMic = approach(this.smoothMic, this.levels.mic, 14, dt);
    this.levels.speech = approach(this.levels.speech, 0, 5, dt); // speech pulses decay on their own
    this.burst = approach(this.burst, 0, 3.2, dt);
    this.morph = Math.min(1, this.morph + dt / (this.intro < 1 ? INTRO_SECONDS : MORPH_SECONDS));
    if (this.morph >= 1) this.intro = 1;

    const u = this.points.material.uniforms;
    u.uTime.value = this.time;
    u.uMorph.value = this.morph;
    u.uScale.value = s.size;
    u.uTurbulence.value = s.turbulence * (this.reducedMotion ? 0.5 : 1);
    u.uBreathing.value = s.breathing;
    u.uThinking.value = w.thinking;
    u.uGathering.value = w.gathering;
    u.uSpeaking.value = w.speaking;
    u.uListening.value = w.listening;
    u.uAlert.value = w.alert;
    u.uError.value = w.error;
    u.uHover.value = w.hover;
    u.uBurst.value = this.burst * s.burst;
    u.uSpeechLevel.value = this.smoothSpeech;
    u.uMicLevel.value = this.smoothMic;
    u.uPointer.value.copy(this.pointerWorld);

    // Idle spin, faster while thinking; a slight tilt toward the pointer on hover.
    this.points.rotation.y += dt * speed * s.rotation * 0.25 * (1 + w.thinking * 3 + w.gathering);
    const tiltX = hovering ? -this.pointerWorld.y * 0.12 : 0;
    const tiltZ = hovering ? -this.pointerWorld.x * 0.06 : 0;
    this.points.rotation.x = approach(this.points.rotation.x, tiltX, 3, dt);
    this.points.rotation.z = approach(this.points.rotation.z, tiltZ, 3, dt);

    const busy = Math.max(w.thinking, w.gathering, w.speaking, w.listening);
    const hu = this.halo.material.uniforms;
    hu.uTime.value = this.time;
    hu.uIntensity.value = s.glow * (0.35 + busy * 0.35 + this.smoothSpeech * 0.4 + this.smoothMic * 0.4 + w.hover * 0.15);
    this.halo.scale.setScalar(s.size * (1 + this.smoothSpeech * 0.08));

    const du = this.dust.material.uniforms;
    du.uTime.value = this.time;
    // Parallax: the background drifts a little against the pointer.
    this.dust.position.x = approach(this.dust.position.x, this.pointerInside ? -this.pointerNdc.x * 0.25 : 0, 2, dt);
    this.dust.position.y = approach(this.dust.position.y, this.pointerInside ? -this.pointerNdc.y * 0.15 : 0, 2, dt);

    this.renderer.render(this.scene, this.camera);
  };
}
