<p align="center">
  <img src="frontend/public/assets/SvgBot.png" alt="SvgBot" />
</p>

# svg.bot

**The most accurate image → fontless SVG converter available!** Not by picking one tracer and hoping for the best, but by running multiple vectorization engines in parallel, scoring every candidate with perceptual metrics, and iteratively **diffing, patching, and merging** corrective paths until fidelity plateaus.

SvgBot combines **StarVector** (neural im2svg, GPU), **VTracer** (classical color tracing), **DinoScore** / **LPIPS** candidate ranking, and a **residual-overlay refinement loop** on every conversion that surgically fixes whatever the base engine missed. Optional **MPP / x402** payments let autonomous agents pay per conversion.

---

## How it works

SvgBot treats vectorization as a **search-and-refine** problem, not a single pass through one algorithm.

### Phase 1 — Preprocess & classify

The input image is loaded, resized (long edge capped at 2048 px), and analyzed for **unique color count** and **edge density**. That classifies it as `logo`, `illustration`, or `photo`, which selects VTracer parameter grids and whether the smooth-curve pipeline runs.

### Phase 2 — Multi-engine candidate generation

The default engine is **`auto`**: SvgBot runs StarVector, VTracer, and VTracer smooth in parallel, ranks them by DinoScore (with an LPIPS tiebreak on logos when scores are close), and refines the winner (**best when you want maximum accuracy and can wait longer**). Pick a single engine when you know what fits:

| Engine | Best for | What it does |
|--------|----------|--------------|
| **Auto** | Maximum accuracy | Runs all engines below in parallel; keeps the highest-scoring candidate. Default. |
| **VTracer smooth** | Logos, icons, brand marks | Bilateral filter + k-means palette quantization (`clean_for_tracing`) produces flat color regions with crisp edges, then VTracer traces with a **smooth-curve grid** (`LOGO_SMOOTH_GRID`) tuned for fewer control points and cleaner splines. Still scored against the **original** image. |
| **StarVector** | Illustrations, complex artwork | A vision-language model (`starvector-1b-im2svg` or `8b`) generates SVG path markup directly from the image. Runs `k` stochastic samples (3 standard / 5 high quality); each sample is rasterized and scored. Needs a CUDA GPU. |
| **VTracer** | Photos, gradients, many colors | Classical color-region tracing on the raw image. **Auto-tune** sweeps a parameter grid (`LOGO_GRID` for logos, `DEFAULT_GRID` otherwise) and keeps the highest-scoring result. |

**Inside Auto**, three independent candidates are generated:

| Candidate | Best for | Notes |
|-----------|----------|-------|
| **StarVector** | Illustrations, complex artwork | Neural im2svg; skipped when CUDA is unavailable. |
| **VTracer** | Photos, gradients | Raw-image tracing with auto-tuned grids. |
| **VTracer smooth** | Logos, flat fills | Palette-quantized input + smooth-curve grid; skipped for photos. |

Each candidate is rasterized back to pixels and scored with:

- **DinoScore** — ResNet-50 embedding cosine distance between original and rendered SVG (higher = better perceptual match). Used as the primary ranking metric.
- **LPIPS** — AlexNet perceptual distance (reported alongside DinoScore).

All candidates are sorted by DinoScore; the winner becomes the **base SVG** for refinement.

### Phase 3 — Iterative residual diff, vectorize, merge

Every conversion runs refinement. Even the best single-pass SVG leaves pixels that don't match the source: missing letter counters, softened corners, anti-aliasing gaps, small color patches. SvgBot closes that gap with up to **20 refinement passes** (`REFINE_MAX_PASSES`, default 20).

Each pass:

1. **Rasterize** the current best SVG back to a bitmap at the source dimensions.
2. **Pixel diff** — Compute per-pixel RGB absolute difference between the original and the render. Pixels above a threshold (default 12, scaled per variant) form a boolean **residual mask**.
3. **Mask filtering** — Two filters suppress false positives:
   - **Edge exclusion** — Canny edges of the rendered SVG are dilated and removed from the mask. Anti-aliasing halos along every shape boundary would otherwise dominate the diff; real defects (malformed counters, missing dots) are interior regions that survive.
   - **Connected-component filtering** — Blobs below a minimum area (8–48 px depending on variant) are dropped as speckle noise.
4. **Extract residual** — Original pixels where the mask is true are copied into an RGBA image; everything else is transparent.
5. **Vectorize residual** — Only the differing pixels are traced with VTracer using the current pass variant's parameters (`colormode`, `hierarchical`, `mode`, `filter_speckle`, `path_precision`, `color_precision`).
6. **Merge overlay** — The corrective SVG paths are appended to the base SVG inside a `<g class="vb-refine">` group. If the base and overlay use different `viewBox` coordinate systems (common when StarVector emits normalized `0 0 1 1` units and VTracer uses pixel units), a **`transform="matrix(...)"`** maps overlay coordinates into the base canvas.
7. **Re-score** — The merged SVG is rasterized and DinoScored against the original.
8. **Accept or reject** — If DinoScore improved by at least `REFINE_MIN_DELTA` (default 0.0005), the merge is kept and becomes the new best SVG. Otherwise the pass counts as a failure.

**Six pass variants** cycle (`pass_idx % 6`), progressing from conservative (large interior defects, high `min_component_area`) to aggressive (fine near-edge defects, binary colormode, zero edge exclusion):

| Variant | Threshold factor | Edge exclusion | Min area | VTracer mode |
|---------|-----------------|----------------|----------|--------------|
| 1 | 0.7× | 2 px | 48 px | color / stacked / spline |
| 2 | 1.0× | 2 px | 32 px | color / stacked / spline |
| 3 | 0.8× | 1 px | 24 px | color / cutout / spline |
| 4 | 0.65× | 1 px | 16 px | color / stacked / polygon |
| 5 | 0.5× | 1 px | 12 px | color / stacked / spline |
| 6 | 0.4× | 0 px | 8 px | binary / stacked / spline |

The loop stops when:

- All six variants produce masks below `REFINE_MIN_MASK_RATIO` (0.05% of pixels) — nothing left to fix.
- Three consecutive passes fail to improve the score — diminishing returns.
- `REFINE_MAX_PASSES` is reached.

Accepted passes are counted in the API response as `refine_passes`; peak residual coverage as `refine_coverage`.

### Phase 4 — Fontless sanitize

If `fontless=true` (default), `<text>` elements and font references are stripped or converted to paths so the output is pure geometry — no embedded fonts, no system-font dependencies.

---

## Quick start

The simplest way to run SvgBot is from the project root:

```bash
bash run.sh
```

That creates `backend/.venv` if needed, installs Python and npm dependencies (including StarVector), starts the FastAPI backend on port 8000 and the Vite frontend on port 5173, then opens both services. Press `Ctrl+C` to stop.

Open **http://127.0.0.1:5173** in your browser.

### Convert an image

The web UI accepts input two ways:

- **Upload** — drag and drop a file or click to browse (PNG, JPG, WebP, GIF, and other common formats).
- **From URL** — paste a direct link to a publicly reachable image; the backend downloads it server-side before vectorizing.

Choose quality and engine options, then run the conversion. The result SVG can be previewed and downloaded when the job finishes.

Override ports with environment variables:

```bash
BACKEND_PORT=8080 FRONTEND_PORT=3000 bash run.sh
```

### macOS (Terminal)

```bash
git clone https://github.com/jamesmudgett/SvgBot.git
cd SvgBot
chmod +x run.sh
bash run.sh
```

Requires **Python 3.11+**, **Node.js 18+**, and an **NVIDIA GPU with CUDA** for StarVector (see [GPU requirements](#gpu-requirements) below). macOS without CUDA falls back to VTracer-only if StarVector cannot load.

### Windows

| Shell | Command |
|-------|---------|
| **PowerShell** (recommended) | `.\run.ps1` |
| **CMD** | `run.cmd` |
| **Git Bash / WSL** | `bash run.sh` |

```powershell
git clone https://github.com/jamesmudgett/SvgBot.git
cd SvgBot
.\run.ps1
```

Do **not** run `./run.ps1` in Git Bash — `.ps1` files are PowerShell scripts. Use `bash run.sh` in Git Bash instead.

Native Cairo/GTK is **not** required on Windows; SvgBot patches StarVector to rasterize via `svglib` when Cairo is missing.

### Linux

```bash
git clone https://github.com/jamesmudgett/SvgBot.git
cd SvgBot
chmod +x run.sh
bash run.sh
```

Same prerequisites as macOS. For GPU support, install [CUDA-enabled PyTorch](#cuda-pytorch-required-for-gpu) after the first run.

---

## GPU requirements

StarVector (the neural engine) requires an **NVIDIA GPU with CUDA**. CPU-only PyTorch will load but StarVector reports `CUDA not available` and the orchestrator falls back to VTracer.

| Model | VRAM | Env var |
|-------|------|---------|
| `starvector/starvector-1b-im2svg` (default) | ~8 GB | `STARVECTOR_MODEL=starvector/starvector-1b-im2svg` |
| `starvector/starvector-8b-im2svg` | ~16 GB | `STARVECTOR_MODEL=starvector/starvector-8b-im2svg` |

**VTracer**, **DinoScore**, and the **refinement loop** run on CPU and do not need a GPU. Set `STARVECTOR_ENABLED=false` in `backend/.env` for a fully CPU-only deployment.

StarVector works best on **icons, logos, diagrams, and charts** — not arbitrary photographs.

Verify your setup:

```bash
cd backend
PYTHONPATH=. python scripts/check_starvector.py
```

Then confirm `http://127.0.0.1:8000/health` includes `"api_version": "0.1.1"` and a `starvector_config` block with `"ready": true`.

---

## Detailed setup

### Stack

- **Backend**: FastAPI, StarVector (transformers), VTracer, DinoScore/LPIPS metrics
- **Frontend**: React + Vite
- **Payments**: [MPP](https://mpp.dev) (Tempo/Stripe) and [x402](https://docs.x402.org) HTTP 402

### Backend (manual)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows
pip install -r requirements.txt
cp .env.example .env               # copy .env.example .env  on Windows
uvicorn app.main:app --reload --reload-dir app --reload-exclude '*.pyc' --reload-exclude '.venv/*' --host 0.0.0.0 --port 8000
```

### Frontend (manual)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

### CUDA PyTorch (required for GPU)

Default `pip install torch` is often **CPU-only**. With an NVIDIA GPU:

```bash
pip install -r backend/requirements-gpu.txt
```

### StarVector package

StarVector requires **transformers 4.49** (5.x causes meta-device load failures). Install deps first (includes flexible **torch≥2.6** wheels), then the git package **without** its upstream metadata deps — upstream pins `torch==2.5.1`, which is often missing from PyPI on newer Python.

```bash
pip install -r backend/requirements-starvector-deps.txt
pip install --no-deps -r backend/requirements-starvector-package.txt
```

`bash run.sh` does both steps automatically. Optional upstream extras such as **`flash_attn`** are not pulled in (SvgBot defaults to **`STARVECTOR_ATTN_IMPLEMENTATION=eager`**); install `flash_attn` yourself only if you switch attention modes and your platform supports builds.

Configure in `backend/.env`:

```env
STARVECTOR_ENABLED=true
STARVECTOR_MODEL=starvector/starvector-1b-im2svg
HF_TOKEN=hf_...   # recommended for faster Hugging Face downloads
```

Refinement tuning (optional; refinement always runs unless `REFINE_MAX_PASSES=0`):

```env
REFINE_MAX_PASSES=20
REFINE_MIN_DELTA=0.0005
REFINE_RESIDUAL_THRESHOLD=12
REFINE_MIN_MASK_RATIO=0.0005
```

### Tests

```bash
cd backend
pytest -q
```

Use `engine=vtracer` in tests when GPU / StarVector is unavailable.

---

## Agent API (MPP / x402)

**$0.50 per conversion** when payments are enabled. Full instructions: [docs/AGENT_API.md](docs/AGENT_API.md).

| Discovery | Description |
|-----------|-------------|
| `GET /.well-known/agent-api` | Machine-readable workflow, pricing, MPP/x402 steps |
| `GET /.well-known/mpp-discovery` | MPP discovery document |

Enable in `backend/.env`:

```env
PAYMENTS_ENABLED=true
PRICE_PER_CONVERSION_USD=0.50
MPP_SECRET_KEY=sk_...
MPP_TEMPO_RECIPIENT=0x...
MPP_TEMPO_CURRENCY=0x20c0000000000000000000000000000000000000
X402_ENABLED=true
X402_EVM_ADDRESS=0x...
```

```bash
pip install -r backend/requirements-payments.txt
```

Paid flow: pay on `POST /api/vectorize` → `{ "job_id" }` → poll `GET /api/jobs/{id}` → `GET /api/jobs/{id}/svg`.

---

## API

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/vectorize` | Start conversion (multipart: `file` **or** `image_url`, plus `quality`, `engine`, `fontless`) |
| GET | `/api/jobs/{id}` | Job status + result (includes `refine_passes`, `refine_coverage`, `dino_score`) |
| GET | `/api/jobs/{id}/svg` | Download SVG |
| GET | `/.well-known/agent-api` | Agent API instructions (JSON) |
| GET | `/.well-known/mpp-discovery` | MPP payment discovery ($0.50/conversion) |
| GET | `/health` | Health + StarVector availability |

---

## Troubleshooting

### "Failed to fetch" in the UI

The browser could not reach the API. Usually the backend is not running.

1. Start both services: `bash run.sh` or `.\run.ps1` on Windows.
2. Confirm the API responds: open http://127.0.0.1:8000/health — you should see `{"status":"ok",...}`.
3. Use the Vite dev server at http://127.0.0.1:5173 (`npm run dev`), not a static file or build opened without the proxy.
4. If you set `VITE_API_BASE` in `frontend/.env`, point it at a reachable host (e.g. `http://127.0.0.1:8000`). Leave it unset for the default dev proxy.

The UI shows a red banner when `/health` is unreachable.

### "StarVector disabled via STARVECTOR_ENABLED=false"

That exact text is from an **old backend build**. Restart after pulling latest code. If `starvector_config.starvector_enabled` is `true` but `starvector` is `false`, check `starvector_detail.reason` — usually **CPU-only PyTorch** (`CUDA not available`) even when an NVIDIA GPU is present; install `requirements-gpu.txt`.

### "Failed to import transformers… [WinError 6714]" on Windows

The cause is `uvicorn --reload` watching directories it shouldn't (the venv, the StarVector/HF model cache). A model download or `.pyc` regeneration triggers a worker reload mid-import; the new worker tries to re-import `transformers` while the old one still holds file handles, and Windows returns `[WinError 6714]`.

The shipped `run.ps1` / `run.sh` already pass `--reload-dir app --reload-exclude '*.pyc' --reload-exclude '.venv/*'`, so reloads only fire on application code changes. If you still hit this (e.g. running uvicorn manually), restart in a fresh PowerShell window:

```powershell
Get-Process | Where-Object { $_.Path -like '*\backend\.venv\*' } | Stop-Process -Force
.\run.ps1
```

If you need to launch uvicorn directly, mirror the reload scope:

```powershell
cd backend
.\.venv\Scripts\python -m uvicorn app.main:app `
  --reload --reload-dir app --reload-exclude '*.pyc' --reload-exclude '.venv/*' `
  --host 0.0.0.0 --port 8000
```

---

## License

GPL-3.0 — see [LICENSE](LICENSE).
