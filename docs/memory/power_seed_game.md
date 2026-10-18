---
name: power-seed-game
description: "Standalone future-civilization game direction and deployment"
metadata:
  node_type: memory
  type: product
  modified: 2026-09-26T00:00:00-07:00
---

The user asked to turn The Power Age's AI embodiment, recursive industry, semiconductor precision and energy-scale
discussion into a game. The preferred frame is a single-civilization strategy / spread simulation, not a flat map.
The visual direction must feel futuristic: living energy field, orbit, factories, planetary grid and Dyson swarm.
The user explicitly rejected a slideshow feel and asked for more 3D motion. The Vercel version now uses a real-time
Three.js scene, with orbiting machines, a rotating planet, stellar collectors, a sun and a galaxy, plus reactions to
build and pulse actions. Keep this as a simulation scene rather than returning to static chapter backdrops.

`kardashev-scroll/dist/index.html` is the Power Seed game served by Vercel. It starts in play, in English,
and unlocks field bodies → refinery → precision fab → data-center lattice → planetary solar → orbital seed foundry →
stellar collectors → interstellar seed. Controls are click orders, Pulse/Space, reset and mouse orbit. The game logic
is in `dist/game.js`, UI in `dist/game.css` and Three.js scene in `dist/scene3d.js`. Vercel can deploy local
changes directly from the nested checkout with `NO_UPDATE_NOTIFIER=1; vercel --prod --yes --scope gijun42`; do not
commit or push unless the user explicitly asks in that turn. The cinematic Sites version stays separate.
