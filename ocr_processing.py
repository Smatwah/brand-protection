"""
OCR Processing: Extract and analyze text from images
"""
from __future__ import annotations

import logging
import os
import re
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
import pytesseract
import torch
from PIL import Image, ImageEnhance, ImageFilter

try:
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
except ImportError:  # pragma: no cover - optional dependency
    TrOCRProcessor = None
    VisionEncoderDecoderModel = None

from normalization import (
    ARABIC_DIACRITICS,
    HOMOGLYPH_MAP,
    analyze_script_mix,
    fold_confusables,
    normalize_and_summarize,
    normalize_arabic_text,
)

logger = logging.getLogger(__name__)


class OCRProcessor:
    def __init__(self, config):
        self.config = config
        self._configure_tesseract()
        self.device = self._resolve_device()
        self._trocr_model = None  
        self._trocr_processor = None  
        self._trocr_loaded = False

    def _resolve_device(self) -> str:
        requested = getattr(self.config, 'GPU_DEVICE', 'cuda')
        if requested == 'cpu':
            return 'cpu'
        if torch.cuda.is_available():  # pragma: no cover - depends on runtime hardware
            try:
                torch_device = torch.device(requested)
                return str(torch_device)
            except Exception as exc:
                logger.warning("Falling back to CPU for OCR GPU device '%s': %s", requested, exc)
        return 'cpu'

    def _configure_tesseract(self) -> None:
        """Configure Tesseract binary path and tessdata directory when needed."""
        try:
            if getattr(self.config, 'TESSERACT_CMD', None):
                pytesseract.pytesseract.tesseract_cmd = self.config.TESSERACT_CMD
            else:
                if os.name == 'nt' and not getattr(pytesseract.pytesseract, 'tesseract_cmd', None):
                    for candidate in (
                        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
                    ):
                        if os.path.exists(candidate):
                            pytesseract.pytesseract.tesseract_cmd = candidate
                            break
            if getattr(self.config, 'TESSDATA_PREFIX', None):
                os.environ['TESSDATA_PREFIX'] = self.config.TESSDATA_PREFIX
        except Exception as exc:
            logger.warning("Failed to configure Tesseract path: %s", exc)

    async def process_image(self, image_path: str) -> Dict:
        """Process image with OCR and extract text."""
        results: Dict[str, object] = {
            'image_path': image_path,
            'extracted_text': '',
            'normalized_text': '',
            'folded_text': '',
            'brand_mentions': [],
            'suspicious_phrases': [],
            'urls_found': [],
            'confidence': 0.0,
            'ocr_sources': [],
        }

        try:
            image = Image.open(image_path)
            processed_image = self._preprocess_image(image)

            ocr_outputs: List[Dict[str, object]] = []
            tesseract_text, tesseract_confidence, tesseract_boxes = self._run_tesseract(processed_image)
            if tesseract_text:
                ocr_outputs.append(
                    {
                        'engine': 'tesseract',
                        'text': tesseract_text,
                        'confidence': tesseract_confidence,
                    }
                )
            results['word_boxes'] = tesseract_boxes

            if getattr(self.config, 'ENABLE_TROCR', False):
                trocr_text = await self._run_trocr(image)
                if trocr_text:
                    ocr_outputs.append(
                        {
                            'engine': 'trocr',
                            'text': trocr_text,
                            'confidence': None,
                        }
                    )

            merged_text = self._merge_ocr_outputs(ocr_outputs)
            results['ocr_sources'] = ocr_outputs
            results['extracted_text'] = merged_text
            results['character_count'] = len(merged_text)
            confidences = [entry['confidence'] for entry in ocr_outputs if entry.get('confidence')]
            if confidences:
                results['confidence'] = float(np.mean(confidences))

            normalized_text = normalize_arabic_text(merged_text) if getattr(self.config, 'ENABLE_ARABIC_NORMALIZATION', True) else merged_text
            folded_text = fold_confusables(normalized_text)
            results['normalized_text'] = normalized_text
            results['folded_text'] = folded_text

            results['brand_mentions'] = self._find_brand_mentions(merged_text, normalized_text)
            results['suspicious_phrases'] = self._find_suspicious_phrases(merged_text)
            results['urls_found'] = self._extract_urls(merged_text)

            suspicious_boxes: List[Dict[str, object]] = []
            if results.get('suspicious_phrases') and results.get('word_boxes'):
                tokens = set()
                for phrase in results['suspicious_phrases']:
                    for token in str(phrase).split():
                        cleaned = ''.join(ch for ch in token.lower() if ch.isalnum())
                        if cleaned:
                            tokens.add(cleaned)
                if tokens:
                    for box in results['word_boxes']:
                        text_value = ''.join(ch for ch in str(box.get('text', '')).lower() if ch.isalnum())
                        if not text_value:
                            continue
                        if any(token in text_value for token in tokens):
                            suspicious_boxes.append(box)
            results['suspicious_word_boxes'] = suspicious_boxes


            normalized_analysis = await self._analyze_normalized_text(merged_text, normalized_text, folded_text)
            results['normalized_analysis'] = normalized_analysis
            script_mix = normalized_analysis.get('script_mix', {})
            if script_mix:
                results['script_mix'] = script_mix

        except Exception as exc:
            logger.error(
                "OCR processing error: %s. Verify Tesseract/TrOCR installation and configuration.",
                exc,
            )
            results['error'] = str(exc)

        return results

    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """Preprocess image for better OCR accuracy."""
        opencv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        opencv_image = self._resize_if_needed(opencv_image)

        gray = cv2.cvtColor(opencv_image, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 9, 75, 75)

        morph_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        morph = cv2.morphologyEx(gray, cv2.MORPH_OPEN, morph_kernel, iterations=1)
        enhanced = cv2.addWeighted(gray, 1.5, morph, -0.5, 0)

        thresh = cv2.adaptiveThreshold(
            enhanced,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            10,
        )

        denoised = cv2.medianBlur(thresh, 3)
        angle = self._get_skew_angle(denoised)
        if abs(angle) > 0.5:
            denoised = self._rotate_image(denoised, angle)

        pil_img = Image.fromarray(denoised)
        pil_img = ImageEnhance.Contrast(pil_img).enhance(1.3)
        pil_img = pil_img.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))
        return pil_img

    def _resize_if_needed(self, image: np.ndarray) -> np.ndarray:
        height, width = image.shape[:2]
        min_edge = min(height, width)
        if min_edge >= 900:
            return image
        scale = 900 / max(min_edge, 1)
        new_size = (int(width * scale), int(height * scale))
        return cv2.resize(image, new_size, interpolation=cv2.INTER_CUBIC)

    def _get_skew_angle(self, image: np.ndarray) -> float:
        coords = np.column_stack(np.where(image > 0))
        if coords.size == 0:
            return 0.0
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = 90 + angle
        return -angle

    def _rotate_image(self, image: np.ndarray, angle: float) -> np.ndarray:
        (height, width) = image.shape[:2]
        center = (width // 2, height // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        return cv2.warpAffine(image, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    def _run_tesseract(self, image: Image.Image) -> Tuple[str, Optional[float], List[Dict[str, object]]]:
        languages = getattr(self.config, 'OCR_LANGUAGES', 'eng+ara')
        psm = getattr(self.config, 'OCR_PSM', 6)
        oem = getattr(self.config, 'OCR_OEM', 3)
        config_args = f'--psm {psm} --oem {oem}'
        text = pytesseract.image_to_string(image, lang=languages, config=config_args)
        ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, lang=languages, config=config_args)
        confidences = [int(conf) for conf in ocr_data.get('conf', []) if conf and conf != '-1']
        confidence = float(np.mean(confidences)) if confidences else None

        word_boxes: List[Dict[str, object]] = []
        text_entries = ocr_data.get('text', []) or []
        for idx, raw_text in enumerate(text_entries):
            if not raw_text or not raw_text.strip():
                continue
            try:
                conf_value = ocr_data.get('conf', [])[idx]
                conf_float = float(conf_value) if conf_value not in (None, '', '-1') else None
            except (IndexError, ValueError, TypeError):
                conf_float = None
            try:
                left = int(float(ocr_data.get('left', [])[idx]))
                top = int(float(ocr_data.get('top', [])[idx]))
                width_box = int(float(ocr_data.get('width', [])[idx]))
                height_box = int(float(ocr_data.get('height', [])[idx]))
            except (IndexError, ValueError, TypeError):
                continue
            word_boxes.append({
                'text': raw_text,
                'left': left,
                'top': top,
                'width': width_box,
                'height': height_box,
                'confidence': conf_float,
            })

        return text, confidence, word_boxes

    async def _run_trocr(self, image: Image.Image) -> Optional[str]:
        if self._trocr_loaded is False:
            self._load_trocr_model()
        if not self._trocr_model or not self._trocr_processor:
            return None
        try:
            pixel_values = self._trocr_processor(images=image, return_tensors='pt').pixel_values
            pixel_values = pixel_values.to(self.device)
            with torch.inference_mode():  # pragma: no cover - depends on GPU availability
                generated_ids = self._trocr_model.generate(pixel_values)
            return self._trocr_processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
        except Exception as exc:
            logger.error("TrOCR inference failed: %s", exc)
            return None

    def _load_trocr_model(self) -> None:
        if self._trocr_loaded:
            return
        self._trocr_loaded = True
        if TrOCRProcessor is None or VisionEncoderDecoderModel is None:
            logger.warning("transformers library not available; skipping TrOCR support.")
            return
        try:
            processor_name = getattr(self.config, 'TROCR_PROCESSOR_NAME', 'microsoft/trocr-base-printed')
            model_name = getattr(self.config, 'TROCR_MODEL_NAME', 'microsoft/trocr-base-printed')
            self._trocr_processor = TrOCRProcessor.from_pretrained(processor_name)
            self._trocr_model = VisionEncoderDecoderModel.from_pretrained(model_name)
            self._trocr_model.to(self.device)
            logger.info("Loaded TrOCR model '%s' on device %s", model_name, self.device)
        except Exception as exc:
            logger.error("Failed to load TrOCR model: %s", exc)
            self._trocr_model = None
            self._trocr_processor = None

    def _merge_ocr_outputs(self, outputs: List[Dict[str, object]]) -> str:
        unique_texts: List[str] = []
        seen = set()
        for entry in outputs:
            text = (entry.get('text') or '').strip()
            if not text:
                continue
            normalized = text.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_texts.append(text)
        return '\n'.join(unique_texts)
    def _find_brand_mentions(self, text: str, normalized_text: str) -> List[Dict[str, object]]:
        mentions: List[Dict[str, object]] = []
        haystack = text.lower()
        normalized_haystack = normalized_text.lower()
        brand_variants = set()
        brand_variants.add(getattr(self.config, 'BRAND_NAME', '').lower())
        for keyword in getattr(self.config, 'BRAND_KEYWORDS', []):
            brand_variants.add(keyword.lower())
        brand_variants = {variant.strip() for variant in brand_variants if variant.strip()}
        for variant in brand_variants:
            if not variant:
                continue
            # Use both raw and normalized text for matches
            for match in re.finditer(re.escape(variant), haystack):
                mentions.append({'text': text[match.start():match.end()], 'position': match.start(), 'variant': variant, 'normalized': False})
            for match in re.finditer(re.escape(variant), normalized_haystack):
                mentions.append({'text': normalized_text[match.start():match.end()], 'position': match.start(), 'variant': variant, 'normalized': True})
        return mentions

    def _find_suspicious_phrases(self, text: str) -> List[str]:
        suspicious_patterns = [
            r'verify.{0,20}account',
            r'suspend.{0,20}account',
            r'click.{0,20}here.{0,20}immediately',
            r'urgent.{0,20}action.{0,20}required',
            r'confirm.{0,20}identity',
            r'update.{0,20}payment',
            r'security.{0,20}alert',
            r'limited.{0,20}time.{0,20}offer',
            r'act.{0,20}now',
            r'your.{0,20}account.{0,20}will.{0,20}be',
            r'\u062a\u062d\u062f\u064a\u062b.{0,15}\u0627\u0644\u062d\u0633\u0627\u0628',  # Arabic: update account
            r'\u062a\u0623\u0643\u064a\u062f.{0,15}\u0647\u0648\u064a\u062a\u0643',  # Confirm your identity
            r'\u0625\u062c\u0631\u0627\u0621.{0,10}\u0639\u0627\u062c\u0644',  # Urgent action
        ]
        found = set()
        text_lower = text.lower()
        for pattern in suspicious_patterns:
            matches = re.findall(pattern, text_lower)
            for match in matches:
                if match:
                    found.add(match)
        return list(found)

    def _extract_urls(self, text: str) -> List[str]:
        url_pattern = r'https?://[^\s<>"{}|\^`\[\]]+'
        urls = re.findall(url_pattern, text)
        domain_pattern = r'(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,61}[a-z0-9]'
        domains = re.findall(domain_pattern, text.lower())
        return list(set(urls + [f"http://{domain}" for domain in domains]))

    async def _analyze_normalized_text(self, original: str, normalized: str, folded: str) -> Dict[str, object]:
        analysis: Dict[str, object] = {
            'homoglyph_alerts': [],
            'contains_diacritics': bool(ARABIC_DIACRITICS.search(original)),
            'contains_tatweel': '?' in original,
            'script_mix': analyze_script_mix(original),
        }
        if getattr(self.config, 'ENABLE_MIXED_SCRIPT_ALERTS', True):
            mix = analysis['script_mix']
            if mix and mix.get('arabic') and mix.get('latin'):
                analysis.setdefault('warnings', []).append('mixed_arabic_latin_scripts')
        homoglyph_hits = [char for char in original if char in HOMOGLYPH_MAP]
        if homoglyph_hits:
            analysis['homoglyph_alerts'] = sorted(set(homoglyph_hits))
        analysis['normalized_text'] = normalized
        analysis['folded_text'] = folded
        normalized_folded, _ = normalize_and_summarize(original)
        analysis['folded_full'] = normalized_folded
        return analysis

async def run_ocr_diagnostic(image_path: str, config: Optional[object] = None) -> Dict[str, object]:
    """Run OCR pipeline on a single image and report detailed diagnostics."""
    import time

    diag_logger = logging.getLogger('bpp.ocr.diagnostic')
    diag_logger.info("Starting OCR diagnostic for %s", image_path)
    if not image_path or not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")

    start = time.perf_counter()
    local_config = config
    if local_config is None:
        from config import Config
        local_config = Config()

    processor = OCRProcessor(local_config)
    results = await processor.process_image(image_path)

    raw_text = results.get('extracted_text') or ''
    normalized_text = results.get('normalized_text') or ''
    folded_text = results.get('folded_text') or ''
    confidence = results.get('confidence')
    analysis = results.get('normalized_analysis') or {}
    sources = results.get('ocr_sources') or []

    issues: List[str] = []
    if results.get('error'):
        issues.append('ocr_engine_error')
    if not raw_text.strip():
        issues.append('no_text_detected')
    min_confidence = float(getattr(local_config, 'OCR_MIN_CONFIDENCE', 0.0) or 0.0)
    if confidence is not None and confidence < min_confidence:
        issues.append(f'low_confidence:{confidence:.3f}<{min_confidence:.3f}')

    if issues:
        diag_logger.warning("Diagnostic detected issues: %s", ', '.join(issues))
    else:
        diag_logger.info("OCR diagnostic checks passed without issues.")

    source_summaries: List[str] = []
    for source in sources:
        engine = source.get('engine') or 'unknown'
        source_conf = source.get('confidence')
        if source_conf is None:
            source_summaries.append(f"{engine}:n/a")
        else:
            try:
                source_summaries.append(f"{engine}:{float(source_conf):.3f}")
            except (TypeError, ValueError):
                source_summaries.append(f"{engine}:?")
    if not source_summaries:
        source_summaries.append('none')
    diag_logger.info("OCR engines: %s", ', '.join(source_summaries))

    diag_logger.info("Raw OCR text (%d chars): %s", len(raw_text), raw_text if raw_text else '<empty>')
    diag_logger.info("Normalized text: %s", normalized_text if normalized_text else '<empty>')
    diag_logger.info("Folded text: %s", folded_text if folded_text else '<empty>')
    diag_logger.info(
        "Normalization flags | diacritics=%s tatweel=%s homoglyphs=%s",
        analysis.get('contains_diacritics', False),
        analysis.get('contains_tatweel', False),
        ','.join(analysis.get('homoglyph_alerts') or []) or 'none'
    )
    if analysis.get('warnings'):
        diag_logger.warning("Normalization warnings: %s", ', '.join(analysis['warnings']))

    elapsed = time.perf_counter() - start
    diag_logger.info("OCR diagnostic elapsed %.2fs", elapsed)

    report = {
        'image_path': image_path,
        'raw_text': raw_text,
        'normalized_text': normalized_text,
        'folded_text': folded_text,
        'confidence': confidence,
        'ocr_sources': sources,
        'analysis': analysis,
        'issues': issues,
        'elapsed_seconds': round(elapsed, 3),
    }
    return report


def _run_ocr_diagnostic_cli() -> None:
    import argparse
    import asyncio
    import json
    import sys

    parser = argparse.ArgumentParser(description='Run OCR diagnostic on a single image file.')
    parser.add_argument('image_path', help='Path to the image to inspect with OCR.')
    parser.add_argument(
        '--min-confidence',
        type=float,
        help='Override OCR minimum confidence threshold for this diagnostic run.'
    )
    args = parser.parse_args()

    config_override = None
    if args.min_confidence is not None:
        try:
            from config import Config
            config_override = Config()
            config_override.OCR_MIN_CONFIDENCE = float(args.min_confidence)
        except Exception as exc:
            logger.error('Failed to prepare config override: %s', exc)
            sys.exit(1)

    try:
        report = asyncio.run(run_ocr_diagnostic(args.image_path, config=config_override))
    except FileNotFoundError as exc:
        logger.error(str(exc))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info('OCR diagnostic interrupted by user.')
        sys.exit(130)
    except Exception as exc:  # pragma: no cover - diagnostic helper
        logger.exception('OCR diagnostic failed: %s', exc)
        sys.exit(1)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    _run_ocr_diagnostic_cli()
