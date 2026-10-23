# Odysseus Homelab Setup: Shared On-Demand GPU Inference (JARVIS)

## 1. Overview & Architecture

In the self-hosted homelab environment, GPU inference is centralized on **Watchtower** (AM5 host with NVIDIA GPU) running under **k3s**.

Instead of individual applications running private, always-on LLM daemons, a single shared engine—**JARVIS** (`manifests/watchtower/jarvis/` in `homelab-k3s`)—serves all client applications:
* **Alpha** (pi harness agent)
* **Beta** (finance / background tasks)
* **Assassin** (vault & personal ledger)
* **Omega** (remote pi sessions)
* **Odysseus** (personal AI workspace: notes, calendar, email, deep research)

```
                            +-----------------------------------------------+
                            |            Watchtower (AM5 + GPU)             |
                            |   JARVIS (llama.cpp router · models.ini SoT)  |
                            |     • Default: replicas 0 (Sleepy-Warm)       |
                            |     • Dynamic Model Swapping (--models-max 1) |
                            +-----------------------+-----------------------+
                                                    |
          +-------------------------+---------------+-------------------------+
          |                         |                                         |
+---------v---------+     +---------v---------+                     +---------v---------+
|     Odysseus      |     |   Alpha / Beta    |                     |   Omega / Others  |
| (Personal Hub)    |     | (Agents & Tasks)  |                     | (Interactive Pi)  |
|-------------------|     |-------------------|                     |-------------------|
| • LLM Client      |     | • LLM Client      |                     | • LLM Client      |
| • Pollers: OFF    |     | • Event-Driven    |                     | • Lease-Aware     |
+-------------------+     +-------------------+                     +-------------------+
```

---

## 2. The On-Demand / Sleepy-Warm Contract

All homelab applications sharing Watchtower adhere to the following rules:

1. **Sleepy-Warm Lifecycle (Cold by Default):**
   - JARVIS defaults to `replicas: 0`.
   - The `jarvis-idle-sleep` CronJob inspects llama.cpp token metrics every 10 minutes. If no requests occur for ~60 minutes and no lease is held, JARVIS scales down to 0 to park the GPU and reduce thermal/power load.
2. **Dynamic Swapping (`--models-max 1`):**
   - Only **one** model lives in VRAM at any time. When an app requests a different model preset, the router unloads the previous model and loads the requested GGUF.
3. **Zero In-Process Polling:**
   - Background tasks must **not** run continuous inference loops that perpetually ping the engine and reset the idle timer.
4. **Exclusive Leasing for Batch Jobs:**
   - Long-running, multi-step operations (e.g. extensive deep research or mass document indexing) should acquire a lease to prevent the model from being swapped out or scaled down mid-job.

---

## 3. Odysseus Client Configuration

Configure your Odysseus `.env` (or Docker environment) to connect to JARVIS:

```env
# -----------------------------------------------------------------------------
# LLM Endpoint Routing
# -----------------------------------------------------------------------------
# When running on the local LAN:
LLM_HOST=ai.watchtower.local

# When running in-cluster on k3s:
# LLM_HOST=jarvis.jarvis.svc.cluster.local:8080

# When running directly on the Watchtower node:
# LLM_HOST=127.0.0.1:8080

# -----------------------------------------------------------------------------
# Model Selection (Must match JARVIS models.ini presets)
# -----------------------------------------------------------------------------
# Primary generalist:
DEFAULT_MODEL=gemma4-12b

# Lightweight / fallback model:
FALLBACK_MODEL=gemma4-4b

# -----------------------------------------------------------------------------
# Zero-Idle Polling Mandate (CRITICAL)
# -----------------------------------------------------------------------------
# Disable continuous 30-second in-process email and task pollers to allow
# JARVIS to idle-sleep when not actively engaged by the user.
ODYSSEUS_INPROCESS_POLLERS=0
ODYSSEUS_INPROCESS_TASKS=0

# -----------------------------------------------------------------------------
# Storage & Data Directory
# -----------------------------------------------------------------------------
ODYSSEUS_DATA_DIR=/mnt/data/odysseus/data
```

---

## 4. Exclusive GPU Leasing for Heavy Tasks

When running extensive deep research or large document batches through Odysseus:

```bash
# 1. Acquire an exclusive lease (e.g. 60 minutes) from any machine with kubectl:
~/Projects/homelab-k3s/scripts/jarvis-lease.sh acquire odysseus-deep-research 60

# 2. Check lease status:
~/Projects/homelab-k3s/scripts/jarvis-lease.sh show

# 3. Perform the deep research / batch work in Odysseus

# 4. Release the lease when finished:
~/Projects/homelab-k3s/scripts/jarvis-lease.sh release
```

While a lease is active:
* The `jarvis-idle-sleep` CronJob is blocked from scaling down the engine.
* Peer projects checking lease status can back off or fail gracefully.

---

## 5. Verification & Smoke Testing

### Test Connection to JARVIS
From the Odysseus host:
```bash
curl -s http://ai.watchtower.local/v1/models | jq .
```

### Start Odysseus
```bash
python app.py
# or docker compose up -d
```
Verify via `http://localhost:7011` that:
1. The UI connects and lists `gemma4-12b` as the active model.
2. Background logs do not emit continuous polling loops when the app is idle.
