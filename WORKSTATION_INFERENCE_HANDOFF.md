# Agent Handoff: Local AI Workstation Architecture & Strategy
**Target Hardware:** Intel Haswell Core i7-4790K (4c/8t, AVX2) + AMD Radeon RX 7600 (8GB GDDR6)  
**Host Operating System:** CachyOS (Linux `x86-64-v3`)  
**Target Application:** Odysseus (Personal AI Workspace) + Satellite Tools  
**Handoff Scope:** Everything a successor agent needs to immediately continue or deploy this workstation setup.

---

## 1. Core Mission & Critical Architectural Rules

### A. The Zero-Spillover Mandate (Non-Negotiable)
```
  RX 7600 GDDR6 Bandwidth:  288 GB/s   =====================>  40–55 tokens/sec
vs.
  Haswell DDR3 Bandwidth:    21 GB/s   ====>                    2–4 tokens/sec
  PCIe 3.0 x8 Bus:          7.9 GB/s   ==> (Bottleneck)
```
* **Rule**: Because Haswell dual-channel DDR3 memory bandwidth (~21 GB/s) is ~14x slower than the GPU, **any model weight or KV cache block that spills into system RAM degrades token generation speed by 90–95%**.
* **Requirement**: All model weights, vision projectors, and active KV context caches **MUST fit 100% inside the RX 7600's 8GB VRAM** (`-ngl 99`). CPU layer offload is strictly banned.

### B. Project Scope: General Use Only (No Coding)
* **Odysseus is strictly for personal general productivity**: Email triage/drafting, calendar, notes, SearXNG Deep Research, and document editing.
* **No coding models or coding workflows** are required on the local workstation.
* **Development Strategy**: The user has **Cursor Pro** and **Antigravity 2.0 (Google AI Pro)** subscriptions. All code writing, refactoring, and planning are performed by cloud agents. The local Haswell workstation acts purely as an execution runtime (running git, FastAPI server, and targeted tests).

---

## 2. Hardware Profile & System Configuration

| Component | Specification | Agent Implications |
| :--- | :--- | :--- |
| **CPU** | Intel Core i7-4790K (4c/8t, Haswell, AVX2, LGA1150) | Set `llama-server` to `--threads 3` (cores - 1). Leaves 1 physical core for OS/I/O. |
| **Motherboard** | MSI Z97 PC Mate (PCIe 3.0 x16, SATA III) | RX 7600 runs at **PCIe 3.0 x8** (~7.9 GB/s). Enable **Above 4G Decoding** in BIOS. |
| **RAM** | 32GB DDR3 (4x8GB, dual-channel, ~21 GB/s) | High capacity, but bandwidth-bound. Never offload active inference layers here. |
| **GPU** | AMD Radeon RX 7600 (8GB GDDR6, Navi 33 / `gfx1102`) | Total budget: 8,192 MB. Use Vulkan backend (`vulkan-radeon` / Mesa RADV). |
| **OS** | CachyOS (Arch-based Linux) | Native `x86-64-v3` AVX2 binaries, BORE scheduler, up-to-date Mesa Vulkan stack. |
| **Storage: OS** | Samsung 850 EVO 120GB SATA SSD | **Warning**: OS root `/` only. Keep Docker data-root off this drive! |
| **Storage: Data** | Samsung 870 QVO 2TB SATA SSD (`/mnt/data`) | Place Docker data-root (`/mnt/data/docker`), GGUFs, and app storage here. |
| **Storage: Archive**| Seagate 1TB HDD (`/mnt/archive`) | Cold backups, database snapshots. |

---

## 3. Inference Engine: Native `llama-server` via Vulkan

We explicitly chose **`llama.cpp` (`llama-server`) with Vulkan (`GGML_VULKAN=1`)** over Ollama or ROCm:

### Why Vulkan Beats ROCm on This Platform
1. **Navi 33 Support**: AMD does not officially enable consumer Navi 33 (`gfx1102`) in standard ROCm runtimes without fragile `HSA_OVERRIDE_GFX_VERSION=11.0.0` environment variables.
2. **Rolling Kernel Stability**: CachyOS updates kernels frequently. ROCm DKMS modules frequently break across kernel updates. **Mesa RADV Vulkan never breaks**.
3. **Performance**: For 7B–8B models, Vulkan matches ROCm performance within 3–5%.

### Low-Level Flag Mandate
When starting `llama-server`, the following flags must always be enforced:
* `-ngl 99`: 100% layer offload to VRAM.
* `--no-mmap`: Pre-loads weights upfront into memory; eliminates SATA SSD page-fault latency during document reads.
* `--mlock`: Memory locks allocations to prevent kernel disk swapping.
* `--threads 3`: Prevents hyperthreading thrashing on Haswell AVX2 units.
* `--ubatch 1024` & `--batch-size 2048`: Scales prompt prefill to **800–1,100+ tokens/sec**.
* `--cache-type-k q4_0 --cache-type-v q2_k` (or `q4_0`): 77% KV compression, fitting 16k–32k context windows inside ~1.2 GB of VRAM.
* `--cache-prompt --cache-reuse 256`: 256-token chunk prefix caching (multi-turn turns reprocess only query deltas).

---

## 4. Model Selection (Strictly < 8GB VRAM Envelope)

Any model selected must adhere to:  
$$\text{Model Weights} + \text{KV Context Cache} + \text{Vulkan Buffers} \le 8,192\text{ MB}$$

| Model | Quant | Weights | Context | KV Type | Total VRAM | Role in Odysseus |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Qwen 2.5 7B Instruct** | Q4_K_M | **4.7 GB** | 32,768 (32k) | Q4 / Q2 (~1.4 GB) | **~6.5 GB** | **Primary Daily Driver**: Best reasoning, tool-calling, and RAG. |
| **Llama 3.1 8B Instruct** | Q4_K_M | **4.9 GB** | 32,768 (32k) | Q4 / Q2 (~1.5 GB) | **~6.7 GB** | **Email & Prose**: Natural tone for drafting correspondence and notes. |
| **Gemma 4 QAT 12B** | QAT-Q4 | **6.2 GB** | 16,384 (16k) | Q4 / Q2 (~1.2 GB) | **~7.8 GB** | **Analytical Heavyweight**: Near-BF16 quality at Q4 footprint. |
| **Gemma 4 E4B Vision** | Q4_K_M | **5.8 GB** | 16,384 (16k) | Q4 / Q2 (~1.1 GB) | **~7.2 GB** | **Multimodal / OCR**: Reading charts, scanned PDFs, and screenshots. |
| **Qwen 2.5 3B Instruct** | Q4_K_M | **2.2 GB** | 16,384 (16k) | Q8 (~0.8 GB) | **~3.2 GB** | **Speed Router (80–110 t/s)**: Instant email tagging & search query rewriting. |
| **Qwen 3 Embedding** | Q8_0 | **0.8 GB** | 8,192 (8k) | N/A | **~0.9 GB** | **Vector RAG**: Indexing document chunks into LanceDB/ChromaDB. |

> **Banned on this hardware**: 14B models (e.g. Qwen 14B ~9GB weights) and MoE models (Mixtral 8x7B, Qwen 35B, GLM 23B). They will breach 8GB VRAM and trigger the DDR3 bottleneck.

---

## 5. Odysseus Configuration & Integration

In the Odysseus root directory (`/home/brian/odysseus/.env`):

```env
# Point to local 100% VRAM llama-server
LLM_HOST=localhost
OPENAI_BASE_URL=http://localhost:8080/v1

# Disable battery/CPU-wasting 30s background email poller
ODYSSEUS_INPROCESS_POLLERS=0

# Enable compact tool schemas to minimize prompt prefill tokens
ODYSSEUS_QWEN_NATIVE_COMPACT_BUILTINS=1

# Storage Volume mapping
APP_DATA_DIR=/mnt/data/odysseus/data
```

---

## 6. Ecosystem & Satellite Projects Map

The user’s workspace contains several related but strictly distinct systems:

```
                            +-----------------------------------------------+
                            |     Universal 100% VRAM Local Engine          |
                            |   llama-server (:8080/v1) - Vulkan / RX 7600  |
                            +-----------------------+-----------------------+
                                                    |
          +-------------------------+---------------+-------------------------+
          |                         |                                         |
+---------v---------+     +---------v---------+                     +---------v---------+
|     Odysseus      |     | Satellite Clients |                     |     Berserker     |
| (Personal AI Hub) |     | (Separate Tools)  |                     | (Agent Benchmark) |
|-------------------|     |-------------------|                     |-------------------|
| • General Use     |     | • AnythingLLM     |                     | • Pi Harness      |
| • Email & Notes   |     |   (PDF/Doc Vault, |                     | • Inspired by     |
| • SearXNG Search  |     |    LanceDB RAG)   |                     |   Pythagoras      |
| • Calendar/Tasks  |     | • n8n Automations |                     | • Understory MCP  |
| • Zero Coding     |     |   (Boot & Cron)   |                     | • Event-Driven    |
+-------------------+     +-------------------+                     +-------------------+
```

1. **Odysseus (`/home/brian/odysseus`)**:
   * Personal AI workspace (email, calendar, notes, SearXNG search, document editor).
   * Fully decoupled from coding workflows.
2. **AnythingLLM & n8n (`workstation_ai/`)**:
   * Standalone satellite services, kept separate from Odysseus.
   * `AnythingLLM`: Dedicated PDF/document vault with embedded LanceDB RAG.
   * `n8n`: Batch workflow automations on boot/cron.
3. **Berserker (`/home/brian/Projects/berserker`) & Pythagoras**:
   * Both use the **Pi harness (`@earendil-works/pi`)** as their core runtime.
   * **Pythagoras** serves as an architectural pattern for `berserker`: event-driven execution, no continuous 30s polling loops, and **Understory** pluggable hierarchical Markdown memory.
   * **`GLM-4.7-Flash-REAP-23B-A3B.gguf` (14 GB)**: Located in `berserker/experiments/models/`. Audit confirmed it has **never been benchmarked yet**. It is evaluated on the temporary RTX 3060 12GB bench to understand the GLM family, but is **not** intended for the RX 7600 8GB setup.

---

## 7. Artifacts & File Inventory

All configurations and scripts authored during this session are located in [`workstation_ai/`](file:///home/brian/odysseus/workstation_ai):

| File Path | Description |
| :--- | :--- |
| [`workstation_ai/scripts/serve-rx7600.sh`](file:///home/brian/odysseus/workstation_ai/scripts/serve-rx7600.sh) | Hardened Bash launcher for `llama-server` tuned with Vulkan, `-ngl 99`, `--no-mmap`, `--mlock`, `--ubatch 1024`, and `--threads 3`. |
| [`workstation_ai/models.ini`](file:///home/brian/odysseus/workstation_ai/models.ini) | Hardware presets for Gemma 4 QAT 12B, Qwen 2.5 7B, Llama 3.1 8B, Gemma 4 E4B Vision, and Qwen 3 Embed. |
| [`workstation_ai/docker-compose.yml`](file:///home/brian/odysseus/workstation_ai/docker-compose.yml) | Compose stack for AnythingLLM (`network_mode: host` + LanceDB) and n8n with cgroup CPU/RAM limits. |
| [`workstation_ai/config/general_settings.json`](file:///home/brian/odysseus/workstation_ai/config/general_settings.json) | Configuration profiles for AnythingLLM, Pythagoras, and n8n batch automations. |
| [`workstation_ai/WORKSTATION_ROADMAP.md`](file:///home/brian/odysseus/workstation_ai/WORKSTATION_ROADMAP.md) | Comprehensive engineering roadmap detailing VRAM budgeting math and Linux deployment steps. |

---

## 8. Quick Start for Successor Agent

To start the engine and test Odysseus on this workstation:
```bash
# 1. Start the 100% VRAM llama-server with the primary generalist preset
cd /home/brian/odysseus/workstation_ai
./scripts/serve-rx7600.sh qwen25-7b

# 2. In another terminal, start Odysseus
cd /home/brian/odysseus
python app.py
# (or docker compose up -d)

# 3. Access Odysseus UI
# Open http://localhost:7011
```
