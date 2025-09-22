"""
Configuration file for Brand Protection System
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _env_flag(name: str, default: str = '0') -> bool:
    value = os.getenv(name)
    if value is None:
        value = default
    return value.strip().lower() in ('1', 'true', 'yes', 'on')

def _env_list(name: str, default: str) -> list[str]:
    value = os.getenv(name)
    if value is None:
        value = default
    return [item.strip() for item in value.split(',') if item.strip()]

class Config:
    # API Keys
    GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'AIzaSyARfPhzmrC5Bx-H4XoPfhZbPdsoStLo43M')
    OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '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')
    SLACK_TOKEN = os.getenv('SLACK_TOKEN', 'xapp-1-A09G6G8LFNF-9560099773188-fd30e7ac4c8cf73f08fd4879e15661f1365b959c07b246c5f088fa4123b2ccd5')

    # GPU / Hardware configuration
    GPU_DEVICE = os.getenv('GPU_DEVICE', 'cuda').strip() or 'cuda'

    # Feature toggles (enable/disable heavy components)
    ENABLE_VISION = _env_flag('ENABLE_VISION', '1')
    ENABLE_OCR = _env_flag('ENABLE_OCR', '1')
    ENABLE_SOCIAL_MEDIA = _env_flag('ENABLE_SOCIAL_MEDIA', '1')
    ENABLE_WEB_DISCOVERY = _env_flag('ENABLE_WEB_DISCOVERY', '1')
    ENABLE_SOCIAL_IMAGE_DISCOVERY = _env_flag('ENABLE_SOCIAL_IMAGE_DISCOVERY', '1')

    WEB_DISCOVERY_ENGINES = _env_list('WEB_DISCOVERY_ENGINES', 'duckduckgo,bing,google_news')
    IMAGE_DISCOVERY_ENGINES = _env_list('IMAGE_DISCOVERY_ENGINES', 'bing_images,duckduckgo_images')
    SOCIAL_IMAGE_PLATFORMS = _env_list('SOCIAL_IMAGE_PLATFORMS', 'reddit')

    # Twitter / social API credentials
    TWITTER_BEARER_TOKEN = (os.getenv('TWITTER_BEARER_TOKEN', '').strip() or None)
    TWITTER_API_KEY = (os.getenv('TWITTER_API_KEY', '').strip() or None)
    TWITTER_API_SECRET = (os.getenv('TWITTER_API_SECRET', '').strip() or None)
    TWITTER_CLIENT_ID = (os.getenv('TWITTER_CLIENT_ID', '').strip() or None)
    TWITTER_CLIENT_SECRET = (os.getenv('TWITTER_CLIENT_SECRET', '').strip() or None)
    TWITTER_REFRESH_TOKEN = (os.getenv('TWITTER_REFRESH_TOKEN', '').strip() or None)
    TWITTER_REDIRECT_URI = (os.getenv('TWITTER_REDIRECT_URI', '').strip() or None)
    TWITTER_SCOPE = os.getenv('TWITTER_SCOPE', 'tweet.read users.read').strip()

    INSTAGRAM_ACCESS_TOKEN = (os.getenv('INSTAGRAM_ACCESS_TOKEN', '').strip() or None)
    INSTAGRAM_GRAPH_USER_ID = (os.getenv('INSTAGRAM_GRAPH_USER_ID', '').strip() or None)
    REDDIT_CLIENT_ID = (os.getenv('REDDIT_CLIENT_ID', '').strip() or None)
    REDDIT_CLIENT_SECRET = (os.getenv('REDDIT_CLIENT_SECRET', '').strip() or None)

    # Lightweight mode to avoid large models on low-RAM systems
    LIGHTWEIGHT_MODE = _env_flag('LIGHTWEIGHT_MODE', '1')

    # NLP model toggles
    ENABLE_ZERO_SHOT = _env_flag('ENABLE_ZERO_SHOT', '1')
    _env_enable_phishing = os.getenv('ENABLE_PHISHING_MODEL')
    ENABLE_PHISHING_MODEL = (
        (_env_enable_phishing.lower() in ('1', 'true', 'yes', 'on'))
        if isinstance(_env_enable_phishing, str)
        else (not LIGHTWEIGHT_MODE)
    )

    ZERO_SHOT_MODEL = os.getenv(
        'ZERO_SHOT_MODEL',
        'typeform/distilbert-base-uncased-mnli' if LIGHTWEIGHT_MODE else 'facebook/bart-large-mnli'
    )
    TEXT_CLASSIFIER_MODEL = os.getenv(
        'TEXT_CLASSIFIER_MODEL',
        'ealvaradob/bert-finetuned-phishing'
    )
    DEFER_NLP_INIT = _env_flag('DEFER_NLP_INIT', '1')

    # OCR configuration and normalization
    OCR_LANGUAGES = os.getenv('OCR_LANGUAGES', 'eng+ara')
    OCR_PSM = int(os.getenv('OCR_PSM', '6'))
    OCR_OEM = int(os.getenv('OCR_OEM', '3'))
    OCR_MIN_CONFIDENCE = float(os.getenv('OCR_MIN_CONFIDENCE', '0.3'))
    ENABLE_TROCR = _env_flag('ENABLE_TROCR', '0')
    TROCR_MODEL_NAME = os.getenv('TROCR_MODEL_NAME', 'microsoft/trocr-base-printed')
    TROCR_PROCESSOR_NAME = os.getenv('TROCR_PROCESSOR_NAME', 'microsoft/trocr-base-printed')
    ENABLE_ARABIC_NORMALIZATION = _env_flag('ENABLE_ARABIC_NORMALIZATION', '1')
    ENABLE_MIXED_SCRIPT_ALERTS = _env_flag('ENABLE_MIXED_SCRIPT_ALERTS', '1')

    # Brand Information
    BRAND_NAME = "tuwaiq , طويق"
    BRAND_LOGO_PATH = 'assets/brand_logo.png'
    BRAND_KEYWORDS = ["tuwaiq academy", "اكاديمية طويق", "طويق"]
    BRAND_DOMAINS = ["tuwaiq.edu.sa", "tuwaiq.edu"]

    # Monitoring Settings
    MONITORING_INTERVAL = int(os.getenv('MONITORING_INTERVAL', '3600'))
    CONFIDENCE_THRESHOLD = float(os.getenv('CONFIDENCE_THRESHOLD', '0.75'))

    # Paths
    DATA_DIR = 'data'
    SCREENSHOTS_DIR = 'data/screenshots'
    REPORTS_DIR = 'data/reports'
    MODELS_DIR = 'models'
    LOGO_MATCHES_DIR = 'data/logo_matches'
    DISCOVERY_LOG_PATH = os.getenv('DISCOVERY_LOG_PATH', str(Path('data') / 'logs' / 'discovery_watchers.log'))
    DISCOVERY_ERROR_EXPORT = os.getenv('DISCOVERY_ERROR_EXPORT', str(Path('data') / 'logs' / 'watcher_errors.jsonl'))

    # Detection Thresholds
    LOGO_SIMILARITY_THRESHOLD = float(os.getenv('LOGO_SIMILARITY_THRESHOLD', '0.85'))
    TEXT_SIMILARITY_THRESHOLD = float(os.getenv('TEXT_SIMILARITY_THRESHOLD', '0.80'))
    RISK_SCORE_HIGH = float(os.getenv('RISK_SCORE_HIGH', '0.76'))
    RISK_SCORE_MEDIUM = float(os.getenv('RISK_SCORE_MEDIUM', '0.26'))

    # Late fusion model configuration
    ENABLE_LATE_FUSION_MODEL = _env_flag('ENABLE_LATE_FUSION_MODEL', '1')
    LATE_FUSION_MODEL_PATH = os.getenv('LATE_FUSION_MODEL_PATH', str(Path('models') / 'late_fusion_model.pkl'))
    LATE_FUSION_MODEL_TYPE = os.getenv('LATE_FUSION_MODEL_TYPE', 'logistic').strip().lower()
    LATE_FUSION_FEATURES = _env_list(
        'LATE_FUSION_FEATURES',
        'visual_similarity,text_classification,url_features,domain_reputation,content_analysis,behavioral_patterns,ocr_confidence,ocr_character_count,gemini_confidence,text_phishing_score,text_impersonation_score,brand_logo_detected,domain_age_bucket,url_has_ip,suspicious_url_patterns,ocr_homoglyph_alert'
    )
    LATE_FUSION_MIN_FALLBACK_WEIGHT = float(os.getenv('LATE_FUSION_MIN_FALLBACK_WEIGHT', '0.35'))

    # Notification Settings
    ENABLE_NOTIFICATIONS = _env_flag('ENABLE_NOTIFICATIONS', '1')
    NOTIFICATION_METHODS = _env_list('NOTIFICATION_METHODS', 'email,slack')
    SLACK_CHANNEL = os.getenv('SLACK_CHANNEL', '#brand-protection')
    EMAIL_RECIPIENTS = [addr.strip() for addr in os.getenv('EMAIL_RECIPIENTS', 'hmooud.bader@yourbrand.com').split(',') if addr.strip()]
    EMAIL_SMTP_SERVER = os.getenv('EMAIL_SMTP_SERVER', 'localhost')
    EMAIL_SMTP_PORT = int(os.getenv('EMAIL_SMTP_PORT', '587'))
    EMAIL_SMTP_USERNAME = (os.getenv('EMAIL_SMTP_USERNAME', '').strip() or None)
    EMAIL_SMTP_PASSWORD = (os.getenv('EMAIL_SMTP_PASSWORD', '').strip() or None)
    EMAIL_FROM_ADDRESS = os.getenv('EMAIL_FROM_ADDRESS', 'alerts@brandprotection.local')
    EMAIL_USE_TLS = _env_flag('EMAIL_USE_TLS', '1')
    EMAIL_USE_SSL = _env_flag('EMAIL_USE_SSL', '0')

    # OCR / Tesseract configuration
    TESSERACT_CMD = os.getenv('TESSERACT_CMD', '').strip() or None
    TESSDATA_PREFIX = os.getenv('TESSDATA_PREFIX', '').strip() or None

    # Discovery / network timeouts
    CERTIFICATE_TRANSPARENCY_URL = os.getenv('CERTIFICATE_TRANSPARENCY_URL', 'https://crt.sh/')
    DISCOVERY_MAX_RETRIES = int(os.getenv('DISCOVERY_MAX_RETRIES', '2'))
    DISCOVERY_RETRY_DELAY_SECONDS = int(os.getenv('DISCOVERY_RETRY_DELAY_SECONDS', '30'))
    DISCOVERY_REQUEST_TIMEOUT_SECONDS = int(os.getenv('DISCOVERY_REQUEST_TIMEOUT_SECONDS', '30'))

    # Playwright / Rendering behavior
    PLAYWRIGHT_NAV_TIMEOUT_MS = int(os.getenv('PLAYWRIGHT_NAV_TIMEOUT_MS', '60000'))
    PLAYWRIGHT_WAIT_UNTIL = os.getenv('PLAYWRIGHT_WAIT_UNTIL', 'domcontentloaded')
    IGNORE_HTTPS_ERRORS = _env_flag('IGNORE_HTTPS_ERRORS', '1')
    SCREENSHOT_FULL_PAGE = _env_flag('SCREENSHOT_FULL_PAGE', '1')

