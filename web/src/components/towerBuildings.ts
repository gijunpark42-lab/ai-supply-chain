// towerBuildings.ts — what each company's building looks like in the Supply-chain Tower.
//
// The shape says what the floor makes, so the tower reads like a city with one district
// per industry:
//   apps: glass towers with a lit crown     AI models: round towers      software: stepped towers
//   cloud: wide data halls with LED bands   server makers: rack rows     compute: a GPU package
//   memory: a stack of dies (up to 12-high) interconnect: signal towers  packaging: chiplets
//   foundry: fabs with exhaust stacks       equipment: sawtooth factories materials: tanks
//   minerals: an ore pile                   power: cooling towers        thermal: fan units
// Size still says how connected a company is, and color says where it is from.
//
// Every building is merged into at most three meshes (lit walls, plain body, glowing
// accents), so hundreds of detailed buildings still draw quickly.

import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";

export const WINDOW_TILE = 2; // one window-texture tile (4 × 4 windows) covers 2 × 2 units of wall
const MAX_FOOTPRINT = 3; // a building never reaches into the next grid cell (3.4 apart)
const fit = (x: number) => Math.min(x, MAX_FOOTPRINT);

type Look = "windows" | "body" | "accent";
type At = [number, number, number];

export interface BuildingLook {
  object: THREE.Group; // stands on y = 0, centred on x = z = 0
  top: number; // height where links attach and the logo floats
  glow: THREE.MeshStandardMaterial[]; // brighter when lit or hovered (base in userData.glow)
  all: THREE.Material[]; // everything, for fading
}

// The wall pattern: a 4 × 4 grid of windows, most lit, a few dark, so the towers read as a
// city at night. White = lit: it is an emissive map, tinted by each building's country color.
export function windowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 64;
  const g = c.getContext("2d")!;
  g.fillStyle = "#000000";
  g.fillRect(0, 0, 64, 64);
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 4; j++) {
      const lit = (i * 7 + j * 13) % 5 !== 0; // a fixed pattern (no flicker between rebuilds)
      g.fillStyle = lit ? "#ffffff" : "#1c1c1c";
      g.fillRect(i * 16 + 4, j * 16 + 4, 8, 9);
    }
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// w = footprint (1.1 … 2.4) and h = height (0.6 … 8.6), both from the company's connections.
export function makeBuilding(floor: string, w: number, h: number, color: THREE.Color, windows: THREE.Texture): BuildingLook {
  const kit = new Kit();
  const top = (SHAPES[floor] || glassTower)(kit, w, h);
  const walls = new THREE.MeshStandardMaterial({
    color: color.clone().multiplyScalar(0.3),
    emissive: color,
    emissiveMap: windows,
    roughness: 0.6,
    metalness: 0.2,
  });
  const body = new THREE.MeshStandardMaterial({
    color: color.clone().multiplyScalar(0.55),
    roughness: 0.5,
    metalness: 0.35,
    side: THREE.DoubleSide, // cooling towers are open at the top
  });
  const accent = new THREE.MeshStandardMaterial({ color, emissive: color, roughness: 0.3 });
  walls.userData.glow = 0.85;
  accent.userData.glow = 0.9;
  // Remember the colors: a faded building is darkened, not made see-through (much cheaper to
  // draw), and a mode (signals, generations) repaints it — each part keeps its own shade.
  walls.userData.shade = 0.3;
  body.userData.shade = 0.55;
  accent.userData.shade = 1;
  for (const m of [walls, body, accent]) {
    m.userData.baseColor = m.color.clone();
    m.userData.baseEmissive = m.emissive.clone();
  }
  return { object: kit.finish({ windows: walls, body, accent }), top, glow: [walls, accent], all: [walls, body, accent] };
}

// ── The districts ───────────────────────────────────────────────────────────
// Each draws one building with the kit and returns its height.

function glassTower(k: Kit, w: number, h: number) {
  k.box(w, h, w);
  k.box(w * 1.06, 0.16, w * 1.06, [0, h, 0], "accent"); // a lit crown
  return h + 0.16;
}

function steppedTower(k: Kit, w: number, h: number) {
  const low = h * 0.6;
  k.box(w, low, w);
  k.box(w * 0.64, h - low, w * 0.64, [0, low, 0]); // a setback, like a classic skyscraper
  k.box(w * 0.7, 0.14, w * 0.7, [0, h, 0], "accent");
  return h + 0.14;
}

function roundTower(k: Kit, w: number, h: number) {
  const r = w * 0.5;
  k.cylinder(r, r, h, [0, 0, 0], "windows", 20);
  k.ring(r * 1.04, 0.07, [0, h - 0.15, 0]); // a glowing halo near the top
  return h;
}

function dataHall(k: Kit, w: number, h: number) {
  const fw = fit(w * 1.45);
  const fd = fit(w * 1.15);
  const fh = Math.max(0.7, h * 0.42);
  k.box(fw, fh, fd, [0, 0, 0], "body");
  for (const f of [0.33, 0.66]) k.box(fw + 0.04, 0.07, fd + 0.04, [0, fh * f, 0], "accent"); // LED bands: rows of servers
  const r = 0.16 + 0.1 * w; // chillers on the roof
  for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) k.cylinder(r, r, 0.28, [(x * fw) / 4, fh, (z * fd) / 4], "body", 10);
  return fh + 0.28;
}

function rackRow(k: Kit, w: number, h: number) {
  const rw = Math.min(w * 0.34, 0.9);
  const gap = 0.1;
  const d = w * 0.8;
  for (const i of [-1, 0, 1]) k.box(rw, h, d, [i * (rw + gap), 0, 0]); // three server racks, lit like status LEDs
  k.box(rw * 3 + gap * 2 + 0.1, 0.1, d + 0.1, [0, h, 0], "accent");
  return h + 0.1;
}

function gpuPackage(k: Kit, w: number, h: number) {
  const base = fit(w * 1.45);
  const die = w * 0.6;
  const dh = Math.max(0.3, h * 0.8);
  k.box(base, 0.3, base, [0, 0, 0], "body"); // the package substrate
  k.box(die, dh, die, [0, 0.3, 0]); // the GPU die
  k.box(die * 0.92, 0.08, die * 0.92, [0, 0.3 + dh, 0], "accent");
  const s = Math.max(0.16, (base - die) / 2 - 0.1); // HBM stacks on both sides of the die
  for (const x of [-(die / 2 + s / 2 + 0.05), die / 2 + s / 2 + 0.05])
    for (const z of [-die * 0.24, die * 0.24]) k.box(s, dh * 0.72, die * 0.4, [x, 0.3, z], "accent");
  return 0.3 + dh + 0.08;
}

function memoryStack(k: Kit, w: number, h: number) {
  const dies = 4 + Math.round(Math.min(1, h / 8.6) * 8); // 4-high … 12-high, like an HBM stack
  const step = h / dies;
  for (let i = 0; i < dies; i++) {
    k.box(w, step * 0.76, w, [0, i * step, 0], "body"); // a DRAM die
    k.box(w * 0.93, step * 0.24, w * 0.93, [0, i * step + step * 0.76, 0], "accent"); // the lit bond line
  }
  return h;
}

function signalTower(k: Kit, w: number, h: number) {
  const r = 0.18 + 0.12 * w;
  k.cylinder(r * 0.7, r, h, [0, 0, 0], "body", 10);
  const rings = 1 + Math.round(h / 3);
  for (let i = 1; i <= rings; i++) k.ring(r * 1.9, 0.06, [0, (h * i) / (rings + 1), 0]); // light rings, like fibre
  k.ball(r * 1.1, [0, h + r * 0.6, 0]);
  return h + r * 1.7;
}

function interposer(k: Kit, w: number, h: number) {
  const base = fit(w * 1.5);
  const core = w * 0.55;
  const ch = Math.max(0.3, h * 0.7);
  k.box(base, 0.25, base, [0, 0, 0], "body"); // the interposer
  k.box(core, ch, core, [0, 0.25, 0]); // the main die
  const c = core * 0.45;
  const off = core / 2 + c / 2 + 0.08;
  for (const [x, z] of [[off, 0], [-off, 0], [0, off], [0, -off]]) k.box(c, ch * 0.5, c, [x, 0.25, z], "accent"); // chiplets
  return 0.25 + ch;
}

function fab(k: Kit, w: number, h: number) {
  const fw = fit(w * 1.5);
  const fd = fit(w * 1.15);
  const fh = Math.max(0.6, h * 0.5);
  k.box(fw, fh, fd); // the cleanroom halls
  const r = 0.1 + 0.05 * w;
  const sh = Math.max(1, h * 0.5); // tall enough to read as stacks, short of the floor above
  for (const x of [-fw * 0.28, fw * 0.28]) {
    k.cylinder(r, r * 1.2, sh, [x, fh, -fd * 0.25], "body", 8); // exhaust stacks
    k.cylinder(r * 1.05, r * 1.05, 0.12, [x, fh + sh, -fd * 0.25], "accent", 8);
  }
  return fh + sh + 0.12;
}

function factory(k: Kit, w: number, h: number) {
  const fw = fit(w * 1.4);
  const fd = fit(w * 1.1);
  const fh = Math.max(0.5, h * 0.45);
  k.box(fw, fh, fd, [0, 0, 0], "body");
  const teeth = 3; // a sawtooth roof of lit glass panes
  const pitch = fw / teeth;
  for (let i = 0; i < teeth; i++) k.pane(pitch * 0.95, fd * 0.96, [-fw / 2 + pitch * (i + 0.5), fh, 0]);
  return fh + pitch * 0.5;
}

function tanks(k: Kit, w: number, h: number) {
  const n = w > 1.8 ? 3 : w > 1.4 ? 2 : 1;
  const r = Math.min(0.3 + 0.18 * w, (MAX_FOOTPRINT - 0.1 * (n - 1)) / (2 * n));
  const th = Math.max(0.5, h * 0.75);
  for (let i = 0; i < n; i++) {
    const x = (i - (n - 1) / 2) * (2 * r + 0.1);
    k.cylinder(r, r, th, [x, 0, 0], "body", 16);
    k.dome(r, r * 0.6, [x, th, 0]);
    k.ring(r * 1.03, 0.04, [x, th * 0.5, 0]); // a lit band
  }
  return th + r * 0.6;
}

function orePile(k: Kit, w: number, h: number) {
  const r = fit(w * 0.9);
  const ph = Math.max(0.6, h * 0.7);
  k.cylinder(0, r, ph, [0, 0, 0], "body", 4); // a pyramid of ore
  k.cylinder(0, r * 0.18, ph * 0.18, [0, ph * 0.82, 0], "accent", 4);
  return ph;
}

function coolingTower(k: Kit, w: number, h: number) {
  const rb = Math.min(w * 0.62, MAX_FOOTPRINT / 2);
  const th = Math.max(1, h * 0.95);
  // A hyperboloid: widest at the foot, waisted about two thirds up, flaring a little at the lip.
  const profile: THREE.Vector2[] = [];
  for (let i = 0; i <= 12; i++) {
    const t = i / 12;
    profile.push(new THREE.Vector2(rb * (0.62 + (0.38 * Math.pow(2 * t - 1.3, 2)) / 1.69), th * t));
  }
  k.put(new THREE.LatheGeometry(profile, 20), "body");
  k.ring(profile[12].x, 0.05, [0, th, 0]);
  return th;
}

function fanUnit(k: Kit, w: number, h: number) {
  const fw = fit(w * 1.3);
  const fh = Math.max(0.5, h * 0.45);
  k.box(fw, fh, fw, [0, 0, 0], "body");
  const r = fw * 0.2;
  for (const x of [-fw / 4, fw / 4])
    for (const z of [-fw / 4, fw / 4]) {
      k.cylinder(r, r, 0.12, [x, fh, z], "body", 16); // fan housings
      k.cylinder(r * 0.78, r * 0.78, 0.14, [x, fh, z], "accent", 16); // lit blades
    }
  return fh + 0.14;
}

function pod(k: Kit, w: number, h: number) {
  const r = w * 0.7;
  const dh = Math.max(0.6, h * 0.6);
  k.dome(r, dh, [0, 0, 0]);
  k.ring(r * 1.01, 0.05, [0, 0.1, 0]);
  return dh;
}

const SHAPES: Record<string, (k: Kit, w: number, h: number) => number> = {
  application: glassTower,
  ai_models: roundTower,
  software_infra: steppedTower,
  cloud_infra: dataHall,
  system_integration: rackRow,
  compute_hardware: gpuPackage,
  memory: memoryStack,
  interconnect: signalTower,
  advanced_packaging: interposer,
  foundry: fab,
  equipment: factory,
  materials: tanks,
  minerals: orePile,
  power: coolingTower,
  thermal: fanUnit,
  edge_ai: pod,
  security: glassTower,
};

// ── The kit: parts collected per look, merged into one mesh per look at the end ──
class Kit {
  private parts: Record<Look, THREE.BufferGeometry[]> = { windows: [], body: [], accent: [] };

  // A box whose bottom centre sits at `at`. With the "windows" look its four sides carry the
  // window pattern — repeated per WINDOW_TILE units, so a tall wall gets more rows rather than
  // stretched windows — and its top and bottom are plain.
  box(wx: number, hy: number, dz: number, at: At = [0, 0, 0], look: Look = "windows") {
    const geo = new THREE.BoxGeometry(wx, hy, dz);
    geo.translate(at[0], at[1] + hy / 2, at[2]);
    if (look !== "windows") return this.put(geo, look);
    const [px, nx, py, ny, pz, nz] = splitByGroups(geo); // BoxGeometry faces: +x, -x, +y, -y, +z, -z
    const T = WINDOW_TILE;
    this.parts.windows.push(
      scaleUV(px, dz / T, hy / T),
      scaleUV(nx, dz / T, hy / T),
      scaleUV(pz, wx / T, hy / T),
      scaleUV(nz, wx / T, hy / T)
    );
    this.parts.body.push(py, ny);
  }

  // A cylinder (a cone or pyramid when rTop is 0) whose bottom centre sits at `at`.
  cylinder(rTop: number, rBottom: number, hy: number, at: At = [0, 0, 0], look: Look = "body", segments = 16) {
    const geo = new THREE.CylinderGeometry(rTop, rBottom, hy, segments);
    geo.translate(at[0], at[1] + hy / 2, at[2]);
    if (look !== "windows") return this.put(geo, look);
    const [side, ...caps] = splitByGroups(geo); // CylinderGeometry groups: side, top cap, bottom cap
    this.parts.windows.push(scaleUV(side, (Math.PI * (rTop + rBottom)) / WINDOW_TILE, hy / WINDOW_TILE));
    this.parts.body.push(...caps);
  }

  // A ring lying flat around the vertical axis (a halo, a band, a signal ring).
  ring(radius: number, tube: number, at: At, look: Look = "accent") {
    const geo = new THREE.TorusGeometry(radius, tube, 6, 28);
    geo.rotateX(Math.PI / 2);
    geo.translate(at[0], at[1], at[2]);
    this.put(geo, look);
  }

  // The top half of a sphere, `height` tall, its base centred on `at` (tank domes, pods).
  dome(r: number, height: number, at: At, look: Look = "body") {
    const geo = new THREE.SphereGeometry(r, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2);
    geo.scale(1, height / r, 1);
    geo.translate(at[0], at[1], at[2]);
    this.put(geo, look);
  }

  ball(r: number, at: At, look: Look = "accent") {
    const geo = new THREE.SphereGeometry(r, 12, 8);
    geo.translate(at[0], at[1], at[2]);
    this.put(geo, look);
  }

  // A thin pane tilted like one tooth of a factory's sawtooth roof.
  pane(len: number, depth: number, at: At, look: Look = "accent") {
    const tilt = 0.55;
    const geo = new THREE.BoxGeometry(len, 0.06, depth);
    geo.rotateZ(-tilt);
    geo.translate(at[0], at[1] + (len / 2) * Math.sin(tilt), at[2]);
    this.put(geo, look);
  }

  // Any shape already in place.
  put(geo: THREE.BufferGeometry, look: Look) {
    const flat = geo.index ? geo.toNonIndexed() : geo;
    flat.clearGroups();
    this.parts[look].push(flat);
  }

  // One mesh per look: a building costs at most three draw calls however many parts it has.
  finish(materials: Record<Look, THREE.Material>) {
    const group = new THREE.Group();
    for (const look of ["windows", "body", "accent"] as Look[]) {
      const list = this.parts[look];
      if (!list.length) continue;
      const merged = mergeGeometries(list);
      list.forEach((g) => g.dispose());
      if (merged) group.add(new THREE.Mesh(merged, materials[look]));
    }
    return group;
  }
}

// Cut a geometry into one piece per material group. Once un-indexed, a group's range is
// simply a run of vertices.
function splitByGroups(geo: THREE.BufferGeometry): THREE.BufferGeometry[] {
  const flat = geo.toNonIndexed();
  return flat.groups.map(({ start, count }) => {
    const piece = new THREE.BufferGeometry();
    for (const name of ["position", "normal", "uv"]) {
      const a = flat.getAttribute(name) as THREE.BufferAttribute;
      const values = (a.array as Float32Array).slice(start * a.itemSize, (start + count) * a.itemSize);
      piece.setAttribute(name, new THREE.BufferAttribute(values, a.itemSize));
    }
    return piece;
  });
}

function scaleUV(geo: THREE.BufferGeometry, su: number, sv: number) {
  const uv = geo.getAttribute("uv") as THREE.BufferAttribute;
  for (let i = 0; i < uv.count; i++) uv.setXY(i, uv.getX(i) * su, uv.getY(i) * sv);
  return geo;
}
