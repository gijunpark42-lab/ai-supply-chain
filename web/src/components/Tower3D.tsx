"use client";

// Tower3D.tsx — draws the Supply-chain Tower with plain three.js.
//
// React owns the page and the side panel; this component owns one <canvas>. The scene —
// a night sky, a lit pedestal, a floor per layer and a building per company per floor,
// shaped like its industry (towerBuildings.ts) — is built once per node list. What is lit,
// which links are drawn, what the floor tags say and any mode colors arrive as a `view`
// (lib/tower.ts decides it) and only restyle the scene.
//
// Zooming in shows more: the nearest buildings show their logo (checked a few times a
// second), and the camera flies to a company or a floor when you pick one. A bloom pass
// makes the lit windows, beacons and links glow; it can be switched off on slow machines.

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CSS2DObject, CSS2DRenderer } from "three/examples/jsm/renderers/CSS2DRenderer.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/examples/jsm/postprocessing/OutputPass.js";
import type { VizNode } from "@/lib/types";
import { FLOORS, buildingKey, countryGroup, floorsOf, type TowerView } from "@/lib/tower";
import { makeBuilding, windowTexture, type BuildingLook } from "./towerBuildings";
import "./Tower.css";

// ── Tower geometry (world units) ────────────────────────────────────────────
const FLOOR_GAP = 14; // height between two floors
const SLAB = 0.35; // floor thickness
const CELL = 3.4; // spacing of the building grid on a floor
const MAX_HEIGHT = 8; // height scale of the best-connected company's building (< FLOOR_GAP)
const BEACONS = 8; // the best-connected companies get a spire with a blinking red light

// ── Level of detail: what appears as you zoom in ────────────────────────────
const NEAR = 80; // buildings closer than this to the camera show who they are (logo, else name)…
const NEAR_TAGS = 20; // …at most this many, the nearest first
const DETAIL_EVERY = 0.25; // seconds between two checks
const FLY_SECONDS = 0.9;

// ── Motion ──────────────────────────────────────────────────────────────────
const RISE_SECONDS = 0.7; // each building's rise when the page opens…
const RISE_STAGGER = 0.14; // …floor after floor, from the minerals up
const POP_SECONDS = 0.55; // the little jump of the buildings a new view lights up

// How brightly windows and accents glow, as a multiple of each material's own base glow.
const GLOW = { dim: 0.1, normal: 1, lit: 2, hover: 3.2 };

interface Building {
  node: VizNode;
  floor: string;
  look: BuildingLook; // the building's meshes and materials
  extras: THREE.MeshBasicMaterial[]; // the spire, faded with the building
  object: THREE.Group;
  topY: number; // building height above its floor
  top: THREE.Vector3; // roof centre in the world: links attach here
  rank: number; // its floor's place counted from the bottom (the rise goes floor by floor)
  labelDiv: HTMLDivElement;
  label: CSS2DObject;
  logo: THREE.Sprite | null | undefined; // undefined = not made yet, null = no logo for this company
}

interface Floor {
  color: string;
  material: THREE.MeshStandardMaterial;
  tag: HTMLDivElement;
  note: HTMLSpanElement;
  x: number;
  y: number;
}

// The moving dots of the current view's links: one instanced mesh, one dot per link.
interface Pulses {
  mesh: THREE.InstancedMesh;
  curves: THREE.QuadraticBezierCurve3[];
}

interface SceneState {
  camera: THREE.PerspectiveCamera;
  buildings: Map<string, Building>;
  floors: Map<string, Floor>;
  links: THREE.Group; // the current view's links and their moving dots
  pulses: Pulses | null;
  annexX: number; // x of the annex's centre line (the main tower's is 0)
  view: TowerView; // the view last applied — hover and level of detail read it
  focusKey: string | null; // the picked company's building: its tag and logo always show
  hoverKey: string | null;
  now: number; // seconds since the scene started (kept by the draw loop)
  pop: { at: number; keys: Set<string> } | null; // the buildings a new view makes jump
}

interface Fly {
  home: () => void;
  building: (key: string) => void;
  floor: (slug: string) => void;
}

interface Props {
  nodes: VizNode[];
  view: TowerView;
  focusKey: string | null; // the picked company's building: the camera flies to it
  overviewKey: string; // changes when a new chain, compare or mode is picked: fly back to see it all
  onPickCompany: (id: string | null) => void;
}

// ── Textures made on a canvas (no image files to ship) ─────────────────────
// The night sky behind everything: deep blue at the top fading to near-black.
function skyTexture() {
  const c = document.createElement("canvas");
  c.width = 2;
  c.height = 512;
  const g = c.getContext("2d")!;
  const grad = g.createLinearGradient(0, 0, 0, 512);
  grad.addColorStop(0, "#0c1a3a");
  grad.addColorStop(0.55, "#070b16");
  grad.addColorStop(1, "#04060a");
  g.fillStyle = grad;
  g.fillRect(0, 0, 2, 512);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

// A soft round glow, white in the middle — the pedestal's lit top.
function glowTexture() {
  const c = document.createElement("canvas");
  c.width = c.height = 256;
  const g = c.getContext("2d")!;
  const grad = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.45, "rgba(255,255,255,0.35)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = grad;
  g.fillRect(0, 0, 256, 256);
  return new THREE.CanvasTexture(c);
}

// Stars on a far sphere, mostly above the horizon, a few tinted warm or blue.
function starField(count: number, radius: number) {
  const positions = new Float32Array(count * 3);
  const colors = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const theta = 2 * Math.PI * Math.random();
    const phi = Math.acos(1 - 1.6 * Math.random()); // from straight up to a little below the horizon
    positions.set(
      [radius * Math.sin(phi) * Math.cos(theta), radius * Math.cos(phi), radius * Math.sin(phi) * Math.sin(theta)],
      i * 3
    );
    const tone = Math.random();
    colors.set(tone > 0.88 ? [1, 0.88, 0.7] : tone < 0.2 ? [0.7, 0.8, 1] : [1, 1, 1], i * 3);
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geo.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  const mat = new THREE.PointsMaterial({ size: 1.8, sizeAttenuation: false, vertexColors: true, fog: false, transparent: true, opacity: 0.85, depthWrite: false });
  return new THREE.Points(geo, mat);
}

// The stage the tower stands on: a dark disc with a glowing top, a bright rim and faint rings.
function pedestal(radius: number) {
  const group = new THREE.Group();
  const side = new THREE.MeshStandardMaterial({ color: "#070b14", metalness: 0.6, roughness: 0.4 });
  const top = new THREE.MeshStandardMaterial({
    color: "#060a12",
    emissive: "#1e3a8a",
    emissiveMap: glowTexture(),
    emissiveIntensity: 0.16, // a faint pool of light under the tower, not a spotlight
    metalness: 0.5,
    roughness: 0.45,
  });
  group.add(new THREE.Mesh(new THREE.CylinderGeometry(radius, radius * 1.03, 1.4, 128), [side, top, side]));
  const rim = new THREE.Mesh(new THREE.TorusGeometry(radius * 1.004, 0.2, 10, 220), new THREE.MeshBasicMaterial({ color: "#38bdf8" }));
  rim.rotation.x = Math.PI / 2;
  rim.position.y = 0.7;
  group.add(rim);
  for (const f of [0.38, 0.62, 0.84]) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(radius * f, 0.06, 6, 180), new THREE.MeshBasicMaterial({ color: "#172554" }));
    ring.rotation.x = Math.PI / 2;
    ring.position.y = 0.72;
    group.add(ring);
  }
  return group;
}

// A company logo as a badge texture: a white (or dark) rounded chip like the Graph tab's logo
// chips. Made once per file; the badge fills in when the image has loaded.
const logoCache = new Map<string, THREE.CanvasTexture>();
function logoTexture(url: string, dark: boolean) {
  const key = url + (dark ? "|dark" : "");
  const cached = logoCache.get(key);
  if (cached) return cached;
  const c = document.createElement("canvas");
  c.width = 256;
  c.height = 128;
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  logoCache.set(key, tex);
  const img = new Image();
  img.onload = () => {
    const g = c.getContext("2d")!;
    g.fillStyle = dark ? "rgba(20, 23, 28, 0.96)" : "rgba(255, 255, 255, 0.96)";
    roundedRect(g, 4, 4, 248, 120, 18);
    g.fill();
    // Fit the logo inside the chip with a margin, keeping its shape. An SVG without a size
    // reports 0 × 0: treat it as 2:1.
    const iw = img.naturalWidth || 200;
    const ih = img.naturalHeight || 100;
    const s = Math.min(212 / iw, 84 / ih);
    g.drawImage(img, 128 - (iw * s) / 2, 64 - (ih * s) / 2, iw * s, ih * s);
    tex.needsUpdate = true;
  };
  img.src = url;
  return tex;
}

function roundedRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

// Grid cells of one floor, centre first: the best-connected companies stand in the middle.
function cellsCentreFirst(grid: number) {
  const cells: { x: number; z: number }[] = [];
  for (let i = 0; i < grid; i++)
    for (let j = 0; j < grid; j++) cells.push({ x: (i - (grid - 1) / 2) * CELL, z: (j - (grid - 1) / 2) * CELL });
  const dist = (c: { x: number; z: number }) => c.x * c.x + c.z * c.z;
  return cells.sort((a, b) => dist(a) - dist(b) || Math.atan2(a.z, a.x) - Math.atan2(b.z, b.x));
}

// Easing: overshoot a little and settle (the rise), and a smooth in-out (flights).
const easeOutBack = (k: number) => 1 + 2.2 * Math.pow(k - 1, 3) + 1.2 * Math.pow(k - 1, 2);
const easeInOut = (k: number) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);

export default function Tower3D({ nodes, view, focusKey, overviewKey, onPickCompany }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const tipRef = useRef<HTMLDivElement>(null);
  const stateRef = useRef<SceneState | null>(null);
  const flyRef = useRef<Fly>({ home: () => {}, building: () => {}, floor: () => {} });
  const [glow, setGlow] = useState(true); // the bloom pass (off = faster on weak machines)
  const glowRef = useRef(glow);
  glowRef.current = glow;
  // The listeners below are attached once; they always call the latest callback through this ref.
  const pickRef = useRef(onPickCompany);
  pickRef.current = onPickCompany;

  // ── 1. Build the scene (once per node list) ───────────────────────────────
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    // Which companies stand on which floor, and how big the floors must be.
    const perFloor = new Map<string, VizNode[]>();
    for (const n of nodes) for (const f of floorsOf(n)) (perFloor.get(f) || perFloor.set(f, []).get(f)!).push(n);
    const busiest = Math.max(1, ...[...perFloor.values()].map((l) => l.length));
    const grid = Math.max(6, Math.ceil(Math.sqrt(busiest))); // 10 × 10 for the 100 equipment makers
    const floorSize = grid * CELL + 3;
    const annexX = floorSize + 18; // the cross-cutting domains stand beside the main tower
    const cells = cellsCentreFirst(grid);
    const maxDegree = Math.max(1, ...nodes.map((n) => n.degree));
    const beaconIds = new Set([...nodes].sort((a, b) => b.degree - a.degree).slice(0, BEACONS).map((n) => n.id));

    // Floor positions: the 13 layers stacked top → bottom at x = 0; the domains that have
    // companies stacked in the annex, starting level with Cloud Infrastructure.
    const layers = FLOORS.filter((f) => !f.annex);
    const floorPos = new Map<string, { x: number; y: number }>();
    layers.forEach((f, i) => floorPos.set(f.slug, { x: 0, y: (layers.length - 1 - i) * FLOOR_GAP }));
    const annexTop = floorPos.get("cloud_infra")?.y ?? 9 * FLOOR_GAP;
    FLOORS.filter((f) => f.annex && perFloor.has(f.slug)).forEach((f, i) =>
      floorPos.set(f.slug, { x: annexX, y: annexTop - i * FLOOR_GAP })
    );

    // Renderer (the canvas) plus a label layer (HTML tags drawn over the canvas).
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5)); // sharp enough; 2× costs a lot of fill
    host.appendChild(renderer.domElement);
    const labelRenderer = new CSS2DRenderer();
    labelRenderer.domElement.className = "tw-labels";
    host.appendChild(labelRenderer.domElement);

    // A night scene: a deep-blue sky with stars, soft light, so the lit windows carry the color.
    const scene = new THREE.Scene();
    const sky = skyTexture();
    scene.background = sky;
    scene.fog = new THREE.Fog("#070b16", 360, 900);
    scene.add(new THREE.HemisphereLight("#cfe3ff", "#0b1118", 0.6));
    const moon = new THREE.DirectionalLight("#ffffff", 0.85);
    moon.position.set(90, 240, 140);
    scene.add(moon);
    const stars = starField(1800, 1500);
    stars.position.set(annexX / 2, 0, 0);
    scene.add(stars);
    const stage = pedestal((annexX + floorSize) / 2 + 14);
    stage.position.set(annexX / 2, -8, 0);
    scene.add(stage);

    // Camera + mouse/touch controls: a little above the tower's middle, looking down onto
    // the floors. A slow turn until the user takes over.
    const height = (layers.length - 1) * FLOOR_GAP;
    const target = new THREE.Vector3(annexX / 2, height / 2 + 6, 0);
    const homeOffset = new THREE.Vector3(135, 105, 185);
    // The starting spot. On a narrow or tall screen (a phone) step further back, so the whole
    // tower and its floor tags still fit.
    const home = () => {
      const w = Math.max(1, host.clientWidth);
      const k = Math.min(2.4, Math.max(1, 1.25 / (w / Math.max(1, host.clientHeight)), 760 / w));
      return target.clone().add(homeOffset.clone().multiplyScalar(k));
    };
    const camera = new THREE.PerspectiveCamera(45, 1, 0.5, 4000);
    camera.position.copy(home());
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.copy(target);
    controls.enableDamping = true;
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.5;
    controls.minDistance = 8; // close enough to read a logo, never inside a building
    let touched = false; // has the user (or a fly-to) moved the camera yet?
    controls.addEventListener("start", () => {
      controls.autoRotate = false;
      touched = true;
    });

    // Glow: render the scene, let the brightest parts bleed light (bloom), then output.
    const composer = new EffectComposer(renderer);
    composer.addPass(new RenderPass(scene, camera));
    const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.85, 0.45, 0.62);
    composer.addPass(bloom);
    composer.addPass(new OutputPass());

    // Floors and buildings.
    const windows = windowTexture();
    const buildings = new Map<string, Building>();
    const floors = new Map<string, Floor>();
    const meshes: THREE.Object3D[] = []; // what the mouse can point at
    const beacons: { light: THREE.MeshBasicMaterial; key: string }[] = []; // blinking lights, animated in tick()
    for (const def of FLOORS) {
      const p = floorPos.get(def.slug);
      if (!p) continue;
      const rank = Math.round(p.y / FLOOR_GAP); // 0 = the bottom floor
      // The floor slab: a thin glassy plate in the layer's color, with a crisp outline and a
      // faint street grid (one block per building plot).
      const material = new THREE.MeshStandardMaterial({
        color: def.color,
        emissive: def.color,
        emissiveIntensity: 0.12,
        transparent: true,
        opacity: 0.16,
        depthWrite: false,
      });
      const slab = new THREE.Mesh(new THREE.BoxGeometry(floorSize, SLAB, floorSize), material);
      slab.position.set(p.x, p.y, 0);
      slab.add(
        new THREE.LineSegments(
          new THREE.EdgesGeometry(slab.geometry),
          new THREE.LineBasicMaterial({ color: def.color, transparent: true, opacity: 0.5 })
        )
      );
      const streets = new THREE.GridHelper(grid * CELL, grid, def.color, def.color);
      const streetMat = streets.material as THREE.LineBasicMaterial;
      streetMat.transparent = true;
      streetMat.opacity = 0.14;
      streets.position.y = SLAB / 2 + 0.02;
      slab.add(streets);
      scene.add(slab);

      // The floor's name tag, hanging off its outer front corner: left of the main tower,
      // right of the annex, so the two columns of tags never overlap. Click it to fly there.
      const tag = document.createElement("div");
      tag.className = "tw-floor";
      tag.title = `Fly to ${def.name}`;
      const name = document.createElement("b");
      name.textContent = def.name;
      const note = document.createElement("span");
      tag.append(name, note);
      tag.addEventListener("click", () => flyRef.current.floor(def.slug));
      const tagObj = new CSS2DObject(tag);
      const side = def.annex ? 1 : -1;
      tagObj.center.set(def.annex ? 0 : 1, 0.5); // the tag's inner edge touches the corner
      tagObj.position.set(side * (floorSize / 2 + 0.8), 0, floorSize / 2);
      slab.add(tagObj);
      floors.set(def.slug, { color: def.color, material, tag, note, x: p.x, y: p.y });

      // Buildings: best-connected first, from the centre of the floor outwards. Size grows
      // with connections (square root keeps small ones visible); the shape is the floor's
      // industry and the color the home country.
      const list = [...(perFloor.get(def.slug) || [])].sort((a, b) => b.degree - a.degree);
      list.forEach((node, i) => {
        const t = Math.sqrt(node.degree / maxDegree);
        const look = makeBuilding(def.slug, 1.1 + 1.3 * t, 0.6 + MAX_HEIGHT * t, new THREE.Color(countryGroup(node.country).color), windows);
        const object = look.object;
        object.position.set(p.x + cells[i].x, p.y + SLAB / 2, cells[i].z);
        object.scale.y = 0.001; // it rises when the page opens (tick)
        const key = buildingKey(node.id, def.slug);
        for (const child of object.children) {
          child.userData.key = key;
          meshes.push(child);
        }

        // The hubs get a spire with a blinking aviation light.
        const extras: THREE.MeshBasicMaterial[] = [];
        if (beaconIds.has(node.id)) {
          const spireMat = new THREE.MeshBasicMaterial({ color: "#94a3b8" });
          const spire = new THREE.Mesh(new THREE.CylinderGeometry(0.07, 0.12, 2.4, 6), spireMat);
          spire.position.y = look.top + 1.2;
          const lightMat = new THREE.MeshBasicMaterial({ color: "#ff3b3b" });
          const light = new THREE.Mesh(new THREE.SphereGeometry(0.24, 12, 8), lightMat);
          light.position.y = look.top + 2.5;
          object.add(spire, light);
          spireMat.userData.baseColor = spireMat.color.clone();
          extras.push(spireMat);
          beacons.push({ light: lightMat, key });
        }

        const labelDiv = document.createElement("div");
        labelDiv.className = "tw-name";
        labelDiv.textContent = node.id;
        const label = new CSS2DObject(labelDiv);
        label.center.set(0.5, 1); // bottom-centre of the tag, above the logo badge
        label.position.set(0, look.top + 2.9, 0);
        label.visible = false;
        object.add(label);
        scene.add(object);
        buildings.set(key, {
          node,
          floor: def.slug,
          look,
          extras,
          object,
          topY: look.top,
          top: new THREE.Vector3(object.position.x, object.position.y + look.top, object.position.z),
          rank,
          labelDiv,
          label,
          logo: undefined,
        });
      });
    }

    const links = new THREE.Group();
    scene.add(links);
    const state: SceneState = {
      camera,
      buildings,
      floors,
      links,
      pulses: null,
      annexX,
      view: { lit: null, edges: [], labels: new Set(), notes: {} },
      focusKey: null,
      hoverKey: null,
      now: 0,
      pop: null,
    };
    stateRef.current = state;

    // Flying: glide the camera and its target to a new spot, easing in and out.
    const clock = new THREE.Clock();
    let flight: { from: THREE.Vector3; to: THREE.Vector3; fromT: THREE.Vector3; toT: THREE.Vector3; start: number } | null = null;
    const flyTo = (to: THREE.Vector3, toTarget: THREE.Vector3) => {
      touched = true;
      controls.autoRotate = false;
      flight = { from: camera.position.clone(), to, fromT: controls.target.clone(), toT: toTarget, start: clock.getElapsedTime() };
    };
    // Keep the current viewing angle, only closer — and at least this steep, to look down onto it.
    const approach = (point: THREE.Vector3, distance: number, minRise: number) => {
      const dir = camera.position.clone().sub(controls.target).normalize();
      if (dir.y < minRise) {
        dir.y = minRise;
        dir.normalize();
      }
      return point.clone().add(dir.multiplyScalar(distance));
    };
    flyRef.current = {
      home: () => flyTo(home(), target.clone()),
      building: (key) => {
        const b = buildings.get(key);
        if (b) flyTo(approach(b.top, 24, 0.35), b.top.clone());
      },
      floor: (slug) => {
        const f = floors.get(slug);
        if (!f) return;
        const centre = new THREE.Vector3(f.x, f.y + 2, 0);
        flyTo(approach(centre, 60, 0.6), centre);
      },
    };

    // Hover = tooltip + a brighter building, click (not drag) = pick that company,
    // click on empty space = clear.
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const hitTest = (e: PointerEvent) => {
      const r = renderer.domElement.getBoundingClientRect();
      pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(meshes, false)[0];
      return hit ? buildings.get(hit.object.userData.key) || null : null;
    };
    const setHover = (key: string | null) => {
      if (key === state.hoverKey) return;
      const before = state.hoverKey;
      state.hoverKey = key;
      if (before) paint(state, before);
      if (key) paint(state, key);
    };
    const hideTip = () => {
      if (tipRef.current) tipRef.current.hidden = true;
      setHover(null);
    };
    const onMove = (e: PointerEvent) => {
      const tip = tipRef.current;
      if (!tip) return;
      const b = e.buttons ? null : hitTest(e); // no tooltip while dragging
      renderer.domElement.style.cursor = b ? "pointer" : "";
      if (!b) return hideTip();
      setHover(buildingKey(b.node.id, b.floor));
      const floor = FLOORS.find((f) => f.slug === b.floor);
      const product = b.node.products.find((p) => (p.layer || p.domain) === b.floor)?.product;
      const line = (cls: string, text: string) => {
        const d = document.createElement("div");
        d.className = cls;
        d.textContent = text;
        return d;
      };
      tip.replaceChildren(
        line("tw-tip-name", b.node.id),
        line("tw-tip-sub", [b.node.ticker, countryGroup(b.node.country).name].filter(Boolean).join(" · ")),
        line("tw-tip-floor", floor ? floor.name : b.floor),
        ...(product ? [line("tw-tip-product", product)] : []),
        line("tw-tip-sub", `${b.node.degree} connections · ${b.node.chains.length} chains`)
      );
      tip.hidden = false;
      const r = host.getBoundingClientRect();
      tip.style.left = `${Math.min(e.clientX - r.left + 14, r.width - 270)}px`;
      tip.style.top = `${e.clientY - r.top + 14}px`;
    };
    let down: { x: number; y: number } | null = null;
    const onDown = (e: PointerEvent) => {
      down = { x: e.clientX, y: e.clientY };
    };
    const onUp = (e: PointerEvent) => {
      const moved = down ? Math.hypot(e.clientX - down.x, e.clientY - down.y) : 99;
      down = null;
      if (moved > 5) return; // that was a drag to rotate, not a click
      const b = hitTest(e);
      pickRef.current(b ? b.node.id : null);
    };
    const canvas = renderer.domElement;
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("pointerleave", hideTip);

    // Keep the canvas the size of its box.
    const resize = () => {
      const w = host.clientWidth;
      const h = Math.max(1, host.clientHeight);
      renderer.setSize(w, h);
      composer.setSize(w, h);
      labelRenderer.setSize(w, h);
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      if (!touched) camera.position.copy(home()); // re-fit until the user takes over
    };
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    // Draw every frame: fly, raise the city on arrival, make newly lit buildings jump, blink
    // the beacons, move the dots supplier → customer, and a few times a second decide which
    // nearby buildings show who they are.
    let frame = 0;
    let lastDetail = -1;
    let risen = false;
    const dot = new THREE.Object3D(); // scratch object for placing the moving dots
    const tick = () => {
      frame = requestAnimationFrame(tick);
      const t = clock.getElapsedTime();
      state.now = t;
      if (flight) {
        const k = Math.min(1, (t - flight.start) / FLY_SECONDS);
        const e = easeInOut(k);
        camera.position.lerpVectors(flight.from, flight.to, e);
        controls.target.lerpVectors(flight.fromT, flight.toT, e);
        if (k === 1) flight = null;
      }
      controls.update();

      if (!risen) {
        risen = true;
        for (const b of buildings.values()) {
          const k = Math.min(1, Math.max(0, (t - 0.3 - b.rank * RISE_STAGGER) / RISE_SECONDS));
          b.object.scale.y = Math.max(0.001, easeOutBack(k));
          if (k < 1) risen = false;
        }
      } else if (state.pop) {
        const done = t - state.pop.at > POP_SECONDS + 0.4;
        for (const key of state.pop.keys) {
          const b = buildings.get(key);
          if (!b) continue;
          const k = Math.min(1, Math.max(0, (t - state.pop.at - b.rank * 0.025) / POP_SECONDS));
          b.object.scale.y = done ? 1 : 1 + 0.22 * Math.sin(Math.PI * k);
        }
        if (done) state.pop = null;
      }

      const blink = Math.sin(t * 3) > 0.2 ? 1 : 0.25;
      for (const { light, key } of beacons) {
        const k = !state.view.lit || state.view.lit.has(key) ? blink : 0.12; // a faded hub does not blink
        light.color.setRGB(k, 0.23 * k, 0.23 * k);
      }
      if (state.pulses) {
        // Each dot sits at its own point along its link (the 0.137 offsets keep them out of step).
        const { mesh, curves } = state.pulses;
        curves.forEach((curve, i) => {
          dot.position.copy(curve.getPoint((t * 0.3 + i * 0.137) % 1));
          dot.updateMatrix();
          mesh.setMatrixAt(i, dot.matrix);
        });
        mesh.instanceMatrix.needsUpdate = true;
      }
      if (t - lastDetail > DETAIL_EVERY) {
        lastDetail = t;
        updateDetail(state);
      }
      if (glowRef.current) composer.render();
      else renderer.render(scene, camera);
      // The logo badges (layer 1) go on top afterwards, outside the glow, so a white badge
      // stays a crisp logo instead of blooming into a white blob. The sky is held back for
      // this pass, or it would paint over the finished picture.
      renderer.autoClear = false;
      scene.background = null;
      camera.layers.set(1);
      renderer.render(scene, camera);
      camera.layers.set(0);
      scene.background = sky;
      renderer.autoClear = true;
      labelRenderer.render(scene, camera);
    };
    tick();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("pointerleave", hideTip);
      scene.traverse((o) => {
        const m = o as THREE.Mesh;
        m.geometry?.dispose();
        const mats = Array.isArray(m.material) ? m.material : m.material ? [m.material] : [];
        mats.forEach((x) => x.dispose());
      });
      windows.dispose();
      sky.dispose();
      composer.dispose();
      renderer.dispose();
      host.removeChild(renderer.domElement);
      host.removeChild(labelRenderer.domElement);
      stateRef.current = null;
    };
  }, [nodes]);

  // ── 2. Restyle for the current view (a chain, a compare, a mode or a company) ──
  useEffect(() => {
    const st = stateRef.current;
    if (st) applyView(st, view);
  }, [view, nodes]);

  // ── 3. Fly to the picked company; a new overview flies back to see it all ──
  useEffect(() => {
    const st = stateRef.current;
    if (!st) return;
    st.focusKey = focusKey;
    updateDetail(st);
    if (focusKey) flyRef.current.building(focusKey);
  }, [focusKey, nodes]);

  const firstOverview = useRef(true);
  useEffect(() => {
    if (firstOverview.current) {
      firstOverview.current = false; // the page opening is not a pick
      return;
    }
    flyRef.current.home();
  }, [overviewKey]);

  return (
    <div className="tw-stage" ref={hostRef}>
      <div className="tw-tip" ref={tipRef} hidden />
      <div className="tw-tools">
        <button type="button" onClick={() => setGlow(!glow)} aria-pressed={glow} title="Glow effect (off = faster)">
          {glow ? "✨ Glow on" : "Glow off"}
        </button>
        <button type="button" onClick={() => flyRef.current.home()}>
          Reset view
        </button>
      </div>
    </div>
  );
}

// One building's look for the current view and hover: faded, normal, lit or hovered, in its
// country's color or the view's mode color. A faded building becomes a dark silhouette — still
// opaque, which draws far faster than hundreds of see-through buildings.
function paint(st: SceneState, key: string) {
  const b = st.buildings.get(key);
  if (!b) return;
  const on = !st.view.lit || st.view.lit.has(key);
  const tint = on ? st.view.tint?.get(key) : undefined;
  const mode = tint ? new THREE.Color(tint) : null;
  for (const m of b.look.all) {
    const s = m as THREE.MeshStandardMaterial;
    if (mode) s.color.copy(mode).multiplyScalar(m.userData.shade as number);
    else s.color.copy(m.userData.baseColor as THREE.Color);
    if (!on) s.color.multiplyScalar(0.18);
    // Only the glowing parts (walls, accents — they carry a base glow) take the mode color as light.
    if (m.userData.glow !== undefined) s.emissive.copy(mode || (m.userData.baseEmissive as THREE.Color));
  }
  for (const m of b.extras) m.color.copy(m.userData.baseColor as THREE.Color).multiplyScalar(on ? 1 : 0.18);
  const factor = !on ? GLOW.dim : key === st.hoverKey ? GLOW.hover : st.view.lit ? GLOW.lit : GLOW.normal;
  for (const m of b.look.glow) m.emissiveIntensity = (m.userData.glow as number) * factor;
}

// Level of detail: the view's own name tags, plus — as you zoom in — the nearest lit
// buildings' logo badges (a name tag for the few without a logo; both would crowd the
// view). In signal mode the near ones show their name with the signal symbols instead.
// The picked company always shows its logo and its name.
function updateDetail(st: SceneState) {
  const near: [string, number][] = [];
  for (const [key, b] of st.buildings) {
    if (st.view.lit && !st.view.lit.has(key)) continue; // faded buildings stay quiet
    const d = st.camera.position.distanceTo(b.top);
    if (d < NEAR) near.push([key, d]);
  }
  near.sort((a, b) => a[1] - b[1]);
  const close = new Set(near.slice(0, NEAR_TAGS).map(([key]) => key));
  const markMode = !!st.view.marks;
  for (const [key, b] of st.buildings) {
    const focus = key === st.focusKey;
    const isNear = close.has(key);
    const hasLogo = !!b.node.logo;
    b.label.visible = st.view.labels.has(key) || focus || (isNear && (!hasLogo || markMode));
    const showLogo = hasLogo && (focus || (isNear && !markMode));
    if (showLogo && b.logo === undefined) b.logo = makeLogo(b);
    if (b.logo) b.logo.visible = showLogo;
  }
}

// The logo badge floating over a building (a sprite always faces the camera). It lives on
// layer 1, drawn on top after the glow pass (see tick), like the name tags.
function makeLogo(b: Building): THREE.Sprite | null {
  if (!b.node.logo) return null;
  const sprite = new THREE.Sprite(
    new THREE.SpriteMaterial({
      map: logoTexture(b.node.logo, b.node.logoBg === "dark"),
      transparent: true,
      depthWrite: false,
      depthTest: false,
    })
  );
  sprite.layers.set(1);
  sprite.scale.set(3, 1.5, 1);
  sprite.position.set(0, b.topY + 1.6, 0);
  b.object.add(sprite);
  return sprite;
}

function applyView(st: SceneState, view: TowerView) {
  st.view = view;
  for (const [key, b] of st.buildings) {
    paint(st, key);
    const mark = view.marks?.get(key);
    b.labelDiv.textContent = mark ? `${mark} ${b.node.id}` : b.node.id;
  }
  // The buildings this view lights up make a little jump (not on the plain overview). A jump
  // still running from the previous view is settled first.
  if (st.pop) for (const key of st.pop.keys) st.buildings.get(key)?.object.scale.setY(1);
  st.pop = view.lit ? { at: st.now, keys: new Set(view.lit) } : null;

  // Floor tags: the note after the name; a bottleneck floor glows amber.
  for (const [slug, f] of st.floors) {
    const note = view.notes[slug];
    f.note.textContent = note ? ` · ${note.text}` : "";
    f.tag.classList.toggle("warn", !!note?.warn);
    f.tag.classList.toggle("dim", !!view.lit && !note);
    f.material.emissive.set(note?.warn ? "#f59e0b" : f.color);
    f.material.emissiveIntensity = note?.warn ? 0.6 : 0.12;
    f.material.opacity = note?.warn ? 0.3 : 0.16;
  }

  // Links: rebuilt for every view. The tubes of one color are merged into a single mesh and
  // all the moving dots share one instanced mesh, so a 200-link chain draws in a few calls.
  for (const child of [...st.links.children]) {
    const m = child as THREE.Mesh;
    m.geometry.dispose();
    (m.material as THREE.Material).dispose();
    st.links.remove(child);
  }
  st.pulses = null;
  const tubesByColor = new Map<string, THREE.BufferGeometry[]>();
  const curves: THREE.QuadraticBezierCurve3[] = [];
  for (const e of view.edges) {
    const a = st.buildings.get(e.from);
    const b = st.buildings.get(e.to);
    if (!a || !b || a === b) continue;
    // Bow each link outwards, away from its tower's centre line, so it arcs around the
    // floors instead of cutting straight through them. The taller the climb, the wider the arc.
    const mid = a.top.clone().lerp(b.top, 0.5);
    const axisX = mid.x > st.annexX / 2 ? st.annexX : 0;
    const out = new THREE.Vector3(mid.x - axisX, 0, mid.z);
    if (out.lengthSq() < 1e-6) out.set(0, 0, 1);
    out.normalize().multiplyScalar(4 + Math.abs(a.top.y - b.top.y) * 0.3);
    const control = mid.clone().add(out);
    control.y += 1.5;
    const curve = new THREE.QuadraticBezierCurve3(a.top.clone(), control, b.top.clone());
    const list = tubesByColor.get(e.color) || tubesByColor.set(e.color, []).get(e.color)!;
    list.push(new THREE.TubeGeometry(curve, 32, 0.11, 6, false));
    curves.push(curve);
  }
  for (const [color, list] of tubesByColor) {
    const merged = mergeGeometries(list);
    list.forEach((g) => g.dispose());
    if (merged) st.links.add(new THREE.Mesh(merged, new THREE.MeshBasicMaterial({ color })));
  }
  if (curves.length) {
    const dots = new THREE.InstancedMesh(
      new THREE.SphereGeometry(0.22, 10, 8),
      new THREE.MeshBasicMaterial({ color: "#dbeafe" }),
      curves.length
    );
    st.links.add(dots);
    st.pulses = { mesh: dots, curves };
  }

  updateDetail(st);
}
