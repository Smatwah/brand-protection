"""
Risk Scoring: Calculate and aggregate risk scores
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

try:
    import joblib
except ImportError:  # pragma: no cover - optional dependency
    joblib = None

try:
    import xgboost as xgb
except ImportError:  # pragma: no cover - optional dependency
    xgb = None

logger = logging.getLogger(__name__)


class RiskScorer:
    def __init__(self, config):
        self.config = config
        self.weights = {
            'visual_similarity': 0.25,
            'text_classification': 0.20,
            'url_features': 0.15,
            'domain_reputation': 0.15,
            'content_analysis': 0.15,
            'behavioral_patterns': 0.10
        }
        fusion_features = getattr(self.config, 'LATE_FUSION_FEATURES', [])
        self._fusion_feature_names = [feature.strip() for feature in fusion_features if feature]
        if not self._fusion_feature_names:
            self._fusion_feature_names = list(self.weights.keys())
        self._late_fusion_model = None
        if getattr(self.config, 'ENABLE_LATE_FUSION_MODEL', False):
            self._late_fusion_model = self._load_late_fusion_model()
            if self._late_fusion_model is None:
                logger.info('Late fusion model unavailable; falling back to weighted heuristics.')
    
    async def calculate_risk_score(self, analysis_results: Dict) -> Dict:
        """Calculate comprehensive risk score"""
        risk_report = {
            'timestamp': datetime.now().isoformat(),
            'url': analysis_results.get('url'),
            'overall_risk_score': 0.0,
            'risk_level': 'low',
            'component_scores': {},
            'risk_factors': [],
            'recommendations': []
        }
        
        try:
            # Calculate component scores
            component_scores = {
                'visual_similarity': self._score_visual_similarity(
                    analysis_results.get('vision_analysis', {})
                ),
                'text_classification': self._score_text_classification(
                    analysis_results.get('text_classification', {})
                ),
                'url_features': self._score_url_features(
                    analysis_results.get('url_features', {})
                ),
                'domain_reputation': self._score_domain_reputation(
                    analysis_results.get('url_features', {})
                ),
                'content_analysis': self._score_content_analysis(
                    analysis_results.get('content_features', {})
                ),
                'behavioral_patterns': self._score_behavioral_patterns(
                    analysis_results
                )
            }
            
            risk_report['component_scores'] = component_scores

            fusion_features = self._build_fusion_features(component_scores, analysis_results)
            if fusion_features:
                risk_report['fusion_features'] = fusion_features

            # Calculate weighted overall score as a fallback baseline
            overall_score = sum(
                score * self.weights[component]
                for component, score in component_scores.items()
            )

            late_score = self._late_fusion_predict(fusion_features) if fusion_features else None
            if late_score is not None:
                weight = float(getattr(self.config, 'LATE_FUSION_MIN_FALLBACK_WEIGHT', 0.25))
                weight = max(0.0, min(1.0, weight))
                overall_score = (1.0 - weight) * overall_score + weight * late_score
                risk_report['late_fusion_score'] = round(float(late_score), 3)
            else:
                risk_report['late_fusion_score'] = None

            overall_score = max(0.0, min(overall_score, 1.0))
            overall_percentage = round(overall_score * 100.0, 1)
            risk_report['overall_risk_score'] = overall_percentage

            high_threshold = getattr(self.config, 'RISK_SCORE_HIGH', 76.0)
            medium_threshold = getattr(self.config, 'RISK_SCORE_MEDIUM', 26.0)
            if high_threshold <= 1.0:
                high_threshold *= 100.0
            if medium_threshold <= 1.0:
                medium_threshold *= 100.0
            high_threshold = max(0.0, min(high_threshold, 100.0))
            medium_threshold = max(0.0, min(medium_threshold, 100.0))
            if high_threshold < medium_threshold:
                high_threshold = medium_threshold

            # Determine risk level using percentage-based tiers
            if overall_percentage >= high_threshold:
                risk_report['risk_level'] = 'high'
            elif overall_percentage >= medium_threshold:
                risk_report['risk_level'] = 'medium'
            else:
                risk_report['risk_level'] = 'low'

            # Identify key risk factors
            risk_report['risk_factors'] = self._identify_risk_factors(
                analysis_results, component_scores
            )
            risk_report['recommendations'] = self._generate_recommendations(
                risk_report['risk_level'], risk_report['risk_factors']
            )
            
        except Exception as e:
            logger.error(f"Risk scoring error: {e}")
            risk_report['error'] = str(e)
        
        return risk_report


    def _score_visual_similarity(self, vision_analysis: Dict) -> float:
        """Score visual similarity component"""
        score = 0.0

        if not vision_analysis:
            return score

        # Check visual similarity metrics
        if vision_analysis.get('visual_similarity'):
            sim = vision_analysis['visual_similarity']
            score += sim.get('structural_similarity', 0) * 0.18
            score += sim.get('color_histogram_similarity', 0) * 0.12
            score += sim.get('feature_similarity', 0) * 0.10

        # Check direct brand logo similarity detection
        brand_logo = vision_analysis.get('brand_logo_similarity')
        if brand_logo:
            score += brand_logo.get('similarity_score', 0) * 0.35
            if brand_logo.get('detected'):
                score += 0.05

        # Check Gemini analysis
        if vision_analysis.get('gemini_analysis'):
            gemini = vision_analysis['gemini_analysis']
            if gemini.get('brand_impersonation_detected'):
                score += 0.10
            confidence = gemini.get('confidence')
            if isinstance(confidence, (int, float)):
                score += max(0.0, min(1.0, confidence / 100)) * 0.10

        return min(1.0, score)


    

    def _score_text_classification(self, text_classification: Dict) -> float:
        """Score text classification component"""
        score = 0.0
        
        if not text_classification:
            return score
        
        # Check classification result
        if text_classification.get('classification'):
            if 'phishing' in text_classification['classification'].lower():
                score += 0.5
            elif 'spam' in text_classification['classification'].lower():
                score += 0.3
        
        # Check detailed scores
        if text_classification.get('detailed_scores'):
            scores = text_classification['detailed_scores']
            score += scores.get('phishing attempt', 0) * 0.2
            score += scores.get('brand impersonation', 0) * 0.2
            score += scores.get('suspicious activity', 0) * 0.1
        
        return min(1.0, score)
    
    def _score_url_features(self, url_features: Dict) -> float:
        """Score URL features component"""
        score = 0.0
        
        if not url_features:
            return score
        
        # Check for suspicious patterns
        suspicious_patterns = url_features.get('suspicious_patterns', [])
        score += len(suspicious_patterns) * 0.15
        
        # Check for IP address usage
        if url_features.get('has_ip'):
            score += 0.3
        
        # Check HTTPS
        if not url_features.get('has_https'):
            score += 0.2
        
        # Check URL length
        if url_features.get('url_length', 0) > 100:
            score += 0.1
        
        return min(1.0, score)
    
    def _score_domain_reputation(self, url_features: Dict) -> float:
        """Score domain reputation component"""
        score = 0.0
        
        if not url_features:
            return score
        
        # Check domain age
        domain_age = url_features.get('domain_age')
        if domain_age is not None:
            if domain_age < 30:
                score += 0.5
            elif domain_age < 180:
                score += 0.3
            elif domain_age < 365:
                score += 0.1
        
        # Check SSL validity
        ssl_info = url_features.get('ssl_info')
        if ssl_info and not ssl_info.get('valid'):
            score += 0.3
        
        # Check WHOIS info
        whois_info = url_features.get('whois_info')
        if whois_info:
            if not whois_info.get('org'):
                score += 0.1
            if whois_info.get('status') and 'clientHold' in str(whois_info['status']):
                score += 0.2
        
        return min(1.0, score)
    
    def _score_content_analysis(self, content_features: Dict) -> float:
        """Score content analysis component"""
        score = 0.0
        
        if not content_features:
            return score
        
        # Check for password fields
        if content_features.get('has_password_field'):
            score += 0.3
        
        # Check number of forms
        if content_features.get('num_forms', 0) > 2:
            score += 0.2
        
        # Check external links
        external_links = content_features.get('external_links', [])
        if len(external_links) > 10:
            score += 0.2
        
        # Check iframe usage
        if content_features.get('iframe_count', 0) > 0:
            score += 0.1
        
        # Check JavaScript usage
        if content_features.get('javascript_refs', 0) > 20:
            score += 0.1
        
        return min(1.0, score)
    
    def _score_behavioral_patterns(self, analysis_results: Dict) -> float:
        """Score behavioral patterns"""
        score = 0.0
        
        # Check OCR results for urgency
        if analysis_results.get('ocr_results'):
            suspicious_phrases = analysis_results['ocr_results'].get('suspicious_phrases', [])
            score += min(0.5, len(suspicious_phrases) * 0.1)
        
        # Check for multiple risk indicators
        risk_indicators = []
        if analysis_results.get('vision_analysis'):
            risk_indicators.extend(
                analysis_results['vision_analysis'].get('risk_indicators', [])
            )
        
        score += min(0.5, len(risk_indicators) * 0.1)
        
        return min(1.0, score)
    
    def _build_fusion_features(self, component_scores: Dict[str, float], analysis_results: Dict) -> Dict[str, float]:
        """Assemble feature vector for the late fusion model."""
        features: Dict[str, float] = {}
        if not component_scores:
            return features

        features.update(component_scores)

        ocr_results = analysis_results.get('ocr_results', {}) or {}
        features['ocr_confidence'] = float(ocr_results.get('confidence') or 0.0)
        features['ocr_character_count'] = float(ocr_results.get('character_count') or 0.0) / 500.0

        vision_analysis = analysis_results.get('vision_analysis', {}) or {}
        gemini_analysis = vision_analysis.get('gemini_analysis', {}) or {}
        gemini_conf = gemini_analysis.get('confidence')
        if isinstance(gemini_conf, (int, float)):
            features['gemini_confidence'] = float(gemini_conf) / 100.0
        else:
            features['gemini_confidence'] = 0.0
        features['brand_logo_detected'] = 1.0 if vision_analysis.get('brand_logo_similarity', {}).get('detected') else 0.0

        text_scores = analysis_results.get('text_classification', {}).get('detailed_scores', {}) or {}
        features['text_phishing_score'] = float(text_scores.get('phishing attempt', 0.0))
        features['text_impersonation_score'] = float(text_scores.get('brand impersonation', 0.0))

        domain_age = analysis_results.get('url_features', {}).get('domain_age')
        if isinstance(domain_age, (int, float)) and domain_age >= 0:
            if domain_age < 30:
                bucket = 0.0
            elif domain_age < 180:
                bucket = 0.33
            elif domain_age < 365:
                bucket = 0.66
            else:
                bucket = 1.0
            features['domain_age_bucket'] = bucket
        else:
            features['domain_age_bucket'] = 0.5

        features['url_has_ip'] = 1.0 if analysis_results.get('url_features', {}).get('has_ip') else 0.0
        patterns = analysis_results.get('url_features', {}).get('suspicious_patterns', []) or []
        features['suspicious_url_patterns'] = float(len(patterns)) / 5.0

        if ocr_results.get('homoglyph_alerts'):
            features['ocr_homoglyph_alert'] = 1.0
        else:
            features['ocr_homoglyph_alert'] = 0.0

        return features

    def _late_fusion_predict(self, features: Dict[str, float]) -> Optional[float]:
        """Invoke the configured late fusion model if available."""
        if not features:
            return None
        if not getattr(self.config, 'ENABLE_LATE_FUSION_MODEL', False):
            return None
        if self._late_fusion_model is None:
            return None
        if not self._fusion_feature_names:
            return None
        vector = [float(features.get(name, 0.0)) for name in self._fusion_feature_names]
        if not any(vector):
            return None
        try:
            if self.config.LATE_FUSION_MODEL_TYPE == 'xgboost' and xgb is not None:
                dmatrix = xgb.DMatrix([vector], feature_names=self._fusion_feature_names)
                score = float(self._late_fusion_model.predict(dmatrix)[0])
            else:
                model = self._late_fusion_model
                if hasattr(model, 'predict_proba'):
                    score = float(model.predict_proba([vector])[0][1])
                elif hasattr(model, 'predict'):
                    score = float(model.predict([vector])[0])
                else:
                    return None
            return max(0.0, min(1.0, score))
        except Exception as exc:
            logger.error("Late fusion prediction failed: %s", exc)
            return None

    def _load_late_fusion_model(self):
        if not getattr(self.config, 'ENABLE_LATE_FUSION_MODEL', False):
            return None
        model_path = Path(getattr(self.config, 'LATE_FUSION_MODEL_PATH', ''))
        if not model_path or not model_path.exists():
            logger.info("Late fusion model not found at %s; using weighted heuristics.", model_path)
            return None
        try:
            if self.config.LATE_FUSION_MODEL_TYPE == 'xgboost':
                if xgb is None:
                    logger.error("xgboost not installed; cannot load late fusion model.")
                    return None
                booster = xgb.Booster()
                booster.load_model(str(model_path))
                logger.info("Loaded XGBoost late fusion model from %s", model_path)
                return booster
            if joblib is None:
                logger.error("joblib not available; cannot load sklearn late fusion model.")
                return None
            model = joblib.load(model_path)
            logger.info("Loaded late fusion model from %s", model_path)
            return model
        except Exception as exc:
            logger.error("Failed to load late fusion model at %s: %s", model_path, exc)
            return None

    def _identify_risk_factors(self, analysis_results: Dict, component_scores: Dict) -> List[str]:
        """Identify key risk factors"""
        risk_factors = []
        
        # High component scores
        for component, score in component_scores.items():
            if score >= 0.7:
                risk_factors.append(f"high_{component}_score")
        
        # Specific risk indicators
        if analysis_results.get('vision_analysis', {}).get('gemini_analysis', {}).get('brand_impersonation_detected'):
            risk_factors.append('ai_detected_impersonation')
        
        if analysis_results.get('url_features', {}).get('has_ip'):
            risk_factors.append('ip_address_in_url')
        
        # Safely handle missing or None domain_age values
        domain_age = analysis_results.get('url_features', {}).get('domain_age')
        if isinstance(domain_age, (int, float)) and domain_age < 30:
            risk_factors.append('newly_registered_domain')
        
        if analysis_results.get('ocr_results', {}).get('brand_mentions'):
            risk_factors.append('unauthorized_brand_usage')
        
        return risk_factors
    
    def _generate_recommendations(self, risk_level: str, risk_factors: List[str]) -> List[str]:
        """Generate actionable recommendations"""
        recommendations = []
        
        if risk_level == 'high':
            recommendations.append('IMMEDIATE ACTION: Block this domain/URL')
            recommendations.append('File takedown request with hosting provider')
            recommendations.append('Report to relevant authorities')
            recommendations.append('Alert legal team for potential trademark infringement')
            
        elif risk_level == 'medium':
            recommendations.append('Monitor this site closely for changes')
            recommendations.append('Consider sending cease and desist notice')
            recommendations.append('Add to watchlist for regular checks')
            
        else:
            recommendations.append('Continue routine monitoring')
            recommendations.append('No immediate action required')
        
        # Specific recommendations based on risk factors
        if 'newly_registered_domain' in risk_factors:
            recommendations.append('Track domain registration changes')
        
        if 'unauthorized_brand_usage' in risk_factors:
            recommendations.append('Document brand usage for legal action')
        
        if 'ai_detected_impersonation' in risk_factors:
            recommendations.append('Preserve evidence for enforcement action')
        
        return recommendations
