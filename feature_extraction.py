"""
Feature Extraction: Extract features from URLs and content
"""
import re
import urllib.parse
from typing import Dict, List, Optional
import whois
import dns.resolver
import requests
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

class FeatureExtractor:
    def __init__(self, config):
        self.config = config
        self.dns_resolver = dns.resolver.Resolver()
        self.dns_resolver.timeout = 5
        self.dns_resolver.lifetime = 5
    
    async def extract_url_features(self, url: str) -> Dict:
        """Extract features from URL"""
        features = {
            'url': url,
            'domain': None,
            'subdomain': None,
            'path': None,
            'url_length': len(url),
            'has_ip': False,
            'has_https': url.startswith('https'),
            'suspicious_patterns': [],
            'domain_age': None,
            'whois_info': None,
            'dns_records': None,
            'ssl_info': None
        }
        
        try:
            # Parse URL
            parsed = urllib.parse.urlparse(url)
            features['domain'] = parsed.netloc
            features['path'] = parsed.path
            
            # Check for IP address
            ip_pattern = r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'
            if re.search(ip_pattern, parsed.netloc):
                features['has_ip'] = True
            
            # Extract subdomain
            domain_parts = parsed.netloc.split('.')
            if len(domain_parts) > 2:
                features['subdomain'] = '.'.join(domain_parts[:-2])
            
            # Check suspicious patterns
            features['suspicious_patterns'] = self._check_suspicious_url_patterns(url)
            
            # Get WHOIS information
            features['whois_info'] = await self._get_whois_info(parsed.netloc)
            
            # Get DNS records
            features['dns_records'] = await self._get_dns_records(parsed.netloc)
            
            # Check SSL certificate
            features['ssl_info'] = await self._check_ssl_certificate(url)
            
            # Calculate domain age
            if features['whois_info'] and features['whois_info'].get('creation_date'):
                creation_date = features['whois_info']['creation_date']
                if isinstance(creation_date, list):
                    creation_date = creation_date[0]
                age = (datetime.now() - creation_date).days
                features['domain_age'] = age
            
        except Exception as e:
            logger.error(f"URL feature extraction error: {e}")
            features['error'] = str(e)
        
        return features
    
    def _check_suspicious_url_patterns(self, url: str) -> List[str]:
        """Check for suspicious patterns in URL"""
        patterns_found = []
        
        suspicious_patterns = {
            'url_shortener': r'(bit\.ly|tinyurl|goo\.gl|ow\.ly|is\.gd|buff\.ly)',
            'homograph': r'[а-яА-Я]',  # Cyrillic characters
            'excessive_subdomains': r'([^.]+\.){4,}',
            'suspicious_tld': r'\.(tk|ml|ga|cf|click|download|review)\b',
            'misleading_subdomain': rf'{self.config.BRAND_NAME.lower()}[.-]',
            'typosquatting': self._generate_typo_patterns()
        }
        
        for pattern_name, pattern in suspicious_patterns.items():
            if re.search(pattern, url.lower()):
                patterns_found.append(pattern_name)
        
        return patterns_found
    
    def _generate_typo_patterns(self) -> str:
        """Generate regex pattern for common typosquatting variants"""
        brand = self.config.BRAND_NAME.lower()
        variants = []
        
        # Common character substitutions
        for i, char in enumerate(brand):
            # Character omission
            variants.append(brand[:i] + brand[i+1:])
            # Character duplication
            variants.append(brand[:i] + char + brand[i:])
        
        # Create regex pattern
        return '|'.join(re.escape(v) for v in variants[:10])
    
    async def _get_whois_info(self, domain: str) -> Optional[Dict]:
        """Get WHOIS information for domain"""
        try:
            w = whois.whois(domain)
            return {
                'registrar': w.registrar,
                'creation_date': w.creation_date,
                'expiration_date': w.expiration_date,
                'name_servers': w.name_servers,
                'status': w.status,
                'emails': w.emails,
                'org': w.org
            }
        except Exception as e:
            logger.debug(f"WHOIS lookup failed for {domain}: {e}")
            return None
    
    async def _get_dns_records(self, domain: str) -> Optional[Dict]:
        """Get DNS records for domain"""
        records = {}
        
        try:
            # A records
            try:
                a_records = self.dns_resolver.resolve(domain, 'A')
                records['A'] = [str(r) for r in a_records]
            except:
                pass
            
            # MX records
            try:
                mx_records = self.dns_resolver.resolve(domain, 'MX')
                records['MX'] = [str(r.exchange) for r in mx_records]
            except:
                pass
            
            # TXT records
            try:
                txt_records = self.dns_resolver.resolve(domain, 'TXT')
                records['TXT'] = [str(r) for r in txt_records]
            except:
                pass
            
        except Exception as e:
            logger.debug(f"DNS lookup failed for {domain}: {e}")
        
        return records if records else None
    
    async def _check_ssl_certificate(self, url: str) -> Optional[Dict]:
        """Check SSL certificate information"""
        try:
            response = requests.get(url, timeout=5, verify=True)
            return {
                'valid': True,
                'status_code': response.status_code
            }
        except requests.exceptions.SSLError:
            return {'valid': False, 'error': 'SSL_ERROR'}
        except Exception as e:
            logger.debug(f"SSL check failed for {url}: {e}")
            return None

    async def extract_content_features(self, content: str) -> Dict:
        """Extract features from page content"""
        features = {
            'content_length': len(content),
            'num_forms': 0,
            'num_inputs': 0,
            'has_password_field': False,
            'external_links': [],
            'form_actions': [],
            'javascript_refs': 0,
            'iframe_count': 0
        }
        
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, 'html.parser')
            
            # Count forms and inputs
            forms = soup.find_all('form')
            features['num_forms'] = len(forms)
            
            for form in forms:
                action = form.get('action', '')
                if action:
                    features['form_actions'].append(action)
                
                inputs = form.find_all('input')
                features['num_inputs'] += len(inputs)
                
                # Check for password fields
                for input_field in inputs:
                    if input_field.get('type') == 'password':
                        features['has_password_field'] = True
            
            # Extract external links
            for link in soup.find_all('a', href=True):
                href = link['href']
                if href.startswith('http'):
                    parsed = urllib.parse.urlparse(href)
                    if parsed.netloc not in self.config.BRAND_DOMAINS:
                        features['external_links'].append(href)
            
            # Count JavaScript references
            features['javascript_refs'] = len(soup.find_all('script'))
            
            # Count iframes
            features['iframe_count'] = len(soup.find_all('iframe'))
            
        except Exception as e:
            logger.error(f"Content feature extraction error: {e}")
        
        return features