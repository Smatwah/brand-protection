# Frontend + Backend Integration Guide

This React + Tailwind interface expects a backend that exposes simple JSON endpoints. Use the instructions below to run the UI and connect it to your own scanning service.

## 1. Start the backend

```powershell
# terminal 1 - detection pipeline
cd C:\\Users\\atwah\\Desktop\\BPP
.\venv\Scripts\Activate
python main.py --monitor

# terminal 2 - API bridge
cd C:\\Users\\atwah\\Desktop\\BPP
.\venv\Scripts\Activate
pip install -r requirement.txt
python api_server.py
```

Run the pipeline in one console so it keeps producing detections inside `data/reports/`; run `api_server.py` beside it to expose HTTP + WebSocket endpoints at `http://127.0.0.1:8000`.

## 2. Install dependencies & run the UI

```bash
cd frontend
npm install
npm run dev
```

*The Vite dev server starts on http://localhost:5173 by default.*

## 3. Expected backend endpoints

| Purpose | Method & Path | Notes |
| --- | --- | --- |
| Live detection feed | `GET /api/url-detection` | Return the most recent detection as JSON. Called every ~4 seconds. |
| Live detection stream | `WS /ws/detections` | WebSocket pushes new detections as soon as they are saved. |
| Trigger deeper scan | `POST /api/scan` | Optional. Invoke from the UI when you wire up an action button. |
| Dashboard summary | `GET /api/url-detection/summary` | Provide aggregate counts, top brands, risk distribution, timeline, and recent detections. |
| Historic detections | `GET /api/url-detection/history` | Used to backfill the dashboard table. |
| Historic detections | `GET /api/url-detection/history` | Used to backfill the dashboard table. |

All responses should use UTF-8 JSON. When endpoints are unreachable, the UI holds in a waiting state until your backend responds.

### Example response: `GET /api/url-detection`

```json
{
  "id": "evt-293488",
  "brand": "SecureBank",
  "risk_score": 82,
  "type": "Potential Brand Impersonation",
  "detected_at": "2025-09-18T13:24:10Z",
  "summary": "We found a login page hosted on an unfamiliar domain mimicking SecureBank.",
  "indicators": ["login", "verify", "securebank"],
  "url": "https://securebank-support-login.com/verify",
  "recommendation": "Block the domain and alert affected customers."
}
```

### Example response: `GET /api/url-detection/summary`

```json
{
  "totalDetections": 145,
  "highRisk": 38,
  "brandsImpersonated": 12,
  "lastDetectionMinutesAgo": 3,
  "topBrands": [{ "brand": "SecureBank", "detections": 32 }],
  "riskDistribution": [
    { "label": "High", "value": 38 },
    { "label": "Medium", "value": 72 },
    { "label": "Low", "value": 35 }
  ],
  "timeline": [{ "time": "13:00", "detections": 28 }],
  "recentDetections": [
    {
      "id": "evt-293488",
      "brand": "SecureBank",
      "detectedAt": "2025-09-18T13:24:10Z",
      "riskScore": 82
    }
  ]
}
```

Adapt the schema if needed-just update the mapping logic in `src/pages/LiveDetection.jsx` and `src/pages/Dashboard.jsx` to match your payloads.

## 4. Proxying requests during development

`vite.config.js` already proxies `/api` and `/screenshots` to `http://127.0.0.1:8000`. Override it by exporting `VITE_API_PROXY_TARGET` before starting the dev server:

```powershell
$env:VITE_API_PROXY_TARGET = 'http://localhost:9000'
npm run dev
```

If you prefer to skip the proxy, provide a full base URL for the frontend instead:

```bash
VITE_API_BASE_URL=https://your-api.example.com npm run dev
```

In production builds the UI uses `VITE_API_BASE_URL` when it is defined; otherwise host the frontend and API together so the relative paths still resolve.

## 5. Production build

```bash
npm run build
```

The optimized assets are emitted to `frontend/dist/`. Serve them behind your preferred web server or integrate them into your backend framework.
