# SvgBot — Agent API (MPP / x402)

Instructions for autonomous agents paying **$0.50 USD per image conversion** and retrieving fontless SVG output.

## Discovery

| Resource | URL |
|----------|-----|
| Agent instructions (JSON) | `GET /.well-known/agent-api` |
| MPP discovery | `GET /.well-known/mpp-discovery` |
| Health | `GET /health` |

Replace `https://your-host` with your deployed API base URL (e.g. `http://127.0.0.1:8000` in development).

## Pricing

- **$0.50 per conversion** — one charge per successful `POST /api/vectorize` (quality tier does not change price).
- Configure on the server: `PRICE_PER_CONVERSION_USD=0.50` (default).
- Poll and download endpoints are **free** after the job is created.

## Enable payments (server operator)

```env
PAYMENTS_ENABLED=true
PRICE_PER_CONVERSION_USD=0.50

# MPP (Tempo) — recommended
MPP_SECRET_KEY=sk_...
MPP_TEMPO_RECIPIENT=0x...
MPP_TEMPO_CURRENCY=0x20c0000000000000000000000000000000000000

# x402 (EVM USDC exact scheme)
X402_ENABLED=true
X402_EVM_ADDRESS=0x...
X402_NETWORK=eip155:84532
X402_FACILITATOR_URL=https://x402.org/facilitator
```

Install payment packages:

```bash
pip install -r backend/requirements-payments.txt
```

## Workflow (all agents)

1. **Discover** — `GET /.well-known/agent-api` for pricing, protocols, and step-by-step payment notes.
2. **Pay** (if `payment.enabled`) — attach MPP or x402 credentials to the vectorize request (see below).
3. **Vectorize** — `POST /api/vectorize` (multipart).
4. **Poll** — `GET /api/jobs/{job_id}` until `status` is `completed` or `failed`.
5. **Download** — `GET /api/jobs/{job_id}/svg` or use `result.svg` from the job payload.

### POST /api/vectorize

**Content-Type:** `multipart/form-data`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | file | required | PNG, JPEG, WebP, etc. (max 20 MB) |
| `quality` | string | `standard` | `standard` or `high` (more StarVector candidates) |
| `engine` | string | `auto` | `auto`, `starvector`, or `vtracer` |
| `fontless` | string | `true` | Strip text elements from SVG |

**Response (200):**

```json
{ "job_id": "abc123..." }
```

**Job status (200):**

```json
{
  "job_id": "abc123",
  "status": "completed",
  "progress": "done",
  "result": {
    "svg": "<svg ...>",
    "width": 512,
    "height": 512,
    "metrics": {
      "dino_score": 0.42,
      "engine": "vtracer",
      "ms": 1200
    }
  }
}
```

---

## MPP (Machine Payments Protocol)

SvgBot uses **MPP Tempo charge** for one-shot API payments. The server calls `mpp.charge(request, amount="0.50")` on `POST /api/vectorize`.

### Agent steps

1. Read `GET /.well-known/mpp-discovery` — confirms `price_per_conversion_usd` and `payment_protocols` includes `mpp`.
2. Use the [MPP client SDK](https://mpp.dev/guides/one-time-payments) (`pympp`) or a Tempo-capable wallet to fund a **$0.50** charge intent.
3. Send the same multipart `POST /api/vectorize` with MPP payment headers/credentials required by your client (signed Tempo transfer).
4. If payment is missing or invalid, the API returns **402 Payment Required**.

References: [MPP one-time payments](https://mpp.dev/guides/one-time-payments), [Tempo charge](https://mpp.dev/payment-methods/tempo/charge).

### Example (Python agent sketch)

```python
import httpx

BASE = "https://your-host"

# 1. Discovery
doc = httpx.get(f"{BASE}/.well-known/agent-api").json()
assert doc["payment"]["price_usd"] == "0.50"

# 2. Build MPP-paid request with your pympp client (attach payment to POST)
# See https://mpp.dev/quickstart/client
with open("logo.png", "rb") as f:
    r = mpp_client.post(  # pseudo — use your MPP HTTP client
        f"{BASE}/api/vectorize",
        files={"file": ("logo.png", f, "image/png")},
        data={"quality": "standard", "engine": "auto", "fontless": "true"},
    )
r.raise_for_status()
job_id = r.json()["job_id"]

# 3. Poll
while True:
    job = httpx.get(f"{BASE}/api/jobs/{job_id}").json()
    if job["status"] in ("completed", "failed"):
        break

svg = job["result"]["svg"]
```

---

## x402 (HTTP 402 Payment Required)

When `X402_ENABLED=true`, **x402 middleware** protects `POST /api/vectorize` at **$0.50** (exact USDC scheme on the configured EVM network).

### Agent steps

1. `POST /api/vectorize` **without** payment → **402** with `PAYMENT-REQUIRED` header (Base64 JSON: scheme, amount, `pay_to`, network).
2. Sign the payment payload (USDC **exact** scheme) for the advertised chain and recipient.
3. **Retry** the identical multipart request with header **`PAYMENT-SIGNATURE`** (Base64 signed payload).
4. On success: **200** + `{ "job_id": "..." }` and optional **`PAYMENT-RESPONSE`** header with settlement info.
5. Poll job endpoints as usual (no extra payment).

References: [x402 docs](https://docs.x402.org), [HTTP 402 concept](https://docs.x402.org/core-concepts/http-402).

### Example (curl outline)

```bash
BASE=https://your-host

# Unpaid request → learn payment requirements
curl -i -X POST "$BASE/api/vectorize" \
  -F "file=@logo.png" \
  -F "quality=standard" \
  -F "engine=auto" \
  -F "fontless=true"
# → 402, read PAYMENT-REQUIRED

# Paid retry (signature from your x402 client wallet)
curl -X POST "$BASE/api/vectorize" \
  -H "PAYMENT-SIGNATURE: <base64-payload>" \
  -F "file=@logo.png" \
  -F "quality=standard" \
  -F "engine=auto" \
  -F "fontless=true"
# → 200 {"job_id":"..."}
```

Use an [x402 client library](https://docs.x402.org) for your stack rather than hand-rolling signatures.

---

## Unpaid mode (development)

When `PAYMENTS_ENABLED=false`, agents can call `POST /api/vectorize` without payment. Discovery lists `price_usd: "0"` and `payment_protocols: []`.

---

## Errors

| Code | Meaning |
|------|---------|
| 402 | Payment required or MPP charge failed |
| 413 | File too large |
| 409 | SVG not ready (job still running) |
| 404 | Unknown job_id |

---

## Human UI

The React UI at `/` uses the same API without agent payment headers when payments are disabled. Agents should always use the discovery endpoints above when integrating programmatically.
