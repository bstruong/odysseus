# Workstation Local AI Architecture Blueprint & Roadmap
**Target Platform:** Intel Haswell Core i7-4790K (4c/8t) + AMD Radeon RX 7600 (8GB GDDR6)  
**Operating System:** CachyOS (Linux x86-64-v3)  
**Acceleration Engine:** Native `llama-server` (Vulkan / Mesa RADV Backend)  
**Workstation Role:** 100% VRAM Fully Private General AI (Document RAG, Vision OCR, Automations, Writing)

---

## 1. Executive Summary & The Zero-Spillover Mandate

This architecture is engineered around one non-negotiable physical constraint:
```
           GDDR6 VRAM Bandwidth:  288 GB/s   ======================>  40–55 tokens/sec
vs.
           Host DDR3 Bandwidth:    21 GB/s   ====>                     2–4 tokens/sec
           PCIe 3.0 x8 Bus:       7.9 GB/s   ==> (Bottleneck bridge)
```

On a Haswell platform with dual-channel DDR3 memory, **any model weight layer or KV cache block that spills into system RAM degrades token generation speed by 90–95%**. 

To deliver a snappy, modern workstation experience:
* **All model weights, attention matrices, and KV context caches MUST fit 100% inside the RX 7600's 8GB GDDR6 VRAM.**
* Layer offloading to CPU is strictly banned (`-ngl 99`).
* The system is tuned for high-throughput prompt prefill (800–1,100+ t/s) and sub-second time-to-first-token on document RAG.

---

## 2. 8GB VRAM Budget Breakdown & Mathematical Derivation

The RX 7600 provides **8,192 MB** of physical GDDR6 memory. Here is the strict partition budgeting:

```
+-------------------------------------------------------------------------------+
|                        TOTAL RX 7600 VRAM: 8,192 MB                           |
+--------------------------------------+--------------------+-------------------+
| Model Weights (100% Resident)        | KV Context Cache   | Buffers & Display |
| ~5,800 MB – 6,400 MB                 | ~1,100 – 1,400 MB  | ~500 – 600 MB     |
+--------------------------------------+--------------------+-------------------+
```

### A. Memory Allocation Matrix by Model Class

| Model Architecture | Parameter Size | Quantization Format | Weights Footprint | Target Context (Tokens) | KV Cache Type | KV Footprint | Vulkan Headroom | 100% VRAM Fit? |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Gemma 4 QAT 12B** | 11.9B | QAT (4-bit effective) | **6,200 MB** | 16,384 (16k) | Q4 / Q2 | **1,150 MB** | ~650 MB | **YES (7.9 GB)** |
| **Qwen 2.5 7B** | 7.6B | Q4_K_M | **4,700 MB** | 32,768 (32k) | Q4 / Q2 | **1,450 MB** | ~1,850 MB | **YES (6.3 GB)** |
| **Llama 3.1 8B** | 8.0B | Q4_K_M | **4,900 MB** | 32,768 (32k) | Q4 / Q2 | **1,500 MB** | ~1,600 MB | **YES (6.5 GB)** |
| **Gemma 4 E4B Vision** | 8.0B + mmproj | Q4_K_M + FP16 proj | **5,800 MB** | 16,384 (16k) | Q4 / Q2 | **1,100 MB** | ~1,100 MB | **YES (7.1 GB)** |
| **Gemma 4 E2B Vision** | 2.5B + mmproj | Q4_K_M + FP16 proj | **2,800 MB** | 8,192 (8k) | Q8 / Q8 | **500 MB** | ~4,700 MB | **YES (3.4 GB)** |
| **Qwen 3 Embed** | 0.6B | Q8_0 | **850 MB** | 8,192 (8k) | N/A (Embed) | N/A | ~7,200 MB | **YES (0.9 GB)** |

### B. KV Context Cache Compression Math (Turbo Quant / Q4-Q2)
Standard 16-bit float KV cache consumes:
$$\text{Memory per Token} = 2 \times \text{layers} \times \text{kv\_heads} \times \text{head\_dim} \times 2\text{ bytes}$$
For a 12B model at 16k context, uncompressed FP16 KV cache requires **~4.8 GB of VRAM** (causing immediate Out-of-Memory on an 8GB card).

By applying **4-bit Keys and 2-bit Values (`--cache-type-k q4_0 --cache-type-v q2_k`)**:
* Average bytes per parameter drops from **2.0 B to ~0.45 B** (a 77% reduction).
* 16k context window on Gemma 4 drops from **4.8 GB to only 1.15 GB**.
* Result: A full 16,384-token document can be evaluated completely within VRAM.

---

## 3. Low-Level `llama-server` Optimization Knobs

The launch script (`scripts/serve-rx7600.sh`) enforces these exact hardware-level flags:

1. **`--n-gpu-layers 99` (`-ngl 99`)**:
   Forces every transformer block, embedding layer, and final output projection into GDDR6 VRAM.
2. **`--no-mmap`**:
   Pre-loads model weights directly into memory on initialization. Prevents on-demand SATA SSD page-faulting during long document reads.
3. **`--mlock`**:
   Locks allocated pages via Linux `IPC_LOCK`, preventing the OS kernel from paging GPU staging buffers to disk swap.
4. **`--threads 3` (Physical Haswell Cores - 1)**:
   The Core i7-4790K has 4 physical cores (8 hyperthreads). Assigning 3 generation threads leaves 1 physical core completely idle for the CachyOS kernel, Wayland/desktop compositor, and GPU driver interrupt dispatching.
5. **`--ubatch 1024` & `--batch-size 2048`**:
   Maximizes physical compute occupancy during prompt prefill, driving prefill throughput to **800–1,100+ tokens/sec** when ingesting multi-page PDF documents.
6. **`--cache-prompt` & `--cache-reuse 256`**:
   Enables 256-token context chunk cache reuse. When a user asks follow-up questions about a document, only the new query delta is processed; the document prefix remains cached in VRAM.
7. **`--spec-type draft-mtp --spec-draft-n-max 3`**:
   Enables Multi-Token Prediction draft heads on supported architectures, predicting 2–3 tokens ahead to boost decode generation speeds on GPU-bound models.

---

## 4. General-Purpose Client Harness Architecture

The client stack consists of three complementary, lightweight applications:

```
                           +----------------------------------------+
                           |  llama-server (http://127.0.0.1:8080)  |
                           |   100% VRAM - AMD Radeon RX 7600 8GB   |
                           +-------------------+--------------------+
                                               |
                  +----------------------------+---------------------------+
                  |                                                        |
    +-------------v-------------+                           +--------------v-------------+
    |       AnythingLLM         |                           |      n8n Automation        |
    |  - Host Network (port 3001)|                           |  - Docker Bridge (:5678)   |
    |  - Embedded LanceDB RAG   |                           |  - On-Demand Email Triage  |
    |  - Private PDF & Doc Q&A  |                           |  - Boot Catchup Batches    |
    +---------------------------+                           +----------------------------+
```

### 1. Document RAG: AnythingLLM (Docker `network_mode: host`)
* **Endpoint**: `http://localhost:3001`
* **Vector Store**: **LanceDB** (embedded, disk-backed, zero background daemon memory overhead).
* **Role**: Private document management. Ingests PDFs, Word docs, spreadsheets, and web pages with strict source attribution citations.
* **Embeddings**: Ingested via local `qwen3-embed` running on `llama-server`.

### 2. Token-Efficient Assistant: Pythagoras
* **Role**: Headless personal assistant for Telegram/Discord alerts, morning briefings, and calendar synthesis.
* **Memory**: **Understory** pluggable MCP memory (hierarchical Markdown storage, zero continuous database polling).
* **Anti-Loop Policy**: Strictly event-driven. Completely sleeps until triggered by a webhook or cron job, avoiding CPU-wasting 30-second poll loops.

### 3. Workflow Automations: n8n
* **Endpoint**: `http://localhost:5678`
* **Role**: On-boot catchup and scheduled batch tasks (e.g., fetching emails, classifying priority messages, organizing downloads).
* **Execution**: Connects to `llama-server` via standard OpenAI chat completion nodes.

---

## 5. Deployment & Operating System Setup (CachyOS)

### A. GPU Drivers & Vulkan Validation
CachyOS includes the latest Mesa RADV driver. Verify that Vulkan detects the RX 7600:
```bash
sudo pacman -S vulkan-radeon vulkan-tools
vulkaninfo | grep -E "deviceName|driverVersion"
# Expected: "AMD Radeon RX 7600", Mesa driver
```

### B. Linux Group Permissions
Ensure your user account can open the GPU render node:
```bash
sudo usermod -aG render,video $USER
```

### C. Host Memory Locking Limits
Allow `llama-server` to lock memory allocations (`--mlock`):
Add the following line to `/etc/security/limits.conf`:
```
brian   soft   memlock   unlimited
brian   hard   memlock   unlimited
```

### D. BIOS Configuration (MSI Z97 PC Mate)
1. **Above 4G Decoding**: Enable in BIOS settings (Settings -> Advanced -> PCI Subsystem Settings).
2. **Restore on AC Power Loss**: Set to **"Power On"** or **"Last State"** so the workstation auto-reboots after a power outage.
3. **PCIe Speed**: Ensure Gen 3 is selected.

### E. Secure Remote Access via Tailscale
Install Tailscale to securely access your AnythingLLM instance from your phone or laptop outside your home:
```bash
sudo pacman -S tailscale
sudo systemctl enable --now tailscaled
sudo tailscale up
```

---

## 6. Quick-Start Execution Guide

1. **Launch the 100% VRAM Model Server**:
   ```bash
   cd /home/brian/odysseus/workstation_ai
   ./scripts/serve-rx7600.sh gemma4-qat-12b
   ```
2. **Start the Client Applications**:
   ```bash
   cd /home/brian/odysseus/workstation_ai
   docker compose up -d
   ```
3. **Open the User Interface**:
   * **AnythingLLM (Document RAG)**: `http://localhost:3001`
   * **n8n (Workflows)**: `http://localhost:5678`
   * **llama-server API**: `http://localhost:8080/v1`
