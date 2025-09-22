"""
Text Classification: Classify text using ML models
"""
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
import torch
from typing import Dict, List
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import logging

from normalization import analyze_script_mix, fold_confusables, normalize_arabic_text

logger = logging.getLogger(__name__)

class TextClassifier:
    def __init__(self, config):
        self.config = config
        self.classifier = None
        self.tokenizer = None
        self.tfidf_vectorizer = TfidfVectorizer(max_features=1000)
        self._models_attempted = False
        # Optionally defer model loading to avoid blocking startup
        if not getattr(self.config, 'DEFER_NLP_INIT', True):
            self._initialize_models()
    
    def _initialize_models(self):
        """Initialize text classification models"""
        self.zero_shot_classifier = None
        device = 0 if torch.cuda.is_available() else -1
        logger.info(f"Device set to use {'cuda' if device == 0 else 'cpu'}")

        # Try to load a phishing-specific classifier (optional, can be heavy)
        if getattr(self.config, 'ENABLE_PHISHING_MODEL', False):
            try:
                self.classifier = pipeline(
                    "text-classification",
                    model=self.config.TEXT_CLASSIFIER_MODEL,
                    device=device,
                    model_kwargs={"low_cpu_mem_usage": True}
                )
            except Exception as e:
                logger.error(f"Error initializing phishing classifier ('{self.config.TEXT_CLASSIFIER_MODEL}'): {e}")
                self.classifier = None

        # Zero-shot classifier (lighter default in lightweight mode)
        if getattr(self.config, 'ENABLE_ZERO_SHOT', True):
            try:
                self.zero_shot_classifier = pipeline(
                    "zero-shot-classification",
                    model=self.config.ZERO_SHOT_MODEL,
                    device=device,
                    model_kwargs={"low_cpu_mem_usage": True}
                )
            except Exception as e:
                logger.error(f"Error initializing zero-shot model ('{self.config.ZERO_SHOT_MODEL}'): {e}")
                # Fallback to a smaller MNLI model if not already tried
                if self.config.ZERO_SHOT_MODEL != "typeform/distilbert-base-uncased-mnli":
                    try:
                        self.zero_shot_classifier = pipeline(
                            "zero-shot-classification",
                            model="typeform/distilbert-base-uncased-mnli",
                            device=device,
                            model_kwargs={"low_cpu_mem_usage": True}
                        )
                        logger.info("Fell back to 'typeform/distilbert-base-uncased-mnli' for zero-shot.")
                    except Exception as e2:
                        logger.error(f"Zero-shot fallback failed: {e2}")
                        self.zero_shot_classifier = None

        # If neither model is available, we will rely on heuristics and similarity analysis
        if self.classifier is None and self.zero_shot_classifier is None:
            logger.warning("No NLP models loaded; classification will rely on heuristics only.")
        self._models_attempted = True

    def _ensure_models(self):
        """Lazy-load models on first use if deferred and not yet attempted."""
        if not self._models_attempted and getattr(self.config, 'DEFER_NLP_INIT', True):
            try:
                self._initialize_models()
            except Exception as e:
                logger.error(f"Deferred NLP model init failed: {e}")
    
    async def classify_text(self, text: str, context: Dict = None) -> Dict:
        """Classify text for brand impersonation"""
        # Lazy init models if needed
        self._ensure_models()
        normalized_input = text
        folded_input = text
        script_mix = None
        if getattr(self.config, 'ENABLE_ARABIC_NORMALIZATION', True):
            normalized_input = normalize_arabic_text(text)
            folded_input = fold_confusables(normalized_input)
            script_mix = analyze_script_mix(text)
        results = {
            'text': text[:500],  # Store first 500 chars
            'classification': None,
            'confidence': 0.0,
            'risk_level': 'low',
            'detailed_scores': {}
        }
        if getattr(self.config, 'ENABLE_ARABIC_NORMALIZATION', True):
            results['normalized_text'] = normalized_input[:500]
            results['folded_text'] = folded_input[:500]
            if script_mix:
                results['script_mix'] = script_mix

        try:
            inference_text = folded_input if getattr(self.config, 'ENABLE_ARABIC_NORMALIZATION', True) else text
            # Primary classification (phishing model, if available)
            if self.classifier:
                classification = self.classifier(inference_text[:512])
                if classification:
                    results['classification'] = classification[0].get('label')
                    results['confidence'] = float(classification[0].get('score', 0.0))

            # Zero-shot classification for specific threats
            if self.zero_shot_classifier:
                candidate_labels = ["phishing attempt", "legitimate content", "brand impersonation", "suspicious activity", "marketing spam"]
                zero_shot_result = self.zero_shot_classifier(
                    inference_text[:512],
                    candidate_labels=candidate_labels,
                    multi_label=True
                )

                if isinstance(zero_shot_result, list):
                    zero_shot_result = zero_shot_result[0]
                results['detailed_scores'] = dict(zip(
                    zero_shot_result.get('labels', []),
                    [float(s) for s in zero_shot_result.get('scores', [])]
                ))

            # Calculate risk level
            results['risk_level'] = self._calculate_risk_level(results)

            # Additional pattern matching
            results['pattern_analysis'] = self._analyze_patterns(inference_text)

        except Exception as e:
            logger.error(f"Text classification error: {e}")
            results['error'] = str(e)

        return results

    def _calculate_risk_level(self, classification_results: Dict) -> str:
        """Calculate risk level based on classification results"""
        risk_score = 0.0
        
        # Check primary classification
        if classification_results.get('classification'):
            if 'phishing' in classification_results['classification'].lower():
                risk_score += 0.5
            elif 'spam' in classification_results['classification'].lower():
                risk_score += 0.3
        
        # Check detailed scores
        if classification_results.get('detailed_scores'):
            scores = classification_results['detailed_scores']
            risk_score += scores.get('phishing attempt', 0) * 0.3
            risk_score += scores.get('brand impersonation', 0) * 0.3
            risk_score += scores.get('suspicious activity', 0) * 0.2
            risk_score -= scores.get('legitimate content', 0) * 0.3
        
        # Normalize risk score
        risk_score = max(0, min(1, risk_score))
        
        if risk_score >= self.config.RISK_SCORE_HIGH:
            return 'high'
        elif risk_score >= self.config.RISK_SCORE_MEDIUM:
            return 'medium'
        else:
            return 'low'
    
    def _analyze_patterns(self, text: str) -> Dict:
        """Analyze text patterns for impersonation indicators"""
        patterns = {
            'urgency_indicators': 0,
            'authority_claims': 0,
            'personal_info_requests': 0,
            'link_density': 0,
            'grammar_issues': 0
        }
        
        text_lower = text.lower()
        
        # Urgency indicators
        urgency_words = ['urgent', 'immediate', 'expire', 'suspend', 'deadline', 'act now']
        patterns['urgency_indicators'] = sum(1 for word in urgency_words if word in text_lower)
        
        # Authority claims
        authority_words = ['official', 'authorized', 'verified', 'certified', 'legitimate']
        patterns['authority_claims'] = sum(1 for word in authority_words if word in text_lower)
        
        # Personal info requests
        info_requests = ['password', 'ssn', 'social security', 'credit card', 'bank account', 'pin']
        patterns['personal_info_requests'] = sum(1 for word in info_requests if word in text_lower)
        
        # Link density
        import re
        links = re.findall(r'https?://[^\s]+', text)
        patterns['link_density'] = len(links) / max(len(text.split()), 1)
        
        return patterns

    async def compare_with_legitimate(self, suspicious_text: str, legitimate_texts: List[str]) -> Dict:
        """Compare suspicious text with known legitimate texts"""
        comparison_results = {
            'max_similarity': 0.0,
            'avg_similarity': 0.0,
            'most_similar_index': -1,
            'is_likely_legitimate': False
        }
        
        try:
            if not legitimate_texts:
                return comparison_results
            
            # Vectorize all texts
            all_texts = [suspicious_text] + legitimate_texts
            tfidf_matrix = self.tfidf_vectorizer.fit_transform(all_texts)
            
            # Calculate similarities
            similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()
            
            comparison_results['max_similarity'] = float(np.max(similarities))
            comparison_results['avg_similarity'] = float(np.mean(similarities))
            comparison_results['most_similar_index'] = int(np.argmax(similarities))
            
            # Determine if likely legitimate
            comparison_results['is_likely_legitimate'] = comparison_results['max_similarity'] > 0.85
            
        except Exception as e:
            logger.error(f"Text comparison error: {e}")
        
        return comparison_results
