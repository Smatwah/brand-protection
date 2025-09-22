"""
Notification: Send alerts and reports
"""
import asyncio
import json
import mimetypes
import smtplib
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

import cv2
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from typing import Dict, List, Optional
import logging
from datetime import datetime


logger = logging.getLogger(__name__)

PREFERENCES_FILE_NAME = "notification_preferences.json"


def _notification_preferences_path(config=None) -> Path:
    base_dir = Path(getattr(config, "DATA_DIR", "data")) if config is not None else Path("data")
    settings_dir = base_dir / "settings"
    return settings_dir / PREFERENCES_FILE_NAME


def _normalise_preferences(payload: dict, *, defaults: dict[str, bool]) -> dict[str, bool]:
    result = defaults.copy()
    if not isinstance(payload, dict):
        return result
    for key in defaults:
        if key in payload:
            result[key] = bool(payload[key])
    return result


def load_notification_preferences(config=None) -> dict[str, bool]:
    defaults = {
        "email": True,
        "slack": True,
    }
    path_value = _notification_preferences_path(config)
    try:
        raw = path_value.read_text(encoding="utf-8")
    except FileNotFoundError:
        return defaults.copy()
    except OSError as exc:
        logging.getLogger(__name__).debug("Unable to read notification preferences: %s", exc)
        return defaults.copy()
    raw = raw.strip()
    if not raw:
        return defaults.copy()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logging.getLogger(__name__).warning("Notification preferences file %s is invalid JSON; using defaults", path_value)
        return defaults.copy()
    return _normalise_preferences(data, defaults=defaults)


def save_notification_preferences(preferences: dict[str, bool], config=None) -> dict[str, bool]:
    defaults = load_notification_preferences(config)
    normalised = _normalise_preferences(preferences or {}, defaults=defaults)
    path_value = _notification_preferences_path(config)
    try:
        path_value.parent.mkdir(parents=True, exist_ok=True)
        path_value.write_text(json.dumps(normalised, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logging.getLogger(__name__).error("Failed to persist notification preferences: %s", exc)
    return normalised.copy()

class EscalationNotificationError(RuntimeError):
    '''Raised when sending an escalation email fails.'''
    pass


class NotificationManager:
    def __init__(self, config):
        self.config = config
        self.enabled = getattr(config, 'ENABLE_NOTIFICATIONS', True)
        raw_methods = getattr(config, 'NOTIFICATION_METHODS', [])
        if isinstance(raw_methods, str):
            raw_methods = [raw_methods]
        self.methods = {method.strip().lower() for method in raw_methods if method and method.strip()}
        if not self.methods:
            self.methods = {'email', 'slack'}

        token = getattr(config, 'SLACK_TOKEN', None)
        self.slack_client = None
        if token and 'slack' in self.methods:
            try:
                self.slack_client = WebClient(token=token)
            except Exception as exc:
                logger.error("Failed to initialise Slack client: %s", exc)
                self.slack_client = None
        self.enable_slack = self.slack_client is not None and 'slack' in self.methods

        self.email_recipients = getattr(config, 'EMAIL_RECIPIENTS', [])
        self.enable_email = bool(self.email_recipients) and 'email' in self.methods

        screenshots_dir = getattr(config, 'SCREENSHOTS_DIR', 'data/screenshots')
        self.annotated_dir = Path(screenshots_dir) / 'annotated'



    async def send_alert(self, risk_report: Dict, detection_type: str = 'impersonation', context: Optional[Dict] = None):
        if not self.enabled:
            return

        risk_score = self._normalise_risk_score(risk_report, context)
        computed_level = self._risk_level_from_score(risk_score)
        reported_level_raw = risk_report.get('risk_level')
        reported_level = str(reported_level_raw).lower().strip() if isinstance(reported_level_raw, str) else None
        risk_level = computed_level or reported_level or 'low'

        if risk_score is not None and risk_score < 26:
            return
        if risk_score is None and risk_level not in {'high', 'medium'}:
            return

        detection_details = self._build_detection_details(
            risk_report,
            detection_type,
            context,
            override_level=risk_level,
            override_score=risk_score,
        )
        annotation_meta: Dict[str, int] = {}
        if context:
            annotated_path, annotation_meta = await asyncio.to_thread(
                self._prepare_annotated_screenshot,
                detection_details,
                context,
            )
            if annotated_path:
                detection_details['annotated_screenshot'] = annotated_path
        detection_details['annotation_meta'] = annotation_meta

        preferences = load_notification_preferences(self.config)
        allow_slack = bool(self.enable_slack and self.slack_client and preferences.get('slack', True))
        allow_email = bool(self.enable_email and preferences.get('email', True))

        tasks: list = []
        if allow_slack:
            tasks.append(asyncio.to_thread(self._send_slack_alert, detection_details))
        if allow_email:
            tasks.append(asyncio.to_thread(self._send_email_alert, detection_details))

        for task in tasks:
            try:
                await task
            except Exception as exc:  # pragma: no cover - logging path
                logger.error("Notification channel failed: %s", exc, exc_info=True)

        await asyncio.to_thread(self._log_detection, detection_details)


    def _build_detection_details(
        self,
        risk_report: Dict,
        detection_type: str,
        context: Optional[Dict],
        *,
        override_level: Optional[str] = None,
        override_score: Optional[float] = None,
    ) -> Dict:
        brand = None
        if context:
            brand = context.get('item', {}).get('brand') or context.get('item', {}).get('brand_name')
        brand = brand or risk_report.get('brand') or getattr(self.config, 'BRAND_NAME', 'Unknown brand')

        url = risk_report.get('url')
        if not url and context:
            url = context.get('item', {}).get('url')

        screenshot_path = None
        if context:
            screenshot_path = (context.get('screenshot_data', {}) or {}).get('screenshot_path')

        timestamp = risk_report.get('timestamp')
        if not timestamp and context:
            timestamp = context.get('timestamp')
        if not timestamp:
            timestamp = datetime.now().isoformat()

        risk_score = override_score
        if risk_score is None:
            risk_score = self._safe_float(risk_report.get('overall_risk_score'))
            if risk_score is None:
                risk_score = self._safe_float(risk_report.get('risk_score'))
            if risk_score is not None and risk_score <= 1:
                risk_score *= 100
        if risk_score is not None:
            try:
                risk_score = max(0.0, min(float(risk_score), 100.0))
                risk_score = round(risk_score, 2)
            except (TypeError, ValueError):
                risk_score = None

        risk_level_value = override_level or str(risk_report.get('risk_level', 'low')).lower().strip()
        if not risk_level_value:
            risk_level_value = 'low'

        summary = None
        summary_candidates = [
            risk_report.get('summary'),
            risk_report.get('report'),
            risk_report.get('details'),
            risk_report.get('analysis'),
        ]
        for candidate in summary_candidates:
            if isinstance(candidate, str) and candidate.strip():
                summary = candidate.strip()
                break
        if not summary and context:
            context_report = context.get('risk_report') if isinstance(context, dict) else None
            if isinstance(context_report, dict):
                for key in ('summary', 'report', 'details', 'analysis'):
                    candidate = context_report.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        summary = candidate.strip()
                        break
            if not summary:
                candidate = context.get('summary') if isinstance(context, dict) else None
                if isinstance(candidate, str) and candidate.strip():
                    summary = candidate.strip()

        return {
            'brand': brand,
            'url': url,
            'timestamp': timestamp,
            'risk_level': risk_level_value,
            'risk_score': risk_score,
            'summary': summary,
            'risk_report': risk_report,
            'detection_type': detection_type,
            'screenshot_path': screenshot_path,
            'recommendations': risk_report.get('recommendations', []),
            'risk_factors': risk_report.get('risk_factors', []),
            'context_fragments': self._extract_context_summary(context),
        }


    def _extract_context_summary(self, context: Optional[Dict]) -> Dict:
        if not context:
            return {}
        summary: Dict[str, object] = {}
        item = context.get('item')
        if item:
            summary['item'] = {
                key: item.get(key)
                for key in ('source', 'type', 'brand', 'url')
                if key in item
            }
        ocr = context.get('ocr_results') or {}
        if ocr:
            summary['ocr'] = {
                'suspicious_phrases': ocr.get('suspicious_phrases', []),
                'confidence': ocr.get('confidence'),
            }
        vision = context.get('vision_analysis') or {}
        if vision:
            summary['vision'] = {
                'logo_detections': len((vision.get('logo_detection') or {}).get('detected_objects', [])),
                'gemini_impersonation': bool((vision.get('gemini_analysis') or {}).get('brand_impersonation_detected')),
            }
        return summary

    def _normalise_risk_score(self, risk_report: Dict, context: Optional[Dict]) -> Optional[float]:
        candidates: list = []
        if isinstance(risk_report, dict):
            candidates.extend([
                risk_report.get('overall_risk_score'),
                risk_report.get('risk_score'),
                risk_report.get('score'),
            ])
            nested = risk_report.get('risk_report')
            if isinstance(nested, dict):
                candidates.extend([
                    nested.get('overall_risk_score'),
                    nested.get('risk_score'),
                    nested.get('score'),
                ])
        if isinstance(context, dict):
            candidates.extend([
                context.get('risk_score'),
                context.get('score'),
            ])
            ctx_report = context.get('risk_report')
            if isinstance(ctx_report, dict):
                candidates.extend([
                    ctx_report.get('overall_risk_score'),
                    ctx_report.get('risk_score'),
                    ctx_report.get('score'),
                ])
        for candidate in candidates:
            score = self._safe_float(candidate)
            if score is None:
                continue
            if score <= 1:
                score *= 100
            try:
                score_value = float(score)
            except (TypeError, ValueError):
                continue
            score_value = max(0.0, min(score_value, 100.0))
            return round(score_value, 2)
        return None

    @staticmethod
    def _risk_level_from_score(score: Optional[float]) -> Optional[str]:
        if score is None:
            return None
        try:
            score_value = float(score)
        except (TypeError, ValueError):
            return None
        if score_value >= 76:
            return 'high'
        if score_value >= 26:
            return 'medium'
        if score_value >= 0:
            return 'low'
        return None

    def _prepare_annotated_screenshot(self, details: Dict, context: Dict):
        screenshot_path = details.get('screenshot_path')
        if not screenshot_path:
            return None, {}
        source = Path(screenshot_path)
        if not source.exists():
            return None, {}

        image = cv2.imread(str(source))
        if image is None:
            return None, {}
        annotated = image.copy()
        meta = {'logo_detections': 0, 'suspicious_highlights': 0}
        height, width = annotated.shape[:2]

        vision = context.get('vision_analysis') or {}
        logo_detection = vision.get('logo_detection') or {}
        boxes = logo_detection.get('bounding_boxes') or []
        names = logo_detection.get('detected_objects') or []
        confidences = logo_detection.get('confidence_scores') or []
        for idx, box in enumerate(boxes):
            if not isinstance(box, (list, tuple)) or len(box) != 4:
                continue
            x1, y1, x2, y2 = [int(round(value)) for value in box]
            x1 = max(0, min(width - 1, x1))
            y1 = max(0, min(height - 1, y1))
            x2 = max(0, min(width - 1, x2))
            y2 = max(0, min(height - 1, y2))
            if x2 <= x1 or y2 <= y1:
                continue
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 255), 2)
            label = names[idx] if idx < len(names) else 'logo'
            conf = None
            if idx < len(confidences):
                try:
                    conf = float(confidences[idx])
                except (TypeError, ValueError):
                    conf = None
            caption = label
            if conf is not None:
                caption = f"{caption} {conf * 100:.0f}%"
            y_text = max(y1 - 8, 8)
            cv2.putText(annotated, caption, (x1, y_text), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
            meta['logo_detections'] += 1

        brand_logo = vision.get('brand_logo_similarity') or {}
        bbox = brand_logo.get('bounding_box') or {}
        top_left = bbox.get('top_left')
        bottom_right = bbox.get('bottom_right')
        if top_left and bottom_right:
            x1 = max(0, min(width - 1, int(top_left[0])))
            y1 = max(0, min(height - 1, int(top_left[1])))
            x2 = max(0, min(width - 1, int(bottom_right[0])))
            y2 = max(0, min(height - 1, int(bottom_right[1])))
            if x2 > x1 and y2 > y1:
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                label = 'Brand logo match' if brand_logo.get('detected') else 'Logo candidate'
                cv2.putText(annotated, label, (x1, max(y1 - 8, 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
                meta['logo_detections'] += 1

        ocr_results = context.get('ocr_results') or {}
        suspicious_boxes = ocr_results.get('suspicious_word_boxes')
        if not suspicious_boxes:
            suspicious_boxes = self._derive_suspicious_boxes(ocr_results)
        if suspicious_boxes:
            overlay = annotated.copy()
            count = 0
            for box in suspicious_boxes:
                try:
                    left = int(box.get('left', 0))
                    top = int(box.get('top', 0))
                    width_box = int(box.get('width', 0))
                    height_box = int(box.get('height', 0))
                except (TypeError, ValueError):
                    continue
                x1 = max(0, min(width - 1, left))
                y1 = max(0, min(height - 1, top))
                x2 = max(0, min(width - 1, x1 + max(width_box, 1)))
                y2 = max(0, min(height - 1, y1 + max(height_box, 1)))
                if x2 <= x1 or y2 <= y1:
                    continue
                cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 255), thickness=-1)
                count += 1
            if count:
                alpha = 0.35
                annotated = cv2.addWeighted(overlay, alpha, annotated, 1 - alpha, 0)
                for box in suspicious_boxes:
                    try:
                        left = int(box.get('left', 0))
                        top = int(box.get('top', 0))
                        width_box = int(box.get('width', 0))
                        height_box = int(box.get('height', 0))
                    except (TypeError, ValueError):
                        continue
                    x1 = max(0, min(width - 1, left))
                    y1 = max(0, min(height - 1, top))
                    x2 = max(0, min(width - 1, x1 + max(width_box, 1)))
                    y2 = max(0, min(height - 1, y1 + max(height_box, 1)))
                    if x2 <= x1 or y2 <= y1:
                        continue
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 128, 255), 1)
                meta['suspicious_highlights'] = count

        try:
            self.annotated_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover - filesystem dependent
            logger.debug("Could not create annotated directory: %s", exc)

        filename = f"annotated_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
        destination = self.annotated_dir / filename
        try:
            if cv2.imwrite(str(destination), annotated):
                return str(destination), meta
        except Exception as exc:  # pragma: no cover - OpenCV failure
            logger.error("Failed to write annotated screenshot: %s", exc)
        return None, meta

    def _derive_suspicious_boxes(self, ocr_results: Dict) -> List[Dict]:
        suspicious_phrases = ocr_results.get('suspicious_phrases') or []
        word_boxes = ocr_results.get('word_boxes') or []
        if not suspicious_phrases or not word_boxes:
            return []
        tokens = set()
        for phrase in suspicious_phrases:
            for token in str(phrase).split():
                cleaned = ''.join(ch for ch in token.lower() if ch.isalnum())
                if cleaned:
                    tokens.add(cleaned)
        if not tokens:
            return []
        matches: List[Dict] = []
        for box in word_boxes:
            text = ''.join(ch for ch in str(box.get('text', '')).lower() if ch.isalnum())
            if not text:
                continue
            if any(token in text for token in tokens):
                matches.append(box)
        return matches

    def _send_slack_alert(self, details: Dict):
        if not self.slack_client:
            return
        risk_level = details.get('risk_level', 'unknown').capitalize()
        risk_score = details.get('risk_score')
        if risk_score is not None:
            try:
                score_display = f"{float(risk_score):.1f}%"
            except (TypeError, ValueError):
                score_display = str(risk_score)
        else:
            score_display = 'N/A'

        timestamp = details.get('timestamp', '')
        message_lines = [
            f"*{details.get('brand', 'Unknown brand')}* detection ({details.get('detection_type', 'impersonation').title()})",
            f"- Risk: *{risk_level}* ({score_display})",
            f"- URL: {details.get('url') or 'N/A'}",
            f"- Detected: {timestamp}",
        ]

        summary_value = details.get('summary') or (details.get('risk_report') or {}).get('summary')
        if isinstance(summary_value, str) and summary_value.strip():
            message_lines.append('')
            message_lines.append('*Summary*')
            message_lines.append(summary_value.strip())

        annotation_meta = details.get('annotation_meta') or {}
        if annotation_meta.get('logo_detections'):
            message_lines.append(f"- Logos highlighted: {annotation_meta['logo_detections']}")
        if annotation_meta.get('suspicious_highlights'):
            message_lines.append(f"- Suspicious text highlights: {annotation_meta['suspicious_highlights']}")
        if details.get('risk_factors'):
            message_lines.append(f"- Risk factors: {', '.join(details['risk_factors'])}")
        if details.get('recommendations'):
            message_lines.append("- Recommendations:\n  - " + '\n  - '.join(details['recommendations']))

        message = '\n'.join(message_lines)
        annotated_path = details.get('annotated_screenshot')

        try:
            if annotated_path and Path(annotated_path).exists():
                try:
                    self.slack_client.files_upload_v2(
                        channel=self.config.SLACK_CHANNEL,
                        initial_comment=message,
                        title=f"{details.get('brand', 'Detection')} - {risk_level}",
                        file=str(annotated_path),
                    )
                except AttributeError:
                    self.slack_client.files_upload(
                        channels=self.config.SLACK_CHANNEL,
                        initial_comment=message,
                        title=f"{details.get('brand', 'Detection')} - {risk_level}",
                        file=str(annotated_path),
                    )
            else:
                self.slack_client.chat_postMessage(
                    channel=self.config.SLACK_CHANNEL,
                    text=message,
                )
        except SlackApiError as exc:
            logger.error("Slack notification error: %s", exc)

    def _send_email_alert(self, details: Dict):
        if not self.enable_email or not self.email_recipients:
            return

        msg = EmailMessage()
        msg['Subject'] = f"[{details.get('risk_level', 'unknown').upper()}] Brand protection alert: {details.get('brand')}"
        msg['From'] = getattr(self.config, 'EMAIL_FROM_ADDRESS', 'alerts@brandprotection.local')
        msg['To'] = ', '.join(self.email_recipients)
        msg['Date'] = formatdate(localtime=True)

        annotation_meta = details.get('annotation_meta') or {}
        lines = [
            f"Brand: {details.get('brand', 'Unknown brand')}",
            f"Risk level: {details.get('risk_level', 'unknown').capitalize()}",
        ]
        risk_score = details.get('risk_score')
        if risk_score is not None:
            try:
                lines.append(f"Risk score: {float(risk_score):.1f}%")
            except (TypeError, ValueError):
                lines.append(f"Risk score: {risk_score}")
        lines.append(f"URL: {details.get('url') or 'N/A'}")
        lines.append(f"Detected: {details.get('timestamp')}")
        summary_value = details.get('summary') or (details.get('risk_report') or {}).get('summary')
        if isinstance(summary_value, str) and summary_value.strip():
            lines.append('')
            lines.append('Summary:')
            lines.append(summary_value.strip())
        if annotation_meta.get('logo_detections'):
            lines.append(f"Logos highlighted: {annotation_meta['logo_detections']}")
        if annotation_meta.get('suspicious_highlights'):
            lines.append(f"Suspicious text highlights: {annotation_meta['suspicious_highlights']}")
        if details.get('risk_factors'):
            lines.append("Risk factors: " + ', '.join(details['risk_factors']))
        if details.get('recommendations'):
            lines.append('Recommendations:')
            for rec in details['recommendations']:
                lines.append(f"  - {rec}")

        msg.set_content('\n'.join(lines))

        annotated_path = details.get('annotated_screenshot')
        if annotated_path and Path(annotated_path).exists():
            mime_type, _ = mimetypes.guess_type(annotated_path)
            if mime_type:
                maintype, subtype = mime_type.split('/', 1)
            else:
                maintype, subtype = 'image', 'png'
            with open(annotated_path, 'rb') as fh:
                msg.add_attachment(
                    fh.read(),
                    maintype=maintype,
                    subtype=subtype,
                    filename=Path(annotated_path).name,
                )

        server = getattr(self.config, 'EMAIL_SMTP_SERVER', 'localhost')
        port = getattr(self.config, 'EMAIL_SMTP_PORT', 587)
        use_ssl = bool(getattr(self.config, 'EMAIL_USE_SSL', False))
        use_tls = bool(getattr(self.config, 'EMAIL_USE_TLS', True))
        username = getattr(self.config, 'EMAIL_SMTP_USERNAME', None)
        password = getattr(self.config, 'EMAIL_SMTP_PASSWORD', None)

        smtp = None
        try:
            if use_ssl:
                smtp = smtplib.SMTP_SSL(server, port)
            else:
                smtp = smtplib.SMTP(server, port)
                smtp.ehlo()
                if use_tls:
                    smtp.starttls()
            if username and password:
                smtp.login(username, password)
            smtp.send_message(msg)
        except Exception as exc:
            logger.error("Email notification error: %s", exc)
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    pass

    def _log_detection(self, detection_details: Dict):
        log_dir = Path(getattr(self.config, 'REPORTS_DIR', 'data/reports'))
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:  # pragma: no cover - filesystem dependent
            logger.debug("Unable to ensure log directory exists: %s", exc)
        log_file = log_dir / f"detections_{datetime.now().strftime('%Y%m%d')}.jsonl"
        payload = {
            'timestamp': detection_details.get('timestamp'),
            'brand': detection_details.get('brand'),
            'risk_level': detection_details.get('risk_level'),
            'risk_score': detection_details.get('risk_score'),
            'url': detection_details.get('url'),
            'detection_type': detection_details.get('detection_type'),
            'risk_report': detection_details.get('risk_report'),
        }
        with log_file.open('a', encoding='utf-8') as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write('\n')

    @staticmethod
    def _safe_float(value) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


def send_escalation_email(
    config,
    *,
    recipients: List[str],
    evidence: Dict,
    screenshot_path: Optional[Path] = None,
) -> None:
    """Send an escalation email that bundles detection evidence."""
    if not recipients:
        raise EscalationNotificationError("No recipients supplied for escalation email.")

    subject_brand = evidence.get("brand") or "Detection"
    risk_level = evidence.get("risk_level") or "Unknown"
    subject = f"[Escalation] {subject_brand} detection ({str(risk_level).capitalize()})"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = getattr(config, "EMAIL_FROM_ADDRESS", "alerts@brandprotection.local")
    msg["To"] = ", ".join(recipients)
    msg["Date"] = formatdate(localtime=True)

    lines = [
        f"Detection ID: {evidence.get('detection_id')}",
        f"Brand: {subject_brand}",
        f"Risk level: {risk_level}",
    ]
    risk_score = evidence.get("risk_score")
    if risk_score is not None:
        try:
            lines.append(f"Risk score: {float(risk_score):.1f}%")
        except (TypeError, ValueError):
            lines.append(f"Risk score: {risk_score}")
    lines.append(f"URL: {evidence.get('url') or 'N/A'}")
    lines.append(f"Detected at: {evidence.get('timestamp')}")
    if evidence.get("screenshot_url"):
        lines.append(f"Screenshot (web): {evidence['screenshot_url']}")

    explanation = evidence.get("explanation")
    if explanation:
        lines.append("")
        lines.append("AI explanation:")
        lines.append(str(explanation))

    msg.set_content("\n".join(lines))

    try:
        summary_bytes = json.dumps(evidence, ensure_ascii=False, indent=2).encode("utf-8")
    except TypeError:
        summary_bytes = json.dumps({}, ensure_ascii=False).encode("utf-8")
    msg.add_attachment(
        summary_bytes,
        maintype="application",
        subtype="json",
        filename=f"escalation_{evidence.get('detection_id', 'detection')}.json",
    )

    if screenshot_path:
        screenshot_file = Path(screenshot_path)
        if screenshot_file.exists():
            mime_type, _ = mimetypes.guess_type(str(screenshot_file))
            if mime_type:
                maintype, subtype = mime_type.split('/', 1)
            else:
                maintype, subtype = 'image', 'png'
            with screenshot_file.open('rb') as handle:
                msg.add_attachment(
                    handle.read(),
                    maintype=maintype,
                    subtype=subtype,
                    filename=screenshot_file.name,
                )

    server = getattr(config, 'EMAIL_SMTP_SERVER', 'localhost')
    port = getattr(config, 'EMAIL_SMTP_PORT', 587)
    use_ssl = bool(getattr(config, 'EMAIL_USE_SSL', False))
    use_tls = bool(getattr(config, 'EMAIL_USE_TLS', True))
    username = getattr(config, 'EMAIL_SMTP_USERNAME', None)
    password = getattr(config, 'EMAIL_SMTP_PASSWORD', None)

    smtp = None
    try:
        if use_ssl:
            smtp = smtplib.SMTP_SSL(server, port)
        else:
            smtp = smtplib.SMTP(server, port)
            smtp.ehlo()
            if use_tls:
                smtp.starttls()
        if username and password:
            smtp.login(username, password)
        smtp.send_message(msg)
    except Exception as exc:
        raise EscalationNotificationError(f"Email escalation failed: {exc}") from exc
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:
                pass

