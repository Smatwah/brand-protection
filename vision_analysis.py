"""
Vision Analysis: Analyzes images using YOLO and Gemini Vision
"""
import cv2
import numpy as np
from PIL import Image
import google.generativeai as genai
from ultralytics import YOLO
import torch
from typing import Dict, List, Optional
import base64
import io
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

class VisionAnalyzer:
    def __init__(self, config):
        self.config = config
        self.yolo_model = None
        self.gemini_model = None
        self._initialize_models()
    
    def _initialize_models(self):
        """Initialize vision models"""
        try:
            # Initialize YOLO for logo detection
            self.yolo_model = YOLO('yolov8x.pt')  # Will download if not present
            
            # Initialize Gemini Vision (multimodal)
            genai.configure(api_key=self.config.GEMINI_API_KEY)
            # Use a current, supported multimodal model
            self.gemini_model = genai.GenerativeModel('gemini-1.5-flash')
            
        except Exception as e:
            logger.error(f"Error initializing vision models: {e}")
    
    async def analyze_screenshot(self, screenshot_path: str, brand_context: Dict) -> Dict:
        """Comprehensive vision analysis of screenshot"""
        results = {
            'screenshot_path': screenshot_path,
            'logo_detection': None,
            'brand_logo_similarity': None,
            'visual_similarity': None,
            'gemini_analysis': None,
            'risk_indicators': []
        }
        
        try:
            # Load image
            image = cv2.imread(screenshot_path)
            pil_image = Image.open(screenshot_path)
            
            # YOLO object detection
            if self.yolo_model:
                results['logo_detection'] = await self._detect_logos_yolo(image)
            
            # Brand logo similarity detection
            results['brand_logo_similarity'] = await self._detect_brand_logo(
                screenshot_path,
                self.config.BRAND_LOGO_PATH
            )

            # Visual similarity analysis
            results['visual_similarity'] = await self._analyze_visual_similarity(
                screenshot_path, 
                self.config.BRAND_LOGO_PATH
            )
            
            # Gemini Vision analysis
            results['gemini_analysis'] = await self._analyze_with_gemini(
                pil_image, 
                brand_context
            )
            
            # Compile risk indicators
            results['risk_indicators'] = self._compile_risk_indicators(results)
            
        except Exception as e:
            logger.error(f"Error in vision analysis: {e}")
            results['error'] = str(e)
        
        return results
    
    async def _detect_logos_yolo(self, image: np.ndarray) -> Dict:
        """Detect logos and objects using YOLO"""
        detection_results = {
            'detected_objects': [],
            'confidence_scores': [],
            'bounding_boxes': []
        }
        
        try:
            # Run YOLO detection
            results = self.yolo_model(image)
            
            for r in results:
                boxes = r.boxes
                if boxes is not None:
                    for box in boxes:
                        detection_results['detected_objects'].append(
                            self.yolo_model.names[int(box.cls)]
                        )
                        detection_results['confidence_scores'].append(
                            float(box.conf)
                        )
                        detection_results['bounding_boxes'].append(
                            box.xyxy.tolist()[0] if box.xyxy is not None else []
                        )
            
        except Exception as e:
            logger.error(f"YOLO detection error: {e}")
        
        return detection_results

    async def _detect_brand_logo(self, screenshot_path: str, logo_path: str) -> Dict:
        """Detect brand logo within screenshot and compute similarity metrics"""
        detection = {
            'detected': False,
            'similarity_score': 0.0,
            'similarity_percent': 0.0,
            'template_match': 0.0,
            'structural_similarity': 0.0,
            'feature_match_ratio': 0.0,
            'color_histogram_similarity': 0.0,
            'bounding_box': None,
            'matched_scale': 1.0,
            'threshold': float(self.config.LOGO_SIMILARITY_THRESHOLD),
            'matched_region_path': None,
            'annotated_image_path': None
        }

        try:
            screenshot = cv2.imread(screenshot_path)
            logo = cv2.imread(logo_path)

            if screenshot is None or logo is None:
                return detection

            screenshot_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
            logo_gray = cv2.cvtColor(logo, cv2.COLOR_BGR2GRAY)

            best_score = -1.0
            best_location = None
            best_shape = None
            best_scale = 1.0

            # Search across scales to handle different logo sizes
            for scale in np.linspace(0.5, 1.5, 21):
                scaled_w = int(logo_gray.shape[1] * scale)
                scaled_h = int(logo_gray.shape[0] * scale)

                if scaled_w < 10 or scaled_h < 10:
                    continue
                if scaled_w >= screenshot_gray.shape[1] or scaled_h >= screenshot_gray.shape[0]:
                    continue

                resized_logo = cv2.resize(
                    logo_gray,
                    (scaled_w, scaled_h),
                    interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
                )

                result = cv2.matchTemplate(screenshot_gray, resized_logo, cv2.TM_CCOEFF_NORMED)
                if result.size == 0:
                    continue

                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val > best_score:
                    best_score = float(max_val)
                    best_location = max_loc
                    best_shape = (scaled_h, scaled_w)
                    best_scale = float(scale)

            if best_location is None or best_shape is None or best_score < 0:
                return detection

            top_left_x, top_left_y = best_location
            h, w = best_shape
            bottom_right_x = top_left_x + w
            bottom_right_y = top_left_y + h

            matched_region = screenshot[top_left_y:bottom_right_y, top_left_x:bottom_right_x]
            if matched_region.size == 0:
                return detection

            resized_logo_color = cv2.resize(
                logo,
                (w, h),
                interpolation=cv2.INTER_AREA if best_scale < 1.0 else cv2.INTER_CUBIC
            )

            matched_gray = cv2.cvtColor(matched_region, cv2.COLOR_BGR2GRAY)
            resized_logo_gray = cv2.cvtColor(resized_logo_color, cv2.COLOR_BGR2GRAY)

            # Structural similarity on the matched region
            ssim_score = 0.0
            try:
                if matched_gray.shape[0] >= 7 and matched_gray.shape[1] >= 7:
                    from skimage.metrics import structural_similarity as ssim
                    ssim_score = float(ssim(resized_logo_gray, matched_gray))
            except Exception as e:
                logger.debug(f"SSIM computation failed: {e}")

            # Color histogram similarity
            hist_logo = cv2.calcHist(
                [resized_logo_color], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256]
            )
            hist_region = cv2.calcHist(
                [matched_region], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256]
            )
            hist_logo = cv2.normalize(hist_logo, hist_logo).flatten()
            hist_region = cv2.normalize(hist_region, hist_region).flatten()
            hist_similarity = cv2.compareHist(hist_logo, hist_region, cv2.HISTCMP_CORREL)
            hist_similarity = float(np.clip((hist_similarity + 1.0) * 0.5, 0.0, 1.0))

            # Feature matching with ORB for robustness
            feature_ratio = 0.0
            try:
                orb = cv2.ORB_create()
                kp1, des1 = orb.detectAndCompute(resized_logo_gray, None)
                kp2, des2 = orb.detectAndCompute(matched_gray, None)
                if des1 is not None and des2 is not None and kp1 and kp2:
                    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                    matches = bf.match(des1, des2)
                    if matches:
                        feature_ratio = float(min(1.0, len(matches) / max(len(kp1), len(kp2))))
            except Exception as e:
                logger.debug(f"Feature matching failed: {e}")

            template_match = float(np.clip(best_score, 0.0, 1.0))
            ssim_score = float(np.clip(ssim_score, 0.0, 1.0))
            feature_ratio = float(np.clip(feature_ratio, 0.0, 1.0))

            final_score = (
                template_match * 0.4 +
                ssim_score * 0.3 +
                hist_similarity * 0.2 +
                feature_ratio * 0.1
            )
            final_score = float(np.clip(final_score, 0.0, 1.0))

            match_dir = Path(getattr(self.config, 'LOGO_MATCHES_DIR', 'data/logo_matches'))
            match_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            screenshot_stem = Path(screenshot_path).stem or 'screenshot'
            matched_region_path = match_dir / f"{screenshot_stem}_logo_match_{timestamp}.png"
            annotated_image_path = match_dir / f"{screenshot_stem}_annotated_{timestamp}.png"

            saved_match_path = None
            try:
                if cv2.imwrite(str(matched_region_path), matched_region):
                    saved_match_path = matched_region_path
            except Exception as save_err:
                logger.debug(f"Unable to save logo match crop: {save_err}")

            saved_annotated_path = None
            try:
                annotated_image = screenshot.copy()
                cv2.rectangle(
                    annotated_image,
                    (int(top_left_x), int(top_left_y)),
                    (int(bottom_right_x), int(bottom_right_y)),
                    (0, 255, 0),
                    2
                )
                if cv2.imwrite(str(annotated_image_path), annotated_image):
                    saved_annotated_path = annotated_image_path
            except Exception as annotate_err:
                logger.debug(f"Unable to save annotated logo match: {annotate_err}")

            detection.update({
                'detected': final_score >= self.config.LOGO_SIMILARITY_THRESHOLD,
                'similarity_score': final_score,
                'similarity_percent': round(final_score * 100, 2),
                'template_match': template_match,
                'structural_similarity': ssim_score,
                'feature_match_ratio': feature_ratio,
                'color_histogram_similarity': hist_similarity,
                'bounding_box': {
                    'top_left': [int(top_left_x), int(top_left_y)],
                    'bottom_right': [int(bottom_right_x), int(bottom_right_y)],
                    'width': int(w),
                    'height': int(h)
                },
                'matched_scale': round(best_scale, 4),
                'matched_region_path': str(saved_match_path) if saved_match_path else None,
                'annotated_image_path': str(saved_annotated_path) if saved_annotated_path else None
            })
        except Exception as e:
            logger.error(f"Brand logo detection error: {e}")

        return detection

    async def _analyze_visual_similarity(self, img1_path: str, img2_path: str) -> Dict:
        """Analyze visual similarity between images"""
        similarity_results = {
            'structural_similarity': 0.0,
            'feature_similarity': 0.0,
            'color_histogram_similarity': 0.0
        }
        
        try:
            # Load images
            img1 = cv2.imread(img1_path)
            img2 = cv2.imread(img2_path)
            
            if img1 is None or img2 is None:
                return similarity_results
            
            # Resize for comparison
            height = min(img1.shape[0], img2.shape[0])
            width = min(img1.shape[1], img2.shape[1])
            img1_resized = cv2.resize(img1, (width, height))
            img2_resized = cv2.resize(img2, (width, height))
            
            # Convert to grayscale for structural similarity
            gray1 = cv2.cvtColor(img1_resized, cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(img2_resized, cv2.COLOR_BGR2GRAY)
            
            # Calculate structural similarity (SSIM)
            from skimage.metrics import structural_similarity as ssim
            similarity_results['structural_similarity'] = ssim(gray1, gray2)
            
            # Calculate histogram similarity
            hist1 = cv2.calcHist([img1_resized], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
            hist2 = cv2.calcHist([img2_resized], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
            hist1 = cv2.normalize(hist1, hist1).flatten()
            hist2 = cv2.normalize(hist2, hist2).flatten()
            
            similarity_results['color_histogram_similarity'] = cv2.compareHist(
                hist1, hist2, cv2.HISTCMP_CORREL
            )
            
            # Feature matching using ORB
            orb = cv2.ORB_create()
            kp1, des1 = orb.detectAndCompute(gray1, None)
            kp2, des2 = orb.detectAndCompute(gray2, None)
            
            if des1 is not None and des2 is not None:
                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
                matches = bf.match(des1, des2)
                similarity_results['feature_similarity'] = len(matches) / max(len(kp1), len(kp2))
            
        except Exception as e:
            logger.error(f"Visual similarity analysis error: {e}")
        
        return similarity_results
    
    async def _analyze_with_gemini(self, image: Image.Image, brand_context: Dict) -> Dict:
        """Analyze image using Gemini Vision API"""
        gemini_results = {
            'brand_impersonation_detected': False,
            'confidence': 0.0,
            'analysis': '',
            'risk_factors': []
        }
        
        try:
            # Prepare prompt
            prompt = f"""
            Analyze this image for potential brand impersonation of {self.config.BRAND_NAME}.
            
            Look for:
            1. Logo similarity or copying
            2. Color scheme mimicry
            3. Layout and design patterns similar to official brand
            4. Misleading text or claims
            5. Trust signals being misused (badges, certificates, etc.)
            
            Brand Context:
            - Official brand name: {self.config.BRAND_NAME}
            - Official domains: {', '.join(self.config.BRAND_DOMAINS)}
            - Brand keywords: {', '.join(self.config.BRAND_KEYWORDS)}
            
            Provide:
            1. Is this likely brand impersonation? (Yes/No)
            2. Confidence level (0-100%)
            3. Detailed analysis
            4. Specific risk factors identified
            
            Format your response as JSON.
            """
            
            # Send to Gemini
            response = self.gemini_model.generate_content([prompt, image])
            
            # Parse response
            if response.text:
                import json
                try:
                    # Try to extract JSON from response
                    json_str = response.text
                    if '```json' in json_str:
                        json_str = json_str.split('```json')[1].split('```')[0]
                    
                    result = json.loads(json_str)
                    gemini_results.update(result)
                except:
                    # Fallback to text analysis
                    gemini_results['analysis'] = response.text
                    if 'yes' in response.text.lower():
                        gemini_results['brand_impersonation_detected'] = True
            
        except Exception as e:
            logger.error(f"Gemini Vision analysis error: {e}")
        
        return gemini_results
    
    def _compile_risk_indicators(self, analysis_results: Dict) -> List[str]:
        """Compile risk indicators from analysis results"""
        indicators = []
        
        # Check logo detection results
        if analysis_results.get('logo_detection'):
            if analysis_results['logo_detection'].get('detected_objects'):
                indicators.append('potential_logo_detected')
        
        # Check brand logo similarity scores
        brand_logo = analysis_results.get('brand_logo_similarity')
        if brand_logo:
            if brand_logo.get('detected'):
                indicators.append('brand_logo_match')
            elif brand_logo.get('similarity_score', 0) > max(0.0, float(self.config.LOGO_SIMILARITY_THRESHOLD) * 0.8):
                indicators.append('brand_logo_partial_match')
        
        # Check visual similarity
        if analysis_results.get('visual_similarity'):
            sim = analysis_results['visual_similarity']
            if sim.get('structural_similarity', 0) > 0.7:
                indicators.append('high_visual_similarity')
            if sim.get('color_histogram_similarity', 0) > 0.8:
                indicators.append('similar_color_scheme')
        
        # Check Gemini analysis
        if analysis_results.get('gemini_analysis'):
            if analysis_results['gemini_analysis'].get('brand_impersonation_detected'):
                indicators.append('gemini_detected_impersonation')
        
        return indicators
