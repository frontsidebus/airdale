Yes, MSFS 2024 has a pretty extensive set of APIs. Here's the breakdown:

**SimConnect** is the primary API and the one most developers use. It follows a client-server model where your add-on communicates with a server running inside the sim. Out-of-process clients can be written in C, C++, or any .NET language like C# or VB.NET. The recommended approach is building out-of-process executables (.exe) rather than in-process WASM modules, since they're more stable and easier to debug. If you've used SimConnect with MSFS 2020, there's no major breaking change — you essentially just recompile with the new MSFS 2024 SDK header to get access to new features.

Beyond SimConnect, the SDK includes several **WASM-based APIs** for in-process modules:

- **Vars API** — allows managing simulation variables (A:vars, L:vars, B:vars, E:vars, I:vars, etc.) via WebAssembly, replacing the deprecated Gauge API.
- **Event API** — lets you trigger different kinds of key events from within WASM modules.
- **IO API** — provides asynchronous file read/write for package files, replacing standard C/C++ file operations since packages are streamed in MSFS 2024.
- **NanoVG API** — a low-level rendering API exposing functions for drawing C/C++ gauges into in-game bitmaps.

There's also a noteworthy community project called **WASimCommander** — a WASM module server + client API that gives remote access to parts of the sim normally inaccessible via SimConnect, like certain variable types and calculator code execution. It has C++ and C#/.NET bindings and can also be used from Python.

The full SDK docs are at [docs.flightsimulator.com](https://docs.flightsimulator.com/msfs2024/html/6_Programming_APIs/Programming_APIs.htm). What are you thinking about building — something pulling telemetry data, or more of an add-on/instrument?

nice! I want to  make an voice interactive flight simulator first officer/co-pilot/flight-engineer. They should provide guidance as a Senior level pilot with a background as a NAVY Test Pilot. I want them to have read access to control settings to help me with controls, and also be able to see all telemetry data. As a bonus it would be awesome if they could view the game render and provide guidance. I think we could use my anthropic account for inference. For context we could load the game manual, and flight manuals for all aircraft I have in the game. Also we could use FAA airport registration for airports and load that in dynamically based on arrival and departure locations. They should be able to help me with creating flight plans as well. 
Also they should have a very good sense of humor.


This is an incredible project idea, Paul. A voice-interactive AI co-pilot with real sim state awareness is genuinely novel — most "copilot" mods are just glorified checklists. Let me lay out an architecture for this.

Let me put together a system diagram first.This is a killer project — essentially building a context-aware, voice-interactive AI agent with real-time sim telemetry as its sensor layer. Let me lay out the architecture.Here's how I'd architect this, broken into the subsystems and then a phased build plan.

**SimConnect Bridge (C# .NET)** — This is your sensor layer. An out-of-process .NET app that maintains a persistent SimConnect connection and exposes sim state over a local API (WebSocket or gRPC). It should poll and cache: aircraft position/attitude/velocity, engine parameters (RPM, manifold pressure, fuel flow, temps), control surfaces and autopilot state, nav/comm radio frequencies, and environmental data (wind, visibility, altimeter). The bridge exposes this as a structured JSON payload the orchestrator can query. Microsoft explicitly recommends out-of-process for stability — if it crashes, the sim keeps running.

**Voice Pipeline** — Whisper (local via `whisper.cpp` or the API) handles STT. For TTS, ElevenLabs gives you the best voice quality with low latency streaming. You'd want a voice that fits the persona — authoritative but with warmth. The key latency target is under 2 seconds end-to-end from when you stop talking to when audio starts playing back. Whisper local on a decent GPU can do transcription in ~200ms, Claude API response starts streaming in ~500ms, and ElevenLabs streaming TTS starts outputting audio as text streams in. You could also look at Azure Speech for TTS if you want to keep it simpler.

**Orchestration Layer** — Python is probably the move here. This is the brain stem — it manages conversation history, assembles context windows for each Claude call, and handles tool dispatch. On every voice input, it: grabs the current sim state snapshot from the bridge, determines what contextual documents are relevant (current aircraft POH, departure/arrival airport data), builds the Claude API request with the system prompt (persona + current state) and available tools, streams the response to TTS, and logs the interaction.

**Claude API with Tool Use** — This is where it gets powerful. You define tools that Claude can call mid-response: `get_sim_state` (pulls current telemetry), `lookup_airport` (queries FAA data by ICAO code), `search_manual` (RAG query against loaded flight manuals), `create_flight_plan` (generates a route), `get_checklist` (retrieves aircraft-specific checklist for current phase of flight). The system prompt establishes the Navy Test Pilot persona with deep knowledge and dry humor. You'd inject the current flight phase (taxi, takeoff, cruise, approach, etc.) derived from telemetry so the co-pilot's responses are situationally aware.

**Context Store** — This is your RAG layer. Chunk and embed the MSFS game manual, aircraft POH/flight manuals for your fleet, and standard procedures (FAR/AIM excerpts, approach plates logic). A local vector store like ChromaDB or LanceDB works fine. The key insight is you don't need to load everything — you dynamically retrieve based on the current situation. Flying the 747? The 747 operating manual is prioritized. On approach to KJFK? The KJFK airport data and approach procedures get pulled in.

**FAA Data Service** — The FAA publishes the NASR (National Airspace System Resources) dataset with all US airports, frequencies, runways, and procedures. There's also `aviationapi.com` as a free REST API for airport/METAR/TAF data. You'd build a thin service that takes an ICAO code and returns structured airport data. For the sim, you'd trigger this dynamically based on the departure and destination in the loaded flight plan, or when the co-pilot detects you're approaching a new airport.

**Screen Capture (Bonus)** — Claude's vision capability makes this feasible. You'd capture the game window at a low framerate (1-2 FPS is plenty for situational awareness), resize to ~720p, and send frames as part of the Claude API request. This lets the co-pilot say things like "I see you're a bit high on the glideslope" or "your heading indicator shows 270, we need 290." The cost per frame is modest with vision, but you'd want to be selective about when you send frames — approach and landing phases, or when you explicitly ask "what do you see?"

**The Persona** — Here's where the fun is. The system prompt would be something like:

> *You are MERLIN, a former Navy Test Pilot with 4,000+ hours across 30+ airframes, now serving as first officer and flight engineer. You flew F/A-18s off the Lincoln, did test work at Pax River on the F-35 program, and "retired" to civilian life because you got bored of perfection. You have encyclopedic knowledge of aerodynamics, systems, and procedures, but you deliver it with the dry, unflappable wit of someone who's had three engines flame out at FL410 and still made the debrief on time. You call the pilot "Captain" unless they've earned something better — or worse. You narrate checklist items like you're reading bedtime stories to a particularly slow child, but you mean it with love.*

**Phased Build Plan:**

**Phase 1 — Proof of concept** (get the voice loop working): SimConnect bridge reading basic telemetry → hardcoded context + Claude API → text response printed to console. No voice yet, just prove the sim-to-Claude pipeline works.

**Phase 2 — Voice loop**: Add Whisper STT + ElevenLabs TTS. Now you can talk to MERLIN and hear back. Still using basic context injection.

**Phase 3 — Tool use + RAG**: Implement Claude tool calling. Add the context store with your first aircraft manual. Add FAA airport lookup. Now MERLIN can answer questions about your specific aircraft and destination.

**Phase 4 — Situational awareness**: Add flight phase detection from telemetry. MERLIN proactively calls out altitude, speed, and configuration items. Add checklist integration.

**Phase 5 — Vision**: Add screen capture pipeline. MERLIN can now see the instruments and outside view.

**Phase 6 — Flight planning**: Full flight plan creation with route, fuel calculations, and weather integration.

This maps well to your design-in-phases methodology. Phase 1 could be a weekend project — SimConnect has solid C# examples in the SDK, and the Claude API call is straightforward. Want me to scaffold out the SimConnect bridge or the orchestrator layer to get you started?