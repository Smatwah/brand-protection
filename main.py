# Complete Brand Protection System - Full Implementation

## 1. Main Pipeline (main.py)


"""
Main Pipeline Orchestrator for Brand Protection System
Full Production Implementation
"""
import asyncio
import os
import sys
import json
from datetime import datetime
from typing import Dict, List, Optional
import logging
from pathlib import Path

# Fix Unicode issues in Windows
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Add project root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import Config
from discovery_watchers import DiscoveryWatcher, QueueManager
from render_screenshot import RenderScreenshot
from ocr_processing import OCRProcessor
from text_classifier import TextClassifier
from feature_extraction import FeatureExtractor
from risk_scoring import RiskScorer
from notification import NotificationManager

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('brand_protection.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class BrandProtectionPipeline:
    def __init__(self):
        self.config = Config()
        self._setup_directories()
        self._initialize_components()
        self.queue_manager = QueueManager()
        logger.info(f"Brand Protection System initialized for: {self.config.BRAND_NAME}")
    
    def _setup_directories(self):
        """Create necessary directories"""
        directories = [
            self.config.DATA_DIR,
            self.config.SCREENSHOTS_DIR,
            self.config.REPORTS_DIR,
            self.config.MODELS_DIR,
            getattr(self.config, "LOGO_MATCHES_DIR", "data/logo_matches"),
            "assets"
        ]
        
        for directory in directories:
            Path(directory).mkdir(parents=True, exist_ok=True)
    
    def _initialize_components(self):
        """Initialize all pipeline components"""
        logger.info("Initializing Brand Protection Pipeline components...")

        # Initialize components one by one with clear logs so failures are visible
        self.discovery_watcher = None
        self.render_screenshot = None
        self.vision_analyzer = None
        self.ocr_processor = None
        self.text_classifier = None
        self.feature_extractor = None
        self.risk_scorer = None
        self.notification_manager = None

        try:
            logger.info("Initializing: DiscoveryWatcher")
            self.discovery_watcher = DiscoveryWatcher(self.config)
            logger.info("Initialized: DiscoveryWatcher")
        except Exception as e:
            logger.error(f"DiscoveryWatcher init failed: {e}")

        try:
            logger.info("Initializing: RenderScreenshot")
            self.render_screenshot = RenderScreenshot(self.config)
            logger.info("Initialized: RenderScreenshot")
        except Exception as e:
            logger.error(f"RenderScreenshot init failed: {e}")

        if getattr(self.config, 'ENABLE_VISION', False):
            try:
                logger.info("Initializing: VisionAnalyzer")
                from vision_analysis import VisionAnalyzer
                self.vision_analyzer = VisionAnalyzer(self.config)
                logger.info("Initialized: VisionAnalyzer")
            except Exception as ve:
                logger.warning(f"Vision disabled due to initialization error: {ve}")

        try:
            logger.info("Initializing: OCRProcessor")
            self.ocr_processor = OCRProcessor(self.config)
            logger.info("Initialized: OCRProcessor")
        except Exception as e:
            logger.error(f"OCRProcessor init failed: {e}")

        try:
            logger.info("Initializing: TextClassifier")
            self.text_classifier = TextClassifier(self.config)
            logger.info("Initialized: TextClassifier")
        except Exception as e:
            logger.error(f"TextClassifier init failed: {e}")

        try:
            logger.info("Initializing: FeatureExtractor")
            self.feature_extractor = FeatureExtractor(self.config)
            logger.info("Initialized: FeatureExtractor")
        except Exception as e:
            logger.error(f"FeatureExtractor init failed: {e}")

        try:
            logger.info("Initializing: RiskScorer")
            self.risk_scorer = RiskScorer(self.config)
            logger.info("Initialized: RiskScorer")
        except Exception as e:
            logger.error(f"RiskScorer init failed: {e}")

        try:
            logger.info("Initializing: NotificationManager")
            self.notification_manager = NotificationManager(self.config)
            logger.info("Initialized: NotificationManager")
        except Exception as e:
            logger.error(f"NotificationManager init failed: {e}")

        logger.info("All components initialization step completed.")
    
    async def run_discovery_phase(self):
        """Run discovery watchers to find potential threats"""
        logger.info("Starting discovery phase...")
        logger.info(f"Brand: {self.config.BRAND_NAME}")
        logger.info(f"Domains: {', '.join(self.config.BRAND_DOMAINS)}")
        
        discovered_items = []
        
        # Run all discovery watchers
        tasks = [
            self.discovery_watcher.watch_transparency_reports(),
            self.discovery_watcher.watch_typosquatting(),
            self.discovery_watcher.watch_social_media(),
            self.discovery_watcher.watch_web_mentions(),
            self.discovery_watcher.watch_visual_mentions()
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for result in results:
            if isinstance(result, list):
                discovered_items.extend(result)
            elif isinstance(result, Exception):
                logger.error(f"Discovery error: {result}")
        
        # Add items to queue
        await self.queue_manager.add_items(discovered_items)
        
        logger.info(f"Discovery phase completed. Found {len(discovered_items)} potential threats.")
        return discovered_items
    
    async def process_item(self, item: Dict) -> Dict:
        """Process a single discovered item through the pipeline"""
        logger.info(f"Processing: {item.get('url', item.get('type'))}")
        
        analysis_results = {
            'item': item,
            'timestamp': datetime.now().isoformat(),
            'url': item.get('url')
        }
        
        try:
            # Phase 1: Render & Screenshot
            if item.get('url'):
                await self.render_screenshot.initialize()
                screenshot_data = await self.render_screenshot.capture_screenshot(item['url'])
                analysis_results['screenshot_data'] = screenshot_data
                
                if screenshot_data.get('screenshot_path'):
                    # Phase 2: Vision Analysis (optional)
                    if self.vision_analyzer is not None:
                        vision_results = await self.vision_analyzer.analyze_screenshot(
                            screenshot_data['screenshot_path'],
                            {'brand_name': self.config.BRAND_NAME}
                        )
                        analysis_results['vision_analysis'] = vision_results
                    else:
                        logger.info("Vision analysis disabled. Set ENABLE_VISION=1 to enable.")
                    
                    # Phase 3: OCR Processing (optional)
                    if getattr(self.config, 'ENABLE_OCR', True):
                        ocr_results = await self.ocr_processor.process_image(
                            screenshot_data['screenshot_path']
                        )
                        analysis_results['ocr_results'] = ocr_results
                    else:
                        logger.info("OCR disabled. Set ENABLE_OCR=1 to enable.")
                
                # Phase 4: Text Classification
                if screenshot_data.get('text_content'):
                    text_classification = await self.text_classifier.classify_text(
                        screenshot_data['text_content']
                    )
                    analysis_results['text_classification'] = text_classification
                
                # Phase 5: Feature Extraction
                url_features = await self.feature_extractor.extract_url_features(item['url'])
                analysis_results['url_features'] = url_features
                
                if screenshot_data.get('page_content'):
                    content_features = await self.feature_extractor.extract_content_features(
                        screenshot_data['page_content']
                    )
                    analysis_results['content_features'] = content_features
                
                await self.render_screenshot.cleanup()
            
            # Phase 6: Risk Scoring
            risk_report = await self.risk_scorer.calculate_risk_score(analysis_results)
            analysis_results['risk_report'] = risk_report

            # Phase 7: Decision & Notification
            raw_level = str(risk_report.get('risk_level', '')).lower().strip()
            raw_score = (
                risk_report.get('overall_risk_score')
                or risk_report.get('risk_score')
                or risk_report.get('score')
            )
            risk_score_value = None
            try:
                if raw_score is not None:
                    risk_score_value = float(raw_score)
                    if risk_score_value <= 1:
                        risk_score_value *= 100
                    risk_score_value = max(0.0, min(risk_score_value, 100.0))
            except (TypeError, ValueError):
                risk_score_value = None

            should_notify = False
            if risk_score_value is not None:
                should_notify = risk_score_value >= 26
            else:
                should_notify = raw_level in {"high", "medium"}

            if should_notify and self.notification_manager is not None:
                await self.notification_manager.send_alert(
                    risk_report,
                    detection_type='impersonation',
                    context=analysis_results,
                )
                risk_level_display = risk_report.get('risk_level', 'unknown').upper()
                logger.warning(
                    f"ALERT: {risk_level_display} risk - {item.get('url', 'unknown URL')}"
                )

            # Save report
            self._save_report(analysis_results)

        except Exception as e:
            logger.error(f"Error processing item: {e}")
            analysis_results['error'] = str(e)

        return analysis_results
    
    def _save_report(self, analysis_results: Dict):
        """Save analysis report to file"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            risk_level = analysis_results.get('risk_report', {}).get('risk_level', 'unknown')
            
            filename = f"{self.config.REPORTS_DIR}/report_{risk_level}_{timestamp}.json"
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(analysis_results, f, indent=2, default=str)
            
            logger.info(f"Report saved: {filename}")
        except Exception as e:
            logger.error(f"Error saving report: {e}")
    
    async def run_pipeline(self):
        """Run the complete brand protection pipeline"""
        logger.info("=" * 70)
        logger.info("STARTING BRAND PROTECTION PIPELINE")
        logger.info("=" * 70)
        
        start_time = datetime.now()
        
        # Phase 1: Discovery
        discovered_items = await self.run_discovery_phase()
        
        # Phase 2: Process discovered items
        results = []
        while not self.queue_manager.is_empty():
            item = await self.queue_manager.get_next_item()
            result = await self.process_item(item)
            results.append(result)
        
        # Generate summary report
        summary = self._generate_summary_report(results)
        
        # Save summary
        self._save_summary(summary)
        
        elapsed_time = (datetime.now() - start_time).total_seconds()
        
        logger.info("=" * 70)
        logger.info("PIPELINE EXECUTION COMPLETED")
        logger.info(f"Time elapsed: {elapsed_time:.2f} seconds")
        logger.info(f"Items processed: {summary['total_items_processed']}")
        logger.info(f"High risk: {summary['high_risk_count']}")
        logger.info(f"Medium risk: {summary['medium_risk_count']}")
        logger.info(f"Low risk: {summary['low_risk_count']}")
        logger.info("=" * 70)
        
        return results
    
    def _generate_summary_report(self, results: List[Dict]) -> Dict:
        """Generate summary report of pipeline execution"""
        summary = {
            'timestamp': datetime.now().isoformat(),
            'brand': self.config.BRAND_NAME,
            'total_items_processed': len(results),
            'high_risk_count': 0,
            'medium_risk_count': 0,
            'low_risk_count': 0,
            'errors': 0,
            'threats_detected': []
        }
        
        for result in results:
            if result.get('error'):
                summary['errors'] += 1
            elif result.get('risk_report'):
                risk_level = result['risk_report'].get('risk_level', 'low')
                summary[f'{risk_level}_risk_count'] += 1
                
                if risk_level in ['high', 'medium']:
                    summary['threats_detected'].append({
                        'url': result.get('url'),
                        'risk_level': risk_level,
                        'risk_score': result['risk_report'].get('overall_risk_score'),
                        'timestamp': result.get('timestamp')
                    })
        
        return summary
    
    def _save_summary(self, summary: Dict):
        """Save summary report"""
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{self.config.REPORTS_DIR}/summary_{timestamp}.json"
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, default=str)
            
            logger.info(f"Summary saved: {filename}")
        except Exception as e:
            logger.error(f"Error saving summary: {e}")
    
    async def test_with_url(self, test_url: str):
        """Test the system with a specific URL"""
        logger.info(f"Testing with URL: {test_url}")
        
        test_item = {
            'url': test_url,
            'source': 'manual_test',
            'type': 'domain',
            'timestamp': datetime.now().isoformat()
        }
        
        result = await self.process_item(test_item)
        
        if result.get('risk_report'):
            risk_level = result['risk_report']['risk_level']
            risk_score = result['risk_report']['overall_risk_score']
            logger.info(f"Test Result: {risk_level.upper()} risk (score: {risk_score:.2f})")
            
            if result['risk_report'].get('risk_factors'):
                logger.info("Risk Factors:")
                for factor in result['risk_report']['risk_factors']:
                    logger.info(f"  - {factor}")
        
        return result

async def main():
    """Main entry point"""
    pipeline = BrandProtectionPipeline()
    
    # Check if this is a test run or full scan
    if len(sys.argv) > 1:
        if sys.argv[1] == '--test' and len(sys.argv) > 2:
            # Test mode with specific URL
            test_url = sys.argv[2]
            await pipeline.test_with_url(test_url)
        elif sys.argv[1] == '--help':
            print("Usage:")
            print("  python main.py              # Run full brand protection scan")
            print("  python main.py --test URL   # Test with specific URL")
            print("  python main.py --monitor    # Run continuous monitoring")
        elif sys.argv[1] == '--monitor':
            # Continuous monitoring mode
            logger.info("Starting continuous monitoring mode...")
            while True:
                await pipeline.run_pipeline()
                logger.info(f"Waiting {pipeline.config.MONITORING_INTERVAL} seconds...")
                await asyncio.sleep(pipeline.config.MONITORING_INTERVAL)
    else:
        # Run full pipeline once
        await pipeline.run_pipeline()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down Brand Protection System...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
