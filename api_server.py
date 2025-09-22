import asyncio
import json
import re
from collections import Counter, defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from config import Config
from notification import (
    EscalationNotificationError,
    load_notification_preferences,
    save_notification_preferences,
    send_escalation_email,
)


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORT_DIR = DATA_DIR / "reports"
SCREENSHOT_DIR = DATA_DIR / "screenshots"
LOGO_MATCH_DIR = DATA_DIR / "logo_matches"

app = FastAPI(title="Brand Protection API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if SCREENSHOT_DIR.exists():
    app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOT_DIR)), name="screenshots")

if LOGO_MATCH_DIR.exists():
    app.mount("/logo-matches", StaticFiles(directory=str(LOGO_MATCH_DIR)), name="logo-matches")

config = Config()



EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$", re.IGNORECASE)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_history_date(value: Optional[str], *, end_of_day: bool = False) -> Optional[datetime]:
    if not value:
        return None
    parsed = _parse_iso(value)
    if parsed:
        return _as_utc(parsed)
    try:
        dt = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None
    if end_of_day:
        dt = dt + timedelta(days=1) - timedelta(microseconds=1)
    return _as_utc(dt)


class Detection:
    def __init__(self, source: Path, payload: dict):
        self.source = source
        self.payload = payload

    @property
    def id(self) -> str:
        return str(
            self.payload.get("id")
            or self.payload.get("item", {}).get("id")
            or self.source.stem
        )

    @property
    def url(self) -> Optional[str]:
        return self.payload.get("url") or self.payload.get("item", {}).get("url")

    @property
    def brand(self) -> str:
        brand = (
            self.payload.get("brand")
            or self.payload.get("risk_report", {}).get("brand")
            or self.payload.get("item", {}).get("brand")
            or config.BRAND_NAME
            or "Unknown"
        )
        return str(brand).strip() or "Unknown"

    @property
    def detected_at(self) -> Optional[str]:
        candidate = (
            self.payload.get("timestamp")
            or self.payload.get("detected_at")
            or self.payload.get("risk_report", {}).get("timestamp")
        )
        if candidate:
            return candidate
        file_ts = datetime.fromtimestamp(self.source.stat().st_mtime, tz=timezone.utc)
        return file_ts.isoformat()

    @property
    def detected_at_dt(self) -> datetime:
        parsed = _parse_iso(self.detected_at)
        if parsed:
            return _as_utc(parsed)
        return datetime.fromtimestamp(self.source.stat().st_mtime, tz=timezone.utc)

    @property
    def risk_score(self) -> Optional[int]:
        score = self.payload.get("risk_report", {}).get("overall_risk_score")
        if score is None:
            score = self.payload.get("risk_score")
        if score is None:
            return None
        try:
            score = float(score)
        except (TypeError, ValueError):
            return None
        if score <= 1:
            score *= 100
        score = max(0, min(int(round(score)), 100))
        return score

    @property
    def risk_level(self) -> str:
        raw = self.payload.get("risk_report", {}).get("risk_level")
        if isinstance(raw, str) and raw.strip():
            return raw.strip().capitalize()
        score = self.risk_score
        if score is None:
            return "Unknown"
        if score >= 76:
            return "High"
        if score >= 26:
            return "Medium"
        return "Low"

    @property
    def description(self) -> Optional[str]:
        for key in ("summary", "description"):
            value = self.payload.get(key)
            if value:
                return value
        snippet = self.payload.get("item", {}).get("snippet")
        if snippet:
            return snippet
        factors = self.payload.get("risk_report", {}).get("risk_factors") or []
        if factors:
            return ", ".join(str(factor) for factor in factors if factor)
        return None

    @property
    def recommendation(self) -> Optional[str]:
        recs = self.payload.get("risk_report", {}).get("recommendations")
        if recs:
            return recs[0]
        value = self.payload.get("recommendation")
        if value:
            return value
        return None

    @property
    def report_summary(self) -> Optional[str]:
        report = self.payload.get("risk_report") or {}
        for key in ("summary", "report", "details"):
            value = report.get(key)
            if value:
                return value
        return self.payload.get("analysis") or self.payload.get("report")

    def _resolve_file_path(self, raw_path: Optional[str], *, default_dir: Path) -> Optional[Path]:
        if not raw_path:
            return None
        candidate = Path(str(raw_path))
        search_paths: list[Path] = []
        if candidate.is_absolute():
            search_paths.append(candidate)
        else:
            norm_candidate = candidate
            if candidate.parts and candidate.parts[0].lower() == "data":
                norm_candidate = Path(*candidate.parts[1:])
            search_paths.extend([
                BASE_DIR / candidate,
                BASE_DIR / norm_candidate,
                DATA_DIR / norm_candidate,
                default_dir / norm_candidate,
                default_dir / norm_candidate.name,
            ])
        for option in search_paths:
            try:
                if option.exists():
                    return option
            except OSError:
                continue
        return None

    def _resolve_public_path(self, raw_path: Optional[str], *, default_dir: Path, mount_segment: str) -> Optional[str]:
        resolved = self._resolve_file_path(raw_path, default_dir=default_dir)
        if resolved is None:
            return None
        return f"/{mount_segment.strip('/')}/{resolved.name}"

    @property
    def screenshot_path(self) -> Optional[str]:
        screenshot_info = self.payload.get("screenshot_data") or {}
        raw_path = (
            screenshot_info.get("screenshot_path")
            or self.payload.get("screenshot")
            or self.payload.get("screenshot_path")
        )
        return self._resolve_public_path(raw_path, default_dir=SCREENSHOT_DIR, mount_segment="screenshots")

    @property
    def screenshot_fs_path(self) -> Optional[Path]:
        screenshot_info = self.payload.get("screenshot_data") or {}
        raw_path = (
            screenshot_info.get("screenshot_path")
            or self.payload.get("screenshot")
            or self.payload.get("screenshot_path")
        )
        return self._resolve_file_path(raw_path, default_dir=SCREENSHOT_DIR)

    def _logo_payload(self) -> Optional[dict]:
        vision = self.payload.get("vision_analysis") or {}
        similarity = vision.get("brand_logo_similarity") or {}
        detection = vision.get("logo_detection") or {}

        annotated = self._resolve_public_path(
            similarity.get("annotated_image_path"),
            default_dir=LOGO_MATCH_DIR,
            mount_segment="logo-matches",
        )
        matched = self._resolve_public_path(
            similarity.get("matched_region_path"),
            default_dir=LOGO_MATCH_DIR,
            mount_segment="logo-matches",
        )

        objects = detection.get("detected_objects") or []
        confidences = detection.get("confidence_scores") or []
        boxes = detection.get("bounding_boxes") or []
        matches: list[dict] = []
        for label, confidence, box in zip(objects, confidences, boxes):
            try:
                confidence_value = float(confidence) if confidence is not None else None
            except (TypeError, ValueError):
                confidence_value = None
            matches.append({
                "label": label,
                "confidence": confidence_value,
                "bounding_box": box,
            })

        similarity_percent = similarity.get("similarity_percent")
        if similarity_percent is None:
            raw_score = similarity.get("similarity_score")
            try:
                if raw_score is not None:
                    raw_score = float(raw_score)
                    similarity_percent = raw_score * 100 if raw_score <= 1 else raw_score
            except (TypeError, ValueError):
                similarity_percent = None

        payload = {
            "annotated_path": annotated,
            "match_path": matched,
            "similarity": similarity_percent,
            "detected": bool(similarity.get("detected")) or bool(matches),
            "bounding_box": similarity.get("bounding_box"),
            "matches": matches,
        }

        has_visual = any(
            value
            for key, value in payload.items()
            if key != "matches" and value not in (None, "", [], False)
        )
        if not has_visual and not matches:
            return None
        return payload

    def to_dict(self) -> dict:
        detected_dt = self.detected_at_dt
        detected_iso = _as_utc(detected_dt).isoformat()
        return {
            "id": self.id,
            "url": self.url,
            "brand": self.brand,
            "detected_at": detected_iso,
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "description": self.description,
            "recommendation": self.recommendation,
            "screenshot_path": self.screenshot_path,
            "logo": self._logo_payload(),
            "report": self.report_summary,
        }


def _iter_report_files() -> Iterable[Path]:
    if not REPORT_DIR.exists():
        return []
    return sorted(REPORT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def load_reports(limit: Optional[int] = 200) -> List[Detection]:
    detections: List[Detection] = []
    for path in _iter_report_files():
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
            detections.append(Detection(path, payload))
            if limit and len(detections) >= limit:
                break
        except (json.JSONDecodeError, OSError):
            continue
    return detections




def _format_notification(det: Detection) -> dict:
    summary = det.report_summary or det.description
    return {
        "id": det.id,
        "timestamp": det.detected_at_dt.isoformat(),
        "brand": det.brand,
        "url": det.url,
        "risk_level": det.risk_level,
        "risk_score": det.risk_score,
        "summary": summary,
        "description": det.description,
        "recommendation": det.recommendation,
        "screenshot": det.screenshot_path,
        "status": "unread",
        "type": "detection",
    }


def _list_notifications(limit: int = 50) -> list[dict]:
    notifications: list[dict] = []
    for det in load_reports(limit=None):
        if det.risk_level not in NOTIFICATION_RISK_LEVELS:
            continue
        notifications.append(_format_notification(det))
        if limit and len(notifications) >= limit:
            break
    return notifications


def _risk_distribution(detections: List[Detection]) -> List[dict]:
    by_level = Counter(det.risk_level for det in detections)
    labels = ["High", "Medium", "Low"]
    distribution = [{"label": label, "value": by_level.get(label, 0)} for label in labels]
    unknown = sum(count for label, count in by_level.items() if label not in labels)
    if unknown:
        distribution.append({"label": "Unknown", "value": unknown})
    return distribution


def _timeline(detections: List[Detection]) -> List[dict]:
    buckets: defaultdict[datetime, dict[str, int]] = defaultdict(lambda: {"monitored": 0, "detected": 0})
    for det in detections[:200]:
        bucket_time = _as_utc(det.detected_at_dt).replace(minute=0, second=0, microsecond=0)
        category = "detected" if det.risk_level in {"High", "Medium"} else "monitored"
        buckets[bucket_time][category] += 1
    entries = []
    for bucket, counts in sorted(buckets.items()):
        detected = counts["detected"]
        monitored = counts["monitored"]
        entries.append(
            {
                "timestamp": bucket.isoformat(),
                "time": bucket.strftime("%H:%M"),
                "detected": detected,
                "monitored": monitored,
                "total": detected + monitored,
            }
        )
    return entries[-48:]


def _brands_counter(detections: List[Detection]) -> List[dict]:
    counter = Counter(det.brand for det in detections if det.brand)
    return [
        {"brand": brand, "detections": count}
        for brand, count in counter.most_common(10)
    ]


def _minutes_between(start: datetime, end: datetime) -> int:
    delta = end - start
    minutes = int(delta.total_seconds() // 60)
    return max(minutes, 0)


@app.get("/api/url-detection")
def get_live_detections(limit: int = 5, since: Optional[str] = None):
    detections = load_reports()
    if since:
        since_dt = _parse_iso(since)
        if since_dt:
            since_dt = _as_utc(since_dt)
            detections = [det for det in detections if det.detected_at_dt > since_dt]
    if not detections:
        raise HTTPException(status_code=404, detail="No detections available yet.")
    payload = [det.to_dict() for det in detections[: limit or 5]]
    return payload


@app.get("/api/url-detection/history")
def get_detection_history(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None),
    brand: Optional[str] = Query(None),
    risk_levels: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
):
    detections = load_reports(limit=None)

    brand_filter = (brand or "").strip().lower()
    if brand_filter:
        detections = [det for det in detections if brand_filter in det.brand.lower()]

    search_value = (search or "").strip().lower()
    if search_value:
        detections = [
            det
            for det in detections
            if search_value in det.brand.lower()
            or (det.url and search_value in det.url.lower())
        ]

    levels_raw = (risk_levels or "").replace(";", ",")
    if levels_raw.strip():
        allowed_levels = {
            level.strip().capitalize()
            for level in levels_raw.split(",")
            if level.strip()
        }
        if allowed_levels:
            detections = [
                det
                for det in detections
                if det.risk_level in allowed_levels
                or ("Unknown" in allowed_levels and det.risk_level not in {"High", "Medium", "Low"})
            ]

    start_dt = _parse_history_date(date_from, end_of_day=False)
    end_dt = _parse_history_date(date_to, end_of_day=True)
    if start_dt:
        detections = [det for det in detections if det.detected_at_dt >= start_dt]
    if end_dt:
        detections = [det for det in detections if det.detected_at_dt <= end_dt]

    total = len(detections)
    sliced = detections[offset : offset + limit]
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [det.to_dict() for det in sliced],
    }


@app.post("/api/url-detection/escalate")
def escalate_detection(payload: dict = Body(...)):
    detection_id = str(payload.get("detection_id") or payload.get("id") or "").strip()
    if not detection_id:
        raise HTTPException(status_code=400, detail="detection_id is required.")

    raw_emails = payload.get("emails")
    if raw_emails is None:
        raw_emails = payload.get("recipients")

    emails: list[str] = []
    if isinstance(raw_emails, str):
        parts = re.split(r"[,;\s]+", raw_emails)
        emails = [part.strip() for part in parts if part and part.strip()]
    elif isinstance(raw_emails, (list, tuple, set)):
        for entry in raw_emails:
            if entry is None:
                continue
            parts = re.split(r"[,;\s]+", str(entry))
            for part in parts:
                value = part.strip()
                if value:
                    emails.append(value)
    elif raw_emails is None:
        emails = []
    else:
        raise HTTPException(status_code=400, detail="emails must be a string or list of strings.")

    if not emails:
        raise HTTPException(status_code=400, detail="At least one email address is required.")

    invalid = [email for email in emails if not EMAIL_PATTERN.fullmatch(email)]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid email address: {', '.join(invalid)}")

    normalised: list[str] = []
    seen = set()
    for email in emails:
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)
        normalised.append(email)
    emails = normalised

    detection = next((det for det in load_reports(limit=None) if det.id == detection_id), None)
    if not detection:
        raise HTTPException(status_code=404, detail="Detection not found.")

    evidence = {
        "detection_id": detection.id,
        "brand": detection.brand,
        "url": detection.url,
        "risk_score": detection.risk_score,
        "risk_level": detection.risk_level,
        "explanation": detection.report_summary or detection.description,
        "timestamp": detection.detected_at_dt.isoformat(),
        "screenshot_url": detection.screenshot_path,
    }
    screenshot_path = detection.screenshot_fs_path

    try:
        send_escalation_email(
            config,
            recipients=emails,
            evidence=evidence,
            screenshot_path=screenshot_path,
        )
    except EscalationNotificationError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Failed to dispatch escalation.") from exc

    return {"status": "ok", "sent_to": emails, "detection_id": detection.id}



@app.get("/api/notifications")
def get_notifications(limit: int = Query(30, ge=1, le=200)):
    return {"notifications": _list_notifications(limit=limit)}


@app.get("/api/settings/notifications")
def get_notification_settings():
    return load_notification_preferences(config)


@app.put("/api/settings/notifications")
def update_notification_settings(payload: dict = Body(...)):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")
    allowed = {"email", "slack"}
    unknown = set(payload.keys()) - allowed
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unsupported keys: {', '.join(sorted(unknown))}")
    normalised = {key: bool(payload.get(key)) for key in allowed}
    updated = save_notification_preferences(normalised, config)
    return updated






@app.websocket("/ws/notifications")
async def stream_notifications(websocket: WebSocket):
    await websocket.accept()
    seen_ids: deque[str] = deque(maxlen=200)
    seen_lookup: set[str] = set()

    def remember(identifier: str) -> None:
        if identifier in seen_lookup:
            return
        if len(seen_ids) == seen_ids.maxlen:
            oldest = seen_ids.popleft()
            seen_lookup.discard(oldest)
        seen_ids.append(identifier)
        seen_lookup.add(identifier)

    try:
        initial = _list_notifications(limit=20)
        for item in reversed(initial):
            await websocket.send_json({"type": "notification", "data": item})
            remember(item["id"])
        while True:
            notifications = _list_notifications(limit=50)
            for item in reversed(notifications):
                identifier = item["id"]
                if identifier in seen_lookup:
                    continue
                await websocket.send_json({"type": "notification", "data": item})
                remember(identifier)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return




@app.get("/api/url-detection/summary")
def get_summary():
    detections = load_reports()
    if not detections:
        raise HTTPException(status_code=404, detail="No detections available yet.")

    now = datetime.now(timezone.utc)
    detection_levels = {"High", "Medium"}

    detected_items: List[Detection] = []
    monitored_items: List[Detection] = []
    for det in detections:
        if det.risk_level in detection_levels:
            detected_items.append(det)
        else:
            monitored_items.append(det)

    latest_detected = detected_items[0] if detected_items else None
    minutes_ago = _minutes_between(latest_detected.detected_at_dt, now) if latest_detected else None
    last_detection_iso = latest_detected.detected_at_dt.isoformat() if latest_detected else None

    brand_counter = Counter(det.brand for det in detections if det.brand)
    risk_counts = Counter(det.risk_level for det in detections)
    risk_dist = _risk_distribution(detections)
    timeline = _timeline(detections)
    recent = [det.to_dict() for det in detected_items[:10]]

    summary = {
        "totalDetected": len(detected_items),
        "totalDetections": len(detected_items),
        "totalMonitored": len(monitored_items),
        "highRisk": risk_counts.get("High", 0),
        "mediumRisk": risk_counts.get("Medium", 0),
        "lowRisk": risk_counts.get("Low", 0),
        "unknownRisk": risk_counts.get("Unknown", 0),
        "brandsImpersonated": len(brand_counter),
        "lastDetectionMinutesAgo": minutes_ago,
        "lastDetectionAt": last_detection_iso,
    }

    return {
        "summary": summary,
        "riskDistribution": risk_dist,
        "timeline": timeline,
        "recentDetections": recent,
        "topBrands": _brands_counter(detections),
        "detectionsByRiskLevel": risk_dist,
    }


@app.websocket("/ws/detections")
async def stream_detections(websocket: WebSocket):
    await websocket.accept()
    seen_ids: set[str] = set()
    try:
        while True:
            detections = load_reports(limit=10)
            for det in reversed(detections):
                if det.id in seen_ids:
                    continue
                await websocket.send_json({"type": "detection", "data": det.to_dict()})
                seen_ids.add(det.id)
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        return


@app.get("/health")
def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
