#!/usr/bin/env python3
"""
Simplified Greenhouse Form Extractor - Clean, Essential Data Only
Extracts only the essential information: ID, Label, Type, Required, Options
"""

import asyncio
import json
import sys
import logging
import re
from datetime import datetime
from typing import List, Dict, Optional, Any
from playwright.async_api import async_playwright, Page, ElementHandle
from undetected_playwright import stealth_async

# Configure logging
import tempfile
import os
from pathlib import Path

# Create a proper log directory
try:
    # Try to use user's home directory first
    log_dir = Path.home() / '.job-automator'
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / 'form_extractor.log'
except (PermissionError, OSError):
    # Fallback to temporary directory
    log_file = Path(tempfile.gettempdir()) / 'job_automator_form_extractor.log'

logging.basicConfig(
    level=logging.DEBUG,  # was INFO; make very verbose
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Reduce noise from lower-level libraries while keeping our logs verbose
for noisy in ['playwright._impl', 'asyncio', 'urllib3']:
    try:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    except Exception:
        pass

class SimpleFormExtractor:
    def __init__(self, config=None):
        self.logger = logger
        self.iframe_context = None  # Store iframe information for JSON output
        
        # Configurable wait strategies and timeouts
        self.config = config or {}
        self.debug = bool(self.config.get('debug', True))
        self.debug_artifacts = bool(self.config.get('debug_artifacts', True))
        self.session_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        self.timeouts = {
            'navigation': self.config.get('navigation_timeout', 20000),  # slightly higher for non-GH domains
            'element_wait': self.config.get('element_wait_timeout', 7000),
            'interaction': self.config.get('interaction_timeout', 3000),
            'loading': self.config.get('loading_timeout', 10000),
            'short_wait': self.config.get('short_wait_timeout', 2000),
            'network_idle': self.config.get('network_idle_timeout', 10000),
            'dynamic_loading_wait': self.config.get('dynamic_loading_wait', 1500),
            'scroll_detection_wait': self.config.get('scroll_detection_wait', 500)
        }
        
        # Wait strategy constants
        self.WAIT_STRATEGIES = {
            'minimal': 75,
            'short': 200,
            'medium': 350,
            'long': 700,
            'extended': 1400
        }

    # Debug helpers
    def _get_debug_dir(self) -> Path:
        base = Path(log_file).parent / 'artifacts' / self.session_ts
        try:
            base.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return base

    async def _save_debug_artifact(self, page_or_frame, label: str):
        if not self.debug_artifacts:
            return
        try:
            base = self._get_debug_dir()
            safe = re.sub(r'[^a-zA-Z0-9_.-]+', '_', label)[:80]
            # Screenshots for Pages only; Frames can use page()
            page_obj = getattr(page_or_frame, 'page', None)
            page_obj = page_obj() if callable(page_obj) else page_or_frame
            # Screenshot
            png = base / f'{safe}.png'
            try:
                await page_obj.screenshot(path=str(png), full_page=True)
                self.logger.debug(f"Saved screenshot: {png}")
            except Exception as e:
                self.logger.debug(f"Screenshot failed: {e}")
            # HTML dump
            try:
                html = await page_or_frame.content()
                html_path = base / f'{safe}.html'
                with open(html_path, 'w', encoding='utf-8') as f:
                    f.write(html)
                self.logger.debug(f"Saved HTML dump: {html_path}")
            except Exception as e:
                self.logger.debug(f"HTML dump failed: {e}")
        except Exception as e:
            self.logger.debug(f"Error saving debug artifacts: {e}")

    def _attach_debug_listeners(self, page: Page):
        try:
            self.logger.debug("Attaching debug listeners to page")
            page.on('console', lambda msg: self.logger.debug(f"[console:{msg.type}] {msg.text}"))
            page.on('pageerror', lambda exc: self.logger.error(f"[pageerror] {exc}"))
            page.on('requestfailed', lambda req: self.logger.warning(f"[requestfailed] {req.url} - {req.failure if req.failure else 'unknown'}"))
            page.on('frameattached', lambda frame: self.logger.debug(f"[frameattached] url={frame.url}"))
            page.on('framedetached', lambda frame: self.logger.debug(f"[framedetached] url={frame.url}"))
            page.on('framenavigated', lambda frame: self.logger.debug(f"[framenavigated] url={frame.url}"))
        except Exception as e:
            self.logger.debug(f"Failed to attach debug listeners: {e}")

    async def _log_iframes(self, page: Page, note: str = ""):
        try:
            frames = page.frames
            self.logger.debug(f"Iframe audit{(' - ' + note) if note else ''}: total={len(frames)}")
            for idx, f in enumerate(frames):
                try:
                    url = f.url
                    name = f.name or ''
                    # Try locate the element for size when possible
                    # This may fail for main frame
                    selector = 'iframe'
                    elements = await page.query_selector_all(selector)
                    # Best-effort: match by URL if available
                    matched = None
                    for el in elements:
                        try:
                            src = await el.get_attribute('src')
                            if src and src in url:
                                matched = el
                                break
                        except Exception:
                            continue
                    size = None
                    if matched:
                        try:
                            size = await matched.bounding_box()
                        except Exception:
                            pass
                    self.logger.debug(f"  - frame[{idx}] name='{name}' url='{url}' size={size}")
                except Exception as e:
                    self.logger.debug(f"  - frame[{idx}] error logging: {e}")
        except Exception as e:
            self.logger.debug(f"Iframe audit failed: {e}")

    async def _smart_wait(self, page: Page, strategy: str = 'medium', max_wait: int = None) -> None:
        """Smart wait that adapts based on page conditions."""
        max_wait = max_wait or self.timeouts['short_wait']
        base_wait = self.WAIT_STRATEGIES.get(strategy, 500)
        
        try:
            # Check if page is still loading
            ready_state = await page.evaluate('document.readyState')
            if ready_state != 'complete':
                await page.wait_for_load_state('domcontentloaded', timeout=max_wait)
            
            # Adaptive wait based on page activity
            start_time = asyncio.get_event_loop().time()
            while (asyncio.get_event_loop().time() - start_time) * 1000 < base_wait:
                # Check for active loading indicators
                has_loading = await page.evaluate('''
                    () => {
                        const loadingSelectors = [
                            '.loading', '.spinner', '.loader', 
                            '[data-loading="true"]', '.skeleton', 
                            '[aria-busy="true"]'
                        ];
                        return loadingSelectors.some(sel => 
                            document.querySelector(sel) && 
                            getComputedStyle(document.querySelector(sel)).display !== 'none'
                        );
                    }
                ''')
                
                if not has_loading:
                    break
                    
                await asyncio.sleep(0.1)  # Check every 100ms
                
        except Exception as e:
            self.logger.debug(f"Smart wait fallback: {e}")
            await asyncio.sleep(base_wait / 1000)

    async def _enhanced_page_wait(self, page: Page) -> None:
        """Enhanced page waiting strategy combining multiple techniques."""
        try:
            # Step 1: Wait for basic DOM
            await page.wait_for_load_state('domcontentloaded', timeout=self.timeouts['loading'])
            
            # Step 2: Wait for content to stabilize
            await self._wait_for_content_stable(page)
            
            # Step 3: Wait for network to calm down
            await self._wait_for_network_calm(page)
            
            # Step 4: Check for and wait for loading indicators to disappear
            await self._wait_for_loading_complete(page)
            
        except Exception as e:
            self.logger.debug(f"Enhanced page wait completed with warnings: {e}")

    async def _wait_for_content_stable(self, page: Page, timeout: int = None) -> None:
        """Wait for page content to stabilize (no more DOM changes)."""
        timeout = timeout or self.timeouts['loading']
        
        try:
            await page.wait_for_function(
                '''() => {
                    if (typeof window.contentStableTimer !== 'undefined') {
                        clearTimeout(window.contentStableTimer);
                    }
                    
                    return new Promise((resolve) => {
                        let lastMutationTime = Date.now();
                        const observer = new MutationObserver(() => {
                            lastMutationTime = Date.now();
                        });
                        
                        observer.observe(document.body, {
                            childList: true,
                            subtree: true,
                            attributes: true
                        });
                        
                        const checkStability = () => {
                            if (Date.now() - lastMutationTime > 500) {
                                observer.disconnect();
                                resolve(true);
                            } else {
                                window.contentStableTimer = setTimeout(checkStability, 100);
                            }
                        };
                        
                        window.contentStableTimer = setTimeout(checkStability, 100);
                    });
                }''',
                timeout=timeout
            )
        except Exception as e:
            self.logger.debug(f"Content stability wait failed: {e}")

    async def _wait_for_network_calm(self, page: Page, timeout: int = None, idle_time: int = 500) -> None:
        """Wait for network activity to calm down."""
        timeout = timeout or self.timeouts['network_idle']
        
        try:
            # Try networkidle first
            await page.wait_for_load_state('networkidle', timeout=timeout)
        except Exception:
            self.logger.debug(f"Network calm monitoring timeout")

    async def _wait_for_loading_complete(self, page: Page, timeout: int = None) -> None:
        """Wait for loading indicators to disappear."""
        timeout = timeout or self.timeouts['loading']
        
        loading_selectors = [
            '.loading', '.spinner', '.loader', 
            '[data-loading="true"]', '.skeleton', 
            '.preloader', '.progress-bar',
            '[aria-busy="true"]', '.loading-overlay',
            '.securiti-overlay-loading'
        ]
        
        try:
            # Wait for all loading indicators to disappear
            for selector in loading_selectors:
                try:
                    await page.wait_for_selector(selector, state='detached', timeout=1500)
                    self.logger.debug(f"Loading indicator {selector} disappeared")
                except Exception:
                    pass  # Not found or didn't disappear - that's OK
                    
        except Exception as e:
            self.logger.debug(f"Loading completion wait failed: {e}")

    async def extract_form_data(self, url: str) -> Dict[str, Any]:
        """Extract essential form data with clean, minimal output."""
        async with async_playwright() as p:
            # Launch browser with enhanced stealth mode for undetectability
            browser = await p.chromium.launch(
                headless=False,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--disable-dev-shm-usage',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                    '--disable-background-timer-throttling',
                    '--disable-backgrounding-occluded-windows',
                    '--disable-renderer-backgrounding'
                ]
            )
            
            # Set a viewport large enough to see most of the form
            context = await browser.new_context(
                viewport={'width': 1366, 'height': 960},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                extra_http_headers={
                    'Accept-Language': 'en-US,en;q=0.9'
                }
            )
            page = await context.new_page()
            
            # Apply stealth mode to make the browser undetectable
            await stealth_async(page)
            # Attach debug listeners
            self._attach_debug_listeners(page)
            
            try:
                # Enhanced navigation and loading strategy
                self.logger.info(f"Navigating to: {url}")
                await self._save_debug_artifact(page, 'before_navigation')
                
                # Navigate with better error handling and retry logic
                max_retries = 3
                for attempt in range(max_retries):
                    try:
                        response = await page.goto(url, timeout=self.timeouts['navigation'], wait_until='domcontentloaded')
                        if response:
                            status = response.status
                            self.logger.info(f"Navigation response status: {status}")
                            if status >= 400:
                                self.logger.warning(f"HTTP {status} response, but proceeding")
                        break
                    except Exception as nav_error:
                        self.logger.warning(f"Navigation attempt {attempt + 1} failed: {nav_error}")
                        if attempt < max_retries - 1:
                            await self._smart_wait(page, 'medium')
                            continue
                        else:
                            self.logger.warning("All navigation attempts failed, but proceeding")
                
                await self._log_iframes(page, 'post-navigation')
                # Skip debug artifact for speed
                
                # Simplified fast page waiting strategy
                await page.wait_for_load_state('domcontentloaded', timeout=8000)  # Reduced timeout
                # Skip enhanced waiting for speed
                
                # Check if page is still alive
                try:
                    await page.evaluate('document.readyState')
                except Exception:
                    raise Exception("Page closed unexpectedly during navigation")
                
                # Quick check for basic loading indicators only
                try:
                    # Just check most common loading indicators with short timeout
                    loading_selectors = ['.loading', '.spinner', '.loader']
                    
                    for selector in loading_selectors:
                        try:
                            await page.wait_for_selector(selector, state='detached', timeout=800)  # Further reduced
                            self.logger.debug(f"Loading indicator {selector} disappeared")
                        except Exception:
                            pass  # Not found or didn't disappear
                    
                    # Quick check for basic content elements
                    try:
                        await page.wait_for_selector('input, textarea, select, button', timeout=1500)  # Check for any form element
                        self.logger.debug(f"Form content found")
                    except Exception:
                        pass  # No form elements found quickly
                    
                    # Skip networkidle wait for speed - forms don't need it
                    self.logger.debug("Skipping networkidle wait for speed")
                        
                except Exception as wait_error:
                    self.logger.debug(f"Enhanced wait strategy warning: {wait_error}")
                    # Quick fallback wait
                    await page.wait_for_timeout(2000)  # Reduced from 5000
                
                # Check if page is still alive after waiting
                try:
                    page_title = await page.title()
                    self.logger.info(f"Page title: {page_title}")
                except Exception:
                    raise Exception("Page closed unexpectedly during wait")
                
                # Enhanced cookie banner and overlay handling
                await self._dismiss_overlays(page)
                
                # Wait for any UI animations to complete using smart wait
                await self._smart_wait(page, 'medium')
                
                # Check for iframe with Greenhouse form or find the form section
                form_page = await self._find_form_page(page)
                
                # Get the specific form container element if found
                form_container = self.iframe_context.get("form_container")
                
                # Extract all form fields
                fields = []
                
                # Try one more time to find the form container if not already found
                if not form_container and form_page == page:  # Only for main page, not iframes
                    try:
                        # Look for the most likely form container
                        form_containers = await form_page.query_selector_all('form, [class*="application-form"], [id="apply-form"], [class*="job-form"], [class*="apply-form"], .application-form, [id="apply"], [id="applynow"]')
                        
                        # Find the container with the most input elements
                        best_container = None
                        max_inputs = 0
                        
                        for container in form_containers:
                            inputs = await container.query_selector_all('input, textarea, select, [role="combobox"]')
                            if len(inputs) > max_inputs:
                                max_inputs = len(inputs)
                                best_container = container
                        
                        if best_container and max_inputs >= 3:
                            self.logger.info(f"Found form container with {max_inputs} input elements")
                            form_container = best_container
                            await form_container.scroll_into_view_if_needed()
                            self.iframe_context["form_container"] = form_container
                    except Exception as e:
                        self.logger.debug(f"Error finding form container: {e}")
                
                # Use the context for extraction - form container if available, otherwise the whole page
                extraction_context = form_container if form_container else form_page
                self.logger.info(f"Using {'form container' if form_container else 'full page'} for field extraction")
                
                # Phone fields (composite country+phone patterns) - extract these first
                phone_fields = await self._extract_phone_fields(form_page, extraction_context)
                fields.extend(phone_fields)
                self.logger.info(f"Extracted {len(phone_fields)} phone fields")
                
                # Text inputs - now extracted only from the form container if available
                text_fields = await self._extract_text_fields(form_page, extraction_context, phone_fields)
                fields.extend(text_fields)
                self.logger.info(f"Extracted {len(text_fields)} text fields")
                
                # Dropdowns
                dropdown_fields = await self._extract_dropdown_fields(form_page, extraction_context, phone_fields)
                fields.extend(dropdown_fields)
                self.logger.info(f"Extracted {len(dropdown_fields)} dropdown fields")
                
                # File inputs
                file_fields = await self._extract_file_fields(form_page, extraction_context)
                fields.extend(file_fields)
                self.logger.info(f"Extracted {len(file_fields)} file fields")
                
                # Textareas
                textarea_fields = await self._extract_textarea_fields(form_page, extraction_context)
                fields.extend(textarea_fields)
                self.logger.info(f"Extracted {len(textarea_fields)} textarea fields")
                
                # Checkbox groups (for demographics sections like Instacart)
                checkbox_fields = await self._extract_checkbox_groups(form_page, extraction_context)
                fields.extend(checkbox_fields)
                self.logger.info(f"Extracted {len(checkbox_fields)} checkbox group fields")
                
                # If we didn't find any fields, try a few other strategies
                if len(fields) == 0:
                    self.logger.warning("No fields found with primary strategy, trying alternative approaches")
                    
                    # Strategy 1: Try to find any visible inputs on the page
                    all_inputs = await form_page.query_selector_all('input, textarea, select, [role="combobox"]')
                    visible_inputs = []
                    
                    for input_elem in all_inputs:
                        try:
                            box = await input_elem.bounding_box()
                            if box and box['width'] > 0 and box['height'] > 0:
                                visible_inputs.append(input_elem)
                        except:
                            pass
                    
                    if visible_inputs:
                        self.logger.info(f"Found {len(visible_inputs)} visible input elements")
                        
                        # Try to extract information from these inputs
                        for input_elem in visible_inputs:
                            try:
                                input_type = await input_elem.get_attribute('type')
                                id_attr = await input_elem.get_attribute('id')
                                name_attr = await input_elem.get_attribute('name')
                                
                                if not input_type:
                                    tag_name = await input_elem.evaluate('el => el.tagName.toLowerCase()')
                                    if tag_name == 'textarea':
                                        input_type = 'textarea'
                                    elif tag_name == 'select':
                                        input_type = 'select'
                                
                                # Try to get a label
                                label = await self._get_real_label(form_page, input_elem, id_attr)
                                if not label and name_attr:
                                    # Use name as fallback
                                    label = name_attr.replace('_', ' ').replace('-', ' ').capitalize()
                                
                                # Determine if required
                                required = await self._is_required(form_page, input_elem, id_attr)
                                
                                if label and (input_type or id_attr or name_attr):
                                    field_type = 'text'
                                    if input_type == 'file':
                                        field_type = 'file'
                                    elif input_type == 'textarea':
                                        field_type = 'textarea'
                                    elif input_type in ['select', 'select-one']:
                                        field_type = 'dropdown'
                                    
                                    fields.append({
                                        'id': id_attr or '',
                                        'name': name_attr or '',
                                        'label': label,
                                        'type': field_type,
                                        'required': required
                                    })
                            except Exception as e:
                                self.logger.debug(f"Error processing input: {e}")
                
                # Clean and deduplicate
                clean_fields = self._clean_and_dedupe_fields(fields)
                
                # Generate user input template
                user_template = self._generate_user_input_template(clean_fields)
                
                # Extract job info (try both main page and form page)
                job_title = await self._extract_job_title(page) or await self._extract_job_title(form_page)
                company = await self._extract_company(page) or await self._extract_company(form_page)
                
                # Create a copy of iframe_context without the form_container element
                # as ElementHandle objects cannot be serialized to JSON
                form_context = {k: v for k, v in self.iframe_context.items() if k != "form_container"}
                
                return {
                    'url': url,
                    'timestamp': datetime.now().isoformat(),
                    'job_title': job_title,
                    'company': company,
                    'form_context': form_context,
                    'total_fields': len(clean_fields),
                    'required_fields': len([f for f in clean_fields if f.get('required', False)]),
                    'fields': clean_fields,
                    'user_input_template': user_template
                }
                
            except Exception as e:
                self.logger.error(f"Error during form extraction: {e}")
                # Try to get more context about the error
                try:
                    page_url = await page.url()
                    self.logger.info(f"Error occurred on page: {page_url}")
                except:
                    pass
                raise
            finally:
                try:
                    await browser.close()
                except Exception as close_error:
                    self.logger.debug(f"Error closing browser: {close_error}")

    def _extract_domain_from_src(self, src: str) -> str:
        """Extract domain from iframe src URL for selector creation."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(src)
            domain = parsed.netloc
            # Return a shortened version for more reliable selector matching
            if domain:
                parts = domain.split('.')
                if len(parts) >= 2:
                    return f"{parts[-2]}.{parts[-1]}"  # Return domain.tld
                return domain
            return "unknown"
        except Exception:
            return "unknown"

    async def _dismiss_overlays(self, page: Page):
        """Enhanced overlay dismissal for cookie banners, modals, and UI interference."""
        try:
            # Wait for page to stabilize
            await page.wait_for_load_state('domcontentloaded', timeout=5000)  # 10000 -> 5000
            self.logger.debug("Attempting to dismiss overlays/cookie banners")
            
            # Cookie banner selectors (expanded from Instacart analysis)
            cookie_selectors = [
                'button:has-text("Accept")', 
                'button:has-text("Accept All")', 
                'button:has-text("Accept Cookies")',
                'button:has-text("Dismiss")',
                'button:has-text("OK")',
                'button:has-text("Agree")',
                'button:has-text("Continue")',
                '[id*="cookie"] button',
                '[class*="cookie"] button',
                '[id*="consent"] button',
                '[class*="consent"] button',
                '[aria-label*="cookie"] button',
                '[aria-label*="consent"] button',
                # Securiti cookie banner (from Instacart)
                '.cc-compliance button',
                '.cookie-banner button',
                '[role="dialog"] button'
            ]
            
            # Try to dismiss cookie banners
            for selector in cookie_selectors:
                try:
                    buttons = await page.query_selector_all(selector)
                    for button in buttons:
                        try:
                            # Check if button is visible
                            box = await button.bounding_box()
                            if box and box['width'] > 0 and box['height'] > 0:
                                button_text = await button.text_content() or ""
                                # Skip reject/decline buttons, prefer accept/dismiss
                                if any(word in button_text.lower() for word in ['reject', 'decline', 'deny']):
                                    continue
                                
                                self.logger.info(f"Dismissing overlay: {button_text.strip()}")
                                await button.click(timeout=1500)  # 3000 -> 1500
                                await self._smart_wait(page, 'medium')
                                return  # Exit after first successful dismissal
                        except Exception:
                            continue
                except Exception:
                    continue
            
            # Clear any select2 drop masks that might interfere
            try:
                await page.evaluate('''
                    document.querySelectorAll('#select2-drop-mask, .select2-drop-mask').forEach(el => {
                        el.style.display = 'none';
                        el.remove();
                    });
                ''')
            except Exception:
                pass
            
            # Close any open modals or dialogs
            try:
                close_selectors = [
                    '[aria-label="close"]',
                    '[aria-label="Close"]',
                    'button[aria-label*="close"]',
                    '.modal-close',
                    '.dialog-close'
                ]
                
                for selector in close_selectors:
                    close_buttons = await page.query_selector_all(selector)
                    for button in close_buttons:
                        try:
                            box = await button.bounding_box()
                            if box and box['width'] > 0 and box['height'] > 0:
                                await button.click(timeout=1000)  # 2000 -> 1000
                                await self._smart_wait(page, 'short')
                                break
                        except Exception:
                            continue
            except Exception:
                pass
                
        except Exception as e:
            self.logger.debug(f"Error dismissing overlays: {e}")

    async def _extract_checkbox_groups(self, page: Page, container=None) -> List[Dict]:
        """Extract checkbox groups (e.g., demographics sections) as dropdown-like fields."""
        fields = []
        
        try:
            context = container or page
            
            # First, try to find all checkboxes/radios and group them intelligently
            all_checkboxes = await context.query_selector_all('input[type="checkbox"], input[type="radio"]')
            self.logger.debug(f"Found {len(all_checkboxes)} total checkboxes/radios")
            
            if not all_checkboxes:
                return fields
            
            # Group checkboxes by their questions using proximity and DOM structure
            question_groups = []
            processed_checkboxes = set()
            
            for checkbox in all_checkboxes:
                if id(checkbox) in processed_checkboxes:
                    continue
                
                try:
                    # Find the label/question for this checkbox
                    checkbox_label = await self._get_checkbox_label(page, checkbox)
                    
                    # Look for similar checkboxes that might belong to the same question
                    related_checkboxes = [checkbox]
                    checkbox_parent = await checkbox.query_selector('..')
                    
                    if checkbox_parent:
                        # Get the grandparent to look for siblings
                        grandparent = await checkbox_parent.query_selector('..')
                        if grandparent:
                            # Find other similar checkboxes in the same area
                            nearby_checkboxes = await grandparent.query_selector_all('input[type="checkbox"], input[type="radio"]')
                            
                            for nearby_checkbox in nearby_checkboxes:
                                if id(nearby_checkbox) in processed_checkboxes or nearby_checkbox == checkbox:
                                    continue
                                
                                # Check if this checkbox has the same name pattern or is in similar DOM structure
                                nearby_name = await nearby_checkbox.get_attribute('name')
                                checkbox_name = await checkbox.get_attribute('name')
                                
                                # Group if they have similar names or values that suggest they're related
                                if nearby_name and checkbox_name:
                                    # Check if they have similar name patterns (e.g., same base name)
                                    if nearby_name.split('[')[0] == checkbox_name.split('[')[0]:
                                        related_checkboxes.append(nearby_checkbox)
                                
                                # Also group by proximity if they're close to each other
                                try:
                                    checkbox_box = await checkbox.bounding_box()
                                    nearby_box = await nearby_checkbox.bounding_box()
                                    if checkbox_box and nearby_box:
                                        distance = abs(checkbox_box['y'] - nearby_box['y'])
                                        if distance < 200:  # Close vertically
                                            related_checkboxes.append(nearby_checkbox)
                                except Exception:
                                    pass
                    
                    # If we have 2-15 related checkboxes, this is likely a question group
                    if 2 <= len(related_checkboxes) <= 15:
                        question_groups.append(related_checkboxes)
                        for cb in related_checkboxes:
                            processed_checkboxes.add(id(cb))
                    else:
                        processed_checkboxes.add(id(checkbox))
                        
                except Exception as e:
                    self.logger.debug(f"Error processing checkbox for grouping: {e}")
                    processed_checkboxes.add(id(checkbox))
                    continue
            
            self.logger.info(f"Found {len(question_groups)} potential checkbox groups")
            
            # Process each question group
            for i, checkbox_group in enumerate(question_groups):
                try:
                    # Try to find the question/label for this group
                    group_label = None
                    
                    # Method 1: Look for common parent with question text
                    first_checkbox = checkbox_group[0]
                    parent = await first_checkbox.query_selector('..')
                    for level in range(3):  # Check up to 3 parent levels
                        if parent:
                            try:
                                parent_text = await parent.text_content()
                                if parent_text:
                                    lines = [line.strip() for line in parent_text.split('\n') if line.strip()]
                                    for line in lines[:10]:  # Check first 10 lines
                                        if self._is_valid_demographics_question(line) and not self._is_option_text(line):
                                            group_label = self._clean_label(line)
                                            break
                                    if group_label:
                                        break
                                parent = await parent.query_selector('..')
                            except Exception:
                                break
                    
                    # Method 2: Try to infer from checkbox values/names if no clear question found
                    if not group_label:
                        # Look at the checkbox options to infer the question type
                        option_texts = []
                        for cb in checkbox_group[:5]:  # Sample first few
                            cb_label = await self._get_checkbox_label(page, cb)
                            if cb_label:
                                option_texts.append(cb_label.lower())
                        
                        # Infer question based on options
                        option_text = ' '.join(option_texts)
                        
                        # Skip if this looks like upload method options (not demographics)
                        if any(phrase in option_text for phrase in ['upload pdf', 'paste', 'upload file', 'choose file', 'browse']):
                            self.logger.debug(f"Skipping checkbox group {i+1}: appears to be upload method options, not demographics")
                            continue
                        
                        # Skip if this looks like other non-demographics options
                        if any(phrase in option_text for phrase in ['save', 'submit', 'cancel', 'next', 'previous', 'continue']):
                            self.logger.debug(f"Skipping checkbox group {i+1}: appears to be form control options, not demographics")
                            continue
                        
                        # Only proceed with actual demographics-related options
                        if any(word in option_text for word in ['woman', 'man', 'female', 'male', 'non-binary']):
                            group_label = "What is your gender or gender identity?"
                        elif any(word in option_text for word in ['yes', 'no']) and 'lgbtq' in option_text:
                            group_label = "Do you identify as a member of the 2SLGBTQIA+ community?"
                        elif any(word in option_text for word in ['white', 'black', 'asian', 'hispanic', 'indigenous']):
                            group_label = "Please select your race/ethnicity"
                        elif any(word in option_text for word in ['disability', 'disabled']):
                            group_label = "Do you have a disability?"
                        elif any(word in option_text for word in ['veteran', 'military', 'armed forces']):
                            group_label = "Are you a veteran or military member?"
                        else:
                            # If we can't identify it as a demographics question, skip it
                            self.logger.debug(f"Skipping checkbox group {i+1}: cannot identify as demographics question")
                            continue
                    
                    if not group_label:
                        self.logger.debug(f"Skipping checkbox group {i+1}: no valid label found")
                        continue
                    
                    # Extract options from this group
                    options = []
                    for checkbox in checkbox_group:
                        try:
                            checkbox_label = await self._get_checkbox_label(page, checkbox)
                            checkbox_value = await checkbox.get_attribute('value') or checkbox_label
                            
                            if checkbox_label:
                                clean_value = checkbox_value.lower().replace(' ', '_').replace('/', '_').replace('(', '').replace(')', '').replace(',', '')
                                options.append({
                                    'text': checkbox_label,
                                    'value': clean_value
                                })
                        except Exception:
                            continue
                    
                    # Only proceed if we have reasonable number of options
                    if 2 <= len(options) <= 15:
                        # Check if required (assume demographics are usually required)
                        required = True
                        
                        # Generate field ID from the label
                        field_id = group_label.lower().replace(' ', '_').replace('?', '').replace('/', '_').replace(',', '').replace('(', '').replace(')', '')
                        
                        # Ensure unique field ID
                        original_field_id = field_id
                        counter = 1
                        while any(f['id'] == field_id for f in fields):
                            field_id = f"{original_field_id}_{counter}"
                            counter += 1
                        
                        field = {
                            'id': field_id,
                            'name': '',
                            'label': group_label,
                            'type': 'dropdown',  # Treat as dropdown for consistency
                            'required': required,
                            'supports_custom_input': True,
                            'options': options,
                            'options_note': 'Select from the available options.',
                            'original_type': 'checkbox_group'  # Track original type
                        }
                        
                        fields.append(field)
                        self.logger.debug(f"Added checkbox group {i+1}: '{group_label}' with {len(options)} options")
                    else:
                        self.logger.debug(f"Skipping checkbox group {i+1}: invalid option count ({len(options)})")
                        
                except Exception as e:
                    self.logger.debug(f"Error processing checkbox group {i+1}: {e}")
                    continue
        
        except Exception as e:
            self.logger.debug(f"Error extracting checkbox groups: {e}")
        
        # Deduplicate and merge similar questions
        fields = self._deduplicate_checkbox_groups(fields)
        
        return fields

    def _deduplicate_checkbox_groups(self, fields: List[Dict]) -> List[Dict]:
        """Deduplicate and merge similar checkbox group fields with smart grouping."""
        if not fields:
            return fields
        
        checkbox_fields = [f for f in fields if f.get('original_type') == 'checkbox_group']
        other_fields = [f for f in fields if f.get('original_type') != 'checkbox_group']
        
        if not checkbox_fields:
            return fields
        
        # Group fields by semantic similarity and merge options
        grouped_fields = []
        processed_indices = set()
        
        for i, field in enumerate(checkbox_fields):
            if i in processed_indices:
                continue
            
            base_field = field.copy()
            base_options = set(opt['text'] for opt in base_field['options'])
            merged_options = base_field['options'].copy()
            
            # Look for fields that should be merged with this one
            for j, other_field in enumerate(checkbox_fields):
                if i == j or j in processed_indices:
                    continue
                
                should_merge = False
                
                # Merge if exact same label
                if other_field['label'] == base_field['label']:
                    should_merge = True
                
                # Merge if options overlap significantly (race/ethnicity case or gender case)
                other_options = set(opt['text'] for opt in other_field['options'])
                overlap = len(base_options.intersection(other_options))
                if overlap > 0 and (overlap / len(base_options) > 0.3 or overlap / len(other_options) > 0.3):
                    # Check if they're both race/ethnicity related
                    race_keywords = ['white', 'black', 'asian', 'hispanic', 'caucasian', 'african', 'indigenous', 'race', 'ethnicity']
                    base_has_race = any(keyword in ' '.join(base_options).lower() for keyword in race_keywords)
                    other_has_race = any(keyword in ' '.join(other_options).lower() for keyword in race_keywords)
                    
                    # Check if they're both gender related
                    gender_keywords = ['woman', 'man', 'male', 'female', 'gender', 'non-binary', 'transgender']
                    base_has_gender = any(keyword in ' '.join(base_options).lower() for keyword in gender_keywords)
                    other_has_gender = any(keyword in ' '.join(other_options).lower() for keyword in gender_keywords)
                    
                    if (base_has_race and other_has_race) or (base_has_gender and other_has_gender):
                        should_merge = True
                        # Use a better label for race/ethnicity
                        if base_has_race and any(keyword in base_field['label'].lower() for keyword in race_keywords):
                            pass  # Keep current label
                        elif base_has_race:
                            base_field['label'] = "What is your race or ethnicity?"
                        # Use a better label for gender
                        elif base_has_gender and any(keyword in base_field['label'].lower() for keyword in gender_keywords):
                            pass  # Keep current label
                        elif base_has_gender:
                            base_field['label'] = "What is your gender or gender identity?"
                
                # Merge if labels are semantically similar
                if not should_merge:
                    base_label_words = set(base_field['label'].lower().split())
                    other_label_words = set(other_field['label'].lower().split())
                    word_overlap = len(base_label_words.intersection(other_label_words))
                    if word_overlap >= 2 and (word_overlap / len(base_label_words) > 0.5 or word_overlap / len(other_label_words) > 0.5):
                        should_merge = True
                
                if should_merge:
                    # Merge options, avoiding duplicates
                    for option in other_field['options']:
                        if option['text'] not in base_options:
                            merged_options.append(option)
                            base_options.add(option['text'])
                    processed_indices.add(j)
            
            # Remove duplicate options within the same field
            unique_options = []
            seen_texts = set()
            for option in merged_options:
                if option['text'] not in seen_texts:
                    unique_options.append(option)
                    seen_texts.add(option['text'])
            
            base_field['options'] = unique_options
            grouped_fields.append(base_field)
            processed_indices.add(i)
        
        # Combine with other field types
        result = other_fields + grouped_fields
        
        self.logger.info(f"Deduplicated checkbox groups: {len(checkbox_fields)} -> {len(grouped_fields)}")
        return result

    async def _get_checkbox_group_label(self, page: Page, group: ElementHandle) -> Optional[str]:
        """Get the label/question for a checkbox group with improved precision."""
        try:
            # Try legend (for fieldsets)
            legend = await group.query_selector('legend')
            if legend:
                text = await legend.text_content()
                if text and text.strip():
                    clean_text = self._clean_label(text.strip())
                    if self._is_valid_demographics_question(clean_text):
                        return clean_text
            
            # Try aria-label
            aria_label = await group.get_attribute('aria-label')
            if aria_label and aria_label.strip():
                clean_text = self._clean_label(aria_label.strip())
                if self._is_valid_demographics_question(clean_text):
                    return clean_text
            
            # Look for heading or label elements within the group that contain question text
            label_selectors = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'label', '[role="heading"]', 'div', 'span', 'p']
            for selector in label_selectors:
                label_elems = await group.query_selector_all(selector)
                for label_elem in label_elems:
                    try:
                        text = await label_elem.text_content()
                        if text and text.strip():
                            clean_text = self._clean_label(text.strip())
                            # Check if this looks like a demographics question
                            if self._is_valid_demographics_question(clean_text):
                                # Make sure it's not just an option label
                                if not self._is_option_text(clean_text):
                                    return clean_text
                    except Exception:
                        continue
            
            # Look for the first text content that appears to be a question
            try:
                full_text = await group.text_content()
                if full_text:
                    lines = [line.strip() for line in full_text.split('\n') if line.strip()]
                    for line in lines[:5]:  # Check first few lines
                        if self._is_valid_demographics_question(line) and not self._is_option_text(line):
                            return self._clean_label(line)
            except Exception:
                pass
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error getting checkbox group label: {e}")
            return None
    
    def _is_valid_demographics_question(self, text: str) -> bool:
        """Check if text looks like a valid demographics question."""
        if not text or len(text) < 5 or len(text) > 300:
            return False
        
        text_lower = text.lower()
        
        # Exclude upload/file-related text
        upload_keywords = ['upload', 'file', 'pdf', 'paste', 'browse', 'choose file', 'attach', 'document']
        if any(keyword in text_lower for keyword in upload_keywords):
            return False
        
        # Exclude form control text
        control_keywords = ['submit', 'save', 'cancel', 'next', 'previous', 'continue', 'back', 'finish']
        if any(keyword in text_lower for keyword in control_keywords):
            return False
        
        # Must contain demographics-related keywords
        demographics_keywords = [
            'gender', 'race', 'ethnicity', 'disability', 'veteran', 'military',
            'lgbtq', '2slgbtq', 'heritage', 'identity', 'colour', 'color',
            'armed forces', 'indigenous', 'caucasian', 'hispanic', 'asian',
            'african', 'pacific islander', 'first nations', 'métis', 'inuit',
            'woman', 'man', 'female', 'male', 'non-binary', 'self-identify',
            'sexual orientation', 'transgender', 'diverse', 'minority'
        ]
        
        has_demographics_keyword = any(keyword in text_lower for keyword in demographics_keywords)
        
        # Check for question patterns
        has_question_mark = '?' in text
        has_question_keywords = any(keyword in text_lower for keyword in [
            'what is your', 'do you', 'are you', 'which of', 'please select', 
            'identify as', 'consider yourself', 'describe yourself'
        ])
        
        # Must have demographics keywords AND look like a question
        if has_demographics_keyword and (has_question_mark or has_question_keywords):
            return True
        
        # More lenient for known demographics patterns
        if has_demographics_keyword and 10 < len(text) < 150:
            # Additional validation - make sure it's not just an option containing these words
            option_starters = ['i am', 'i have', 'yes,', 'no,', 'i identify as', 'i consider myself']
            if not any(text_lower.startswith(starter) for starter in option_starters):
                return True
        
        return False
    
    def _is_option_text(self, text: str) -> bool:
        """Check if text looks like an option rather than a question."""
        if not text:
            return True
        
        text_lower = text.lower().strip()
        
        # Very long descriptive text is usually an option with explanation
        if len(text) > 150:
            return True
        
        # Common option patterns - be more specific
        specific_options = [
            'yes', 'no', 'woman', 'man', 'male', 'female', 'non-binary', 'transgender',
            'i don\'t wish to answer', 'prefer not to answer', 'decline to answer',
            'not listed', 'other', 'none of the above', 'select one', 'choose one'
        ]
        
        # If it exactly matches common options
        if text_lower in specific_options:
            return True
        
        # Race/ethnicity specific options with descriptive text
        race_ethnicity_patterns = [
            'white', 'caucasian', 'black', 'african', 'asian', 'hispanic', 'latino', 'latina', 'latinx',
            'indigenous', 'native', 'pacific islander', 'hawaiian', 'first nations', 'métis', 'inuit',
            'american indian', 'alaska native', 'caribbean', 'west indian'
        ]
        
        # If it starts with a race/ethnicity identifier and contains descriptive text
        if any(text_lower.startswith(pattern) for pattern in race_ethnicity_patterns):
            # If it also contains parenthetical explanations, it's definitely an option
            if '(' in text and ')' in text:
                return True
            # If it's a race/ethnicity term followed by explanation
            if any(word in text_lower for word in ['person', 'having origins', 'descent', 'heritage', 'background']):
                return True
        
        # Disability status options
        disability_patterns = [
            'yes, i have a disability', 'no, i don\'t have a disability', 'i am unsure'
        ]
        if any(pattern in text_lower for pattern in disability_patterns):
            return True
        
        # Veteran status options
        veteran_patterns = [
            'yes - i am a', 'yes - i am the spouse', 'no, i am not'
        ]
        if any(pattern in text_lower for pattern in veteran_patterns):
            return True
        
        # Text that starts with declarative statements are usually options
        declarative_starts = [
            'i am', 'i have', 'i don\'t', 'i do not', 'i identify', 'i consider',
            'yes -', 'no -', 'yes,', 'no,'
        ]
        if any(text_lower.startswith(start) for start in declarative_starts):
            return True
        
        return False

    async def _get_checkbox_label(self, page: Page, checkbox: ElementHandle) -> Optional[str]:
        """Get the label for an individual checkbox."""
        try:
            # Try associated label
            checkbox_id = await checkbox.get_attribute('id')
            if checkbox_id:
                label_elem = await page.query_selector(f'label[for="{checkbox_id}"]')
                if label_elem:
                    text = await label_elem.text_content()
                    if text and text.strip():
                        return text.strip()
            
            # Try parent label
            parent = await checkbox.query_selector('..')
            if parent:
                parent_tag = await parent.evaluate('el => el.tagName.toLowerCase()')
                if parent_tag == 'label':
                    text = await parent.text_content()
                    if text and text.strip():
                        return text.strip()
            
            # Look for nearby text
            checkbox_box = await checkbox.bounding_box()
            if checkbox_box:
                # Look for text elements near the checkbox
                text_elements = await page.query_selector_all('span, div, label')
                for elem in text_elements:
                    try:
                        elem_box = await elem.bounding_box()
                        if not elem_box:
                            continue
                        
                        # Check if element is close to checkbox (within 200px horizontally)
                        horizontal_distance = abs(elem_box['x'] - (checkbox_box['x'] + checkbox_box['width']))
                        vertical_distance = abs(elem_box['y'] - checkbox_box['y'])
                        
                        if horizontal_distance < 200 and vertical_distance < 30:
                            text = await elem.text_content()
                            if text and text.strip() and len(text.strip()) > 3:
                                return text.strip()
                    except Exception:
                        continue
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error getting checkbox label: {e}")
            return None

    async def _is_checkbox_group_required(self, page: Page, group: ElementHandle) -> bool:
        """Check if a checkbox group is required."""
        try:
            # Check for required attribute on any checkbox in the group
            checkboxes = await group.query_selector_all('input[type="checkbox"], input[type="radio"]')
            for checkbox in checkboxes:
                required = await checkbox.get_attribute('required')
                if required is not None:
                    return True
            
            # Check for asterisk in group text
            text = await group.text_content()
            if text and '*' in text:
                return True
            
            # Check for "required" text
            if text and 'required' in text.lower():
                return True
            
            return False
            
        except Exception:
            return False

    async def _find_form_page(self, page: Page) -> Page:
        """Find the actual form page, which might be in an iframe or a specific section."""
        try:
            # Initialize iframe context
            self.iframe_context = {
                "is_iframe": False,
                "iframe_src": None,
                "iframe_selector": None,
                "iframe_index": None,
                "wait_strategy": "networkidle",
                "form_container": None  # Will store the main form container element
            }
            
            await self._log_iframes(page, 'before_find_form_page')
            
            # Check for "Apply" or similar buttons that might need to be clicked first
            apply_selectors = [
                'a[href="#apply"]', 'a[href="#applynow"]', 'a[href^="#app"]',
                'button:has-text("Apply")', 'a:has-text("Apply")',
                'button:has-text("Apply now")', 'a:has-text("Apply now")',
                'button:has-text("Start application")', 'a:has-text("Start application")',
                '[data-qa*="apply"]', '[data-testid*="apply"]', '[id*="apply"]'
            ]
            found_apply = False
            for sel in apply_selectors:
                try:
                    buttons = await page.query_selector_all(sel)
                    for button in buttons:
                        try:
                            box = await button.bounding_box()
                            if not box or box['width'] <= 0 or box['height'] <= 0:
                                continue
                            btn_text = (await button.text_content() or '').strip()
                            self.logger.info(f"Found apply trigger via '{sel}': '{btn_text}'")
                            
                            # Scroll to the button first
                            await button.scroll_into_view_if_needed()
                            # Skip wait for speed
                            
                            # Try popup first (for new tab/window scenarios)
                            try:
                                with page.expect_popup(timeout=2000) as popup_info:  # Further reduced
                                    await button.click(timeout=2000)  # Further reduced
                                new_page = await popup_info.value
                                self._attach_debug_listeners(new_page)
                                await new_page.wait_for_load_state('domcontentloaded', timeout=8000)  # Reduced
                                # Skip artifacts and waits for speed
                                page = new_page
                                self.logger.info(f"✅ Apply button opened new tab: {new_page.url}")
                            except Exception:
                                # No popup, try regular click
                                try:
                                    await button.click(timeout=2000)  # Further reduced
                                    # Minimal wait after click for iframe loading
                                    await page.wait_for_timeout(800)  # Reduced from 1500
                                    # Skip artifacts for speed
                                    self.logger.info(f"✅ Apply button clicked successfully")
                                    await self._log_iframes(page, 'after_apply_click_same_page')
                                    await self._save_debug_artifact(page, 'after_apply_click_same_page')
                                    self.logger.info(f"✅ Apply button clicked successfully")
                                except Exception as e:
                                    self.logger.warning(f"Apply button click failed: {e}")
                                    continue
                            found_apply = True
                            break
                        except Exception as e:
                            self.logger.debug(f"Error clicking apply trigger '{sel}': {e}")
                    if found_apply:
                        break
                except Exception:
                    continue
            
            # PRIORITY 1: Look for iframes that might contain the form - prioritize Greenhouse iframes FIRST
            iframes = await page.query_selector_all('iframe')
            self.logger.info(f"Found {len(iframes)} iframes on page")
            
            # First pass: Look specifically for Greenhouse iframes (highest priority)
            for i, iframe in enumerate(iframes):
                try:
                    src = await iframe.get_attribute('src')
                    self.logger.info(f"Iframe {i+1} src: {src}")
                    
                    # Check if it's a Greenhouse iframe first
                    if src and 'greenhouse' in src.lower():
                        self.logger.info(f"FOUND GREENHOUSE IFRAME {i+1}: {src}")
                        try:
                            iframe_box = await iframe.bounding_box()
                            self.logger.debug(f"Greenhouse iframe {i+1} size: {iframe_box}")
                            if iframe_box and (iframe_box['width'] < 100 or iframe_box['height'] < 100):
                                self.logger.debug(f"Greenhouse iframe {i+1} appears small; scrolling into view")
                                await iframe.scroll_into_view_if_needed()
                                await self._smart_wait(page, 'long')  # Longer wait for Greenhouse
                                await self._dismiss_overlays(page)
                        except Exception:
                            pass
                        
                        frame = await iframe.content_frame()
                        if frame:
                            try:
                                self.logger.info(f"Loading Greenhouse iframe {i+1} content...")
                                # For Greenhouse, wait a bit longer but still optimized
                                await frame.wait_for_load_state('domcontentloaded', timeout=8000)  # Slightly longer for Greenhouse
                                # Give Greenhouse iframe time to fully expand
                                await page.wait_for_timeout(1500)  # Let iframe expand
                                try:
                                    await frame.wait_for_load_state('networkidle', timeout=4000)  # Moderate timeout
                                except Exception:
                                    self.logger.debug("Greenhouse iframe networkidle timeout; proceeding")
                                # Skip overlay dismissal for speed - Greenhouse forms usually don't need it
                                
                                frame_indicators = await frame.query_selector_all('input, textarea, select, [role="combobox"], [role="group"], button[type="submit"], fieldset')
                                self.logger.info(f"Greenhouse iframe {i+1} has {len(frame_indicators)} form elements")
                                if len(frame_indicators) > 5:  # Higher threshold for Greenhouse
                                    self.logger.info(f"✅ USING GREENHOUSE IFRAME {i+1} with {len(frame_indicators)} elements")
                                    # Skip debug artifact for speed
                                    self.iframe_context = {
                                        "is_iframe": True,
                                        "iframe_src": src,
                                        "iframe_selector": f'iframe[src*="greenhouse"]',
                                        "iframe_index": i,
                                        "wait_strategy": "domcontentloaded",
                                        "load_timeout": 8000  # Adjusted timeout
                                    }
                                    return frame
                            except Exception as frame_error:
                                self.logger.error(f"Error loading Greenhouse iframe {i+1}: {frame_error}")
                                continue
                except Exception as e:
                    self.logger.debug(f"Error checking iframe {i+1}: {e}")
                    continue
            
            # Second pass: Look for other job-related iframes
            for i, iframe in enumerate(iframes):
                try:
                    src = await iframe.get_attribute('src')
                    
                    # Skip if already processed as Greenhouse
                    if src and 'greenhouse' in src.lower():
                        continue
                        
                    # Check if it's likely a job form iframe
                    if src and any(keyword in src.lower() for keyword in ['job', 'career', 'apply', 'form', 'workday', 'lever', 'talent', 'recruit']):
                        try:
                            iframe_box = await iframe.bounding_box()
                            self.logger.debug(f"Job iframe {i+1} size: {iframe_box}")
                            if iframe_box and (iframe_box['width'] < 5 or iframe_box['height'] < 5):
                                self.logger.debug(f"Job iframe {i+1} appears small/hidden; scrolling into view")
                                await iframe.scroll_into_view_if_needed()
                                await self._smart_wait(page, 'medium')
                                await self._dismiss_overlays(page)
                        except Exception:
                            pass
                        
                        frame = await iframe.content_frame()
                        if frame:
                            try:
                                await frame.wait_for_load_state('domcontentloaded', timeout=10000)
                                await self._smart_wait(page, 'medium')
                                try:
                                    await frame.wait_for_load_state('networkidle', timeout=7000)
                                except Exception:
                                    self.logger.debug("Job iframe networkidle timeout; proceeding")
                                await self._dismiss_overlays(frame)
                                
                                frame_indicators = await frame.query_selector_all('input, textarea, select, [role="combobox"], [role="group"], button[type="submit"], fieldset')
                                if len(frame_indicators) > 2:
                                    self.logger.info(f"Found job application form in iframe {i+1} with {len(frame_indicators)} elements")
                                    await self._save_debug_artifact(frame, f'iframe_{i+1}_form_detected')
                                    self.iframe_context = {
                                        "is_iframe": True,
                                        "iframe_src": src or "unknown",
                                        "iframe_selector": f'iframe[src*="{self._extract_domain_from_src(src) if src else ""}"]' if src else f'iframe:nth-child({i+1})',
                                        "iframe_index": i,
                                        "wait_strategy": "domcontentloaded",
                                        "load_timeout": 15000
                                    }
                                    return frame
                            except Exception as frame_error:
                                self.logger.debug(f"Error loading iframe {i+1} content: {frame_error}")
                                continue
                except Exception as e:
                    self.logger.debug(f"Error checking iframe {i+1}: {e}")
                    continue
            
            # PRIORITY 2 FALLBACK: Check for actual form elements on main page only if no iframe forms were found
            self.logger.info("No iframe forms found; checking main page as fallback")
            form_elements = await page.query_selector_all('form')
            if form_elements:
                for form in form_elements:
                    try:
                        inputs = await form.query_selector_all('input[type="text"], input[type="email"], textarea')
                        if len(inputs) >= 2:
                            self.logger.info("Found application form element on main page (fallback)")
                            self.iframe_context["form_container"] = form
                            await form.scroll_into_view_if_needed()
                            await self._smart_wait(page, 'short')
                            await self._save_debug_artifact(page, 'form_on_main_page_fallback')
                            return page
                    except Exception as e:
                        self.logger.debug(f"Error checking form element: {e}")
            
            # PRIORITY 3 FALLBACK: Dedicated application sections on main page
            apply_sections = await page.query_selector_all('[id="apply"], [id="applynow"], [class*="apply-form"], [class*="application-form"], section:has(h2:has-text("Apply")), section:has(h3:has-text("Apply"))')
            for section in apply_sections:
                try:
                    inputs = await section.query_selector_all('input, select, textarea, [role="combobox"]')
                    if len(inputs) >= 2:
                        self.logger.info("Found dedicated application section (fallback)")
                        self.iframe_context["form_container"] = section
                        await section.scroll_into_view_if_needed()
                        await self._smart_wait(page, 'short')
                        await self._save_debug_artifact(page, 'form_section_on_main_page_fallback')
                        return page
                except Exception as e:
                    self.logger.debug(f"Error checking apply section: {e}")
            
            # Final check: any form-like elements at all
            form_elements = await page.query_selector_all('form, input, textarea, select, [role="combobox"]')
            if form_elements and len(form_elements) > 2:
                self.logger.info("Found form elements on main page; proceeding with main page context")
                await self._save_debug_artifact(page, 'fallback_main_page_elements_detected')
                return page
            
            self.logger.info("No form found in iframes; using main page as fallback")
            await self._save_debug_artifact(page, 'no_form_found_fallback')
            return page
            
        except Exception as e:
            self.logger.warning(f"Error finding form page: {e}")
            await self._save_debug_artifact(page, 'error_finding_form_page')
            return page

    async def _extract_phone_fields(self, page: Page, container=None) -> List[Dict]:
        """Extract phone fields, handling composite country+phone patterns."""
        fields = []
        context = container or page
        
        try:
            # Strategy 1: Look for composite phone containers (country selector + phone input)
            # Find containers that have both a combobox and a phone/text input
            potential_containers = await context.query_selector_all('div, section, fieldset')
            
            for container_elem in potential_containers:
                try:
                    # Look for country selector (combobox) and phone input (textbox) in the same container
                    country_selector = None
                    phone_input = None
                    
                    # Find combobox that looks like a country selector
                    comboboxes = await container_elem.query_selector_all('[role="combobox"]')
                    for cb in comboboxes:
                        cb_text = await cb.text_content() or ""
                        cb_name = await cb.get_attribute('name') or ""
                        cb_id = await cb.get_attribute('id') or ""
                        
                        # Check if this looks like a country selector
                        if (any(keyword in cb_text.lower() for keyword in ['country', '+1', '+44', '+49']) or
                            any(keyword in (cb_name + cb_id).lower() for keyword in ['country', 'phone_country'])):
                            country_selector = cb
                            break
                    
                    # Find text input that looks like a phone field
                    text_inputs = await container_elem.query_selector_all('input[type="text"], input[type="tel"], input:not([type]), textbox')
                    for inp in text_inputs:
                        inp_name = await inp.get_attribute('name') or ""
                        inp_id = await inp.get_attribute('id') or ""
                        inp_placeholder = await inp.get_attribute('placeholder') or ""
                        
                        # Check if this looks like a phone input
                        all_attrs = (inp_name + inp_id + inp_placeholder).lower()
                        if any(keyword in all_attrs for keyword in ['phone', 'mobile', 'tel']):
                            phone_input = inp
                            break
                    
                    # If we found both components, create a composite phone field
                    if country_selector and phone_input:
                        # Get the real label for the phone field
                        phone_id = await phone_input.get_attribute('id')
                        phone_name = await phone_input.get_attribute('name')
                        
                        label = await self._get_real_label(page, phone_input, phone_id)
                        if not label:
                            # Try to get label from the container or nearby text
                            container_text = await container_elem.text_content()
                            if container_text:
                                lines = [line.strip() for line in container_text.split('\n') if line.strip()]
                                for line in lines[:3]:  # Check first 3 lines
                                    clean_line = self._clean_label(line)
                                    if any(keyword in clean_line.lower() for keyword in ['phone', 'mobile', 'telephone']) and len(clean_line) < 50:
                                        label = clean_line
                                        break
                        
                        # Determine if required
                        required = await self._is_required(page, phone_input, phone_id)
                        
                        # Extract country options for metadata
                        country_options = []
                        try:
                            country_options = await self._extract_dropdown_options(page, country_selector)
                        except Exception as e:
                            self.logger.debug(f"Could not extract country options: {e}")
                        
                        if label:
                            field = {
                                'id': phone_id or '',
                                'name': phone_name or '',
                                'label': label,
                                'type': 'phone',
                                'required': required,
                                'country_selector': True,  # Indicates this has a country selector
                                'country_options': country_options[:10] if country_options else []  # Limit to first 10 for brevity
                            }
                            
                            fields.append(field)
                            self.logger.debug(f"Added composite phone field: {label}")
                            break  # Only process one phone field per container
                            
                except Exception as e:
                    self.logger.debug(f"Error processing potential phone container: {e}")
                    continue
            
            # Strategy 2: Look for standalone phone inputs that we might have missed
            if not fields:
                phone_inputs = await context.query_selector_all('input[type="tel"]')
                for phone_input in phone_inputs:
                    try:
                        phone_id = await phone_input.get_attribute('id')
                        phone_name = await phone_input.get_attribute('name')
                        
                        # Check if this input is already processed or near a country selector
                        already_processed = False
                        for field in fields:
                            if field.get('id') == phone_id or field.get('name') == phone_name:
                                already_processed = True
                                break
                        
                        if not already_processed:
                            label = await self._get_real_label(page, phone_input, phone_id)
                            required = await self._is_required(page, phone_input, phone_id)
                            
                            if label:
                                fields.append({
                                    'id': phone_id or '',
                                    'name': phone_name or '',
                                    'label': label,
                                    'type': 'phone',
                                    'required': required,
                                    'country_selector': False
                                })
                                self.logger.debug(f"Added standalone phone field: {label}")
                                
                    except Exception as e:
                        self.logger.debug(f"Error processing standalone phone input: {e}")
                        continue
        
        except Exception as e:
            self.logger.debug(f"Error in phone field extraction: {e}")
        
        return fields

    async def _extract_text_fields(self, page: Page, container=None, processed_phone_fields=None) -> List[Dict]:
        """Extract text input fields with real labels from the form container."""
        fields = []
        processed_phone_fields = processed_phone_fields or []
        
        # If container is None, fall back to the full page
        context = container or page
        
        # Find all text inputs with expanded selectors
        inputs = await context.query_selector_all('input[type="text"], input[type="email"], input[type="tel"], input[type="url"], input:not([type]), [contenteditable="true"]')
        
        # Filter out hidden inputs and inputs that are likely not part of the form
        filtered_inputs = []
        for input_elem in inputs:
            try:
                # Skip if it's actually a dropdown (combobox)
                role = await input_elem.get_attribute('role')
                if role == 'combobox':
                    continue
                
                # Skip if this is already processed as a phone field
                input_id = await input_elem.get_attribute('id')
                input_name = await input_elem.get_attribute('name')
                
                already_processed = False
                for phone_field in processed_phone_fields:
                    if ((input_id and phone_field.get('id') == input_id) or 
                        (input_name and phone_field.get('name') == input_name)):
                        already_processed = True
                        break
                
                if already_processed:
                    self.logger.debug(f"Skipping input already processed as phone field: {input_id}")
                    continue
                
                # Skip hidden or invisible inputs
                try:
                    box = await input_elem.bounding_box()
                    if not box or box['width'] <= 1 or box['height'] <= 1:
                        continue
                    
                    # Ensure element is scrolled into view
                    await input_elem.scroll_into_view_if_needed()
                    await self._smart_wait(page, 'minimal')
                except Exception:
                    continue
                
                # Get basic attributes
                id_attr = await input_elem.get_attribute('id')
                name_attr = await input_elem.get_attribute('name')
                placeholder = await input_elem.get_attribute('placeholder')
                
                # Get the real label
                label = await self._get_real_label(page, input_elem, id_attr)
                
                # If no label found but we have placeholder, use that
                if not label and placeholder and placeholder.strip():
                    label = placeholder.strip()
                
                # If we still don't have a label, try looking for text elements near the input
                if not label:
                    try:
                        # Get input position
                        box = await input_elem.bounding_box()
                        if box:
                            # Look for elements above or to the left
                            label_candidates = await page.query_selector_all('label, div, span, p')
                            for elem in label_candidates:
                                elem_box = await elem.bounding_box()
                                if not elem_box:
                                    continue
                                
                                # Check if element is above or to the left
                                is_above = (elem_box['y'] + elem_box['height'] <= box['y'] + 5 and 
                                           abs(elem_box['x'] - box['x']) < 150)
                                is_left = (elem_box['x'] + elem_box['width'] <= box['x'] + 5 and 
                                          abs(elem_box['y'] - box['y']) < 30)
                                
                                if is_above or is_left:
                                    text = await elem.text_content()
                                    if text and text.strip():
                                        label = self._clean_label(text.strip())
                                        if self._is_valid_label(label):
                                            break
                    except Exception as label_err:
                        self.logger.debug(f"Error finding nearby label: {label_err}")
                
                # If still no label but we have name/id attributes, generate label from them
                if not label and (id_attr or name_attr):
                    attr_for_label = id_attr or name_attr
                    # Convert ID/name to a readable label
                    import re
                    label = re.sub(r'[_\-]', ' ', attr_for_label).strip()
                    # Fix capitalization
                    label = ' '.join(word.capitalize() for word in label.split())
                
                # Determine if required
                required = await self._is_required(page, input_elem, id_attr)
                
                # Determine field type based on attributes or parent container
                field_type = 'text'
                input_type = await input_elem.get_attribute('type')
                
                if input_type == 'email':
                    field_type = 'email'
                elif input_type == 'tel':
                    field_type = 'phone'
                elif input_type == 'url':
                    field_type = 'url'
                elif label:
                    label_lower = label.lower()
                    if 'email' in label_lower:
                        field_type = 'email'
                    elif 'phone' in label_lower or 'mobile' in label_lower:
                        field_type = 'phone'
                    elif 'linkedin' in label_lower or 'website' in label_lower or 'url' in label_lower:
                        field_type = 'url'
                
                # Filter out problematic cases before adding the field
                if label:
                    skip_field = False
                    
                    # Skip if no ID/name AND label is suspiciously long (likely a heading or description)
                    if not id_attr and not name_attr and len(label) > 100:
                        self.logger.debug(f"Skipping likely heading/description text: {label[:50]}...")
                        skip_field = True
                    
                    # Skip if this looks like a dropdown helper input (often hidden textboxes)
                    # These are common in custom dropdown implementations
                    if not skip_field:
                        parent_classes = []
                        try:
                            parent = await input_elem.query_selector('..')
                            if parent:
                                class_attr = await parent.get_attribute('class')
                                if class_attr:
                                    parent_classes = class_attr.lower().split()
                        except:
                            pass
                        
                        # Skip if parent container suggests this is part of a dropdown
                        if any(keyword in ' '.join(parent_classes) for keyword in ['dropdown', 'select', 'combobox']):
                            self.logger.debug(f"Skipping dropdown helper input: {label[:30]}...")
                            skip_field = True
                    
                    # Skip if the input appears to be a hidden helper for a nearby dropdown
                    if not skip_field:
                        try:
                            input_box = await input_elem.bounding_box()
                            if input_box:
                                # Look for nearby dropdowns/comboboxes
                                nearby_dropdowns = await page.query_selector_all('select, [role="combobox"]')
                                for dropdown in nearby_dropdowns:
                                    dropdown_box = await dropdown.bounding_box()
                                    if dropdown_box:
                                        # Check if very close to a dropdown (within 50px)
                                        distance = abs(input_box['x'] - dropdown_box['x']) + abs(input_box['y'] - dropdown_box['y'])
                                        if distance < 50:
                                            self.logger.debug(f"Skipping input near dropdown: {label[:30]}...")
                                            skip_field = True
                                            break
                        except:
                            pass
                    
                    if not skip_field:
                        fields.append({
                            'id': id_attr or '',
                            'name': name_attr or '',
                            'label': label,
                            'type': field_type,
                            'required': required
                        })
                    
            except Exception as e:
                self.logger.debug(f"Error processing text field: {e}")
                continue
        
        return fields

    async def _extract_dropdown_fields(self, page: Page, container=None, processed_phone_fields=None) -> List[Dict]:
        """Extract dropdown fields with real labels and options from the form container."""
        fields = []
        processed_phone_fields = processed_phone_fields or []
        
        # If container is None, fall back to the full page
        context = container or page
        
        # Find dropdown elements with various selectors for different implementations
        dropdown_selectors = [
            'select',  # Standard HTML select element - most reliable
            '[role="combobox"]',  # ARIA role for comboboxes
            'div[aria-haspopup="listbox"]',  # ARIA attribute for dropdown triggering a listbox
            'div[aria-expanded]',  # Elements with aria-expanded attribute (dropdown triggers)
            '.custom-select',  # Common class name
            '.form-select'  # Common class name
        ]
        
        all_dropdowns = []
        
        # Find dropdowns using different selectors
        for selector in dropdown_selectors:
            dropdowns = await context.query_selector_all(selector)
            
            for dropdown in dropdowns:
                # Check if element is visible
                try:
                    box = await dropdown.bounding_box()
                    if box and box['width'] > 0 and box['height'] > 0:
                        # Check it's not already in our list
                        already_added = False
                        dropdown_id = await dropdown.get_attribute('id') or ""
                        
                        if dropdown_id:
                            for existing in all_dropdowns:
                                existing_id = await existing.get_attribute('id') or ""
                                if existing_id and existing_id == dropdown_id:
                                    already_added = True
                                    break
                        
                        if not already_added:
                            all_dropdowns.append(dropdown)
                except Exception:
                    continue
        
        self.logger.info(f"Found {len(all_dropdowns)} potential dropdown elements")
        
        # Process each dropdown
        for i, dropdown in enumerate(all_dropdowns):
            try:
                self.logger.info(f"Processing dropdown {i+1}/{len(all_dropdowns)}")
                
                # Skip if this dropdown is a country selector that's part of a phone field
                dropdown_text = await dropdown.text_content() or ""
                dropdown_name = await dropdown.get_attribute('name') or ""
                dropdown_id = await dropdown.get_attribute('id') or ""
                
                # Check if this looks like a country selector
                is_country_selector = (
                    any(keyword in dropdown_text.lower() for keyword in ['country', '+1', '+44', '+49', '+353']) or
                    any(keyword in (dropdown_name + dropdown_id).lower() for keyword in ['country', 'phone_country']) or
                    'selected country' in dropdown_text.lower()
                )
                
                # If this is a country selector and we have phone fields with country selectors, skip it
                if is_country_selector and any(pf.get('country_selector') for pf in processed_phone_fields):
                    self.logger.debug(f"Skipping country selector dropdown (already processed with phone field): {dropdown_text[:50]}")
                    continue
                
                # Get basic attributes
                id_attr = await dropdown.get_attribute('id')
                name_attr = await dropdown.get_attribute('name')
                
                # Scroll to the dropdown to ensure it's in view
                try:
                    await dropdown.scroll_into_view_if_needed()
                    await self._smart_wait(page, 'short')
                except Exception:
                    pass
                
                # Get the real label
                label = await self._get_real_label(page, dropdown, id_attr)
                
                # If we still don't have a label, try to look for labels near the dropdown
                if not label:
                    try:
                        # Get dropdown position
                        box = await dropdown.bounding_box()
                        if box:
                            # Look for elements above or to the left
                            label_candidates = await page.query_selector_all('label, div, span, p')
                            for elem in label_candidates:
                                elem_box = await elem.bounding_box()
                                if not elem_box:
                                    continue
                                
                                # Check if element is above or to the left
                                is_above = (elem_box['y'] + elem_box['height'] <= box['y'] + 5 and 
                                           abs(elem_box['x'] - box['x']) < 100)
                                is_left = (elem_box['x'] + elem_box['width'] <= box['x'] + 5 and 
                                          abs(elem_box['y'] - box['y']) < 30)
                                
                                if is_above or is_left:
                                    text = await elem.text_content()
                                    if text and text.strip():
                                        label = self._clean_label(text.strip())
                                        if self._is_valid_label(label):
                                            break
                    except Exception as label_err:
                        self.logger.debug(f"Error finding nearby label: {label_err}")
                
                # If we still don't have a label but have a name/id, generate one from that
                if not label and (id_attr or name_attr):
                    attr_for_label = id_attr or name_attr
                    # Convert ID/name to a readable label
                    import re
                    label = re.sub(r'[_\-]', ' ', attr_for_label).strip()
                    # Fix capitalization
                    label = ' '.join(word.capitalize() for word in label.split())
                
                # Determine if required
                required = await self._is_required(page, dropdown, id_attr)
                
                # Extract options and check for dynamic loading
                options, has_dynamic_loading = await self._extract_dropdown_options_with_loading_detection(page, dropdown)
                self.logger.info(f"Found {len(options)} options for dropdown {id_attr}, dynamic loading: {has_dynamic_loading}")
                
                if label:
                    field = {
                        'id': id_attr or '',
                        'name': name_attr or '',
                        'label': label,
                        'type': 'dropdown',
                        'required': required,
                        'supports_custom_input': True  # Indicates user can type custom values
                    }
                    
                    # Add options if we found any
                    if options:
                        field['options'] = options
                        self.logger.info(f"Added {len(options)} options to field {id_attr}")
                    
                    # Add appropriate note based on dynamic loading detection
                    if has_dynamic_loading or not options:
                        # For dropdowns with dynamic loading or no extracted options
                        if options:
                            field['options_note'] = 'These are sample options. You can type any value that matches your specific case.'
                        else:
                            field['options_note'] = 'This dropdown accepts custom input. Type the value that matches your specific case.'
                    else:
                        # For static dropdowns with complete option lists (like Yes/No)
                        field['options_note'] = 'Select from the available options.'
                    
                    fields.append(field)
                    
            except Exception as e:
                self.logger.error(f"Error processing dropdown {i+1}: {e}")
                continue
        
        return fields

    async def _extract_file_fields(self, page: Page, container=None) -> List[Dict]:
        """Extract file input fields and upload components from the form container."""
        fields = []
        
        # If container is None, fall back to the full page
        context = container or page
        
        # Track file inputs that are already processed as part of upload groups
        # Use a more reliable tracking method with element attributes
        processed_file_input_ids = set()
        
        # STEP 1: Process upload groups first (to avoid duplicates)
        upload_selectors = ['[role="group"]', 'group', 'fieldset']
        
        for selector in upload_selectors:
            upload_groups = await page.query_selector_all(selector)
            
            for i, group in enumerate(upload_groups):
                try:
                    # Check if this is a file upload group
                    group_text = await group.text_content()
                    if not group_text:
                        continue
                    
                    group_text_lower = group_text.lower()
                    
                    if any(keyword in group_text_lower for keyword in ['resume', 'cv', 'cover letter']):
                        # Track all file inputs within this group to prevent duplicate extraction
                        group_file_inputs = await group.query_selector_all('input[type="file"]')
                        for file_input in group_file_inputs:
                            # Create a unique identifier for this file input
                            try:
                                input_id = await file_input.get_attribute('id')
                                input_name = await file_input.get_attribute('name')
                                input_class = await file_input.get_attribute('class')
                                
                                # Create identifier based on available attributes
                                if input_id:
                                    identifier = f"id:{input_id}"
                                elif input_name:
                                    identifier = f"name:{input_name}"
                                else:
                                    # Fallback: use bounding box position as identifier
                                    box = await file_input.bounding_box()
                                    if box:
                                        identifier = f"pos:{box['x']},{box['y']}"
                                    else:
                                        identifier = f"class:{input_class or 'none'}"
                                
                                processed_file_input_ids.add(identifier)
                                self.logger.info(f"Tracked file input in group: {identifier}")
                            except Exception as e:
                                self.logger.debug(f"Error tracking file input: {e}")
                        
                        # Extract the main label from the group
                        label = await self._extract_file_group_label(group)
                        
                        # Check if required
                        required = '*' in group_text or 'required' in group_text_lower
                        
                        # Extract upload options
                        upload_options = await self._extract_upload_options(group)
                        
                        # Get accepted file types
                        accepted_types = await self._extract_accepted_types(group)
                        
                        if label:
                            field_id = label.lower().replace(' ', '_').replace('/', '_')
                            field = {
                                'id': field_id,
                                'name': '',
                                'label': label,
                                'type': 'file',
                                'required': required

                            }
                            
                            if upload_options:
                                field['upload_options'] = upload_options
                            
                            if accepted_types:
                                field['accepted_types'] = accepted_types
                            
                            fields.append(field)
                            self.logger.info(f"Processed upload group: {label} (tracked {len(group_file_inputs)} file inputs)")
                            
                except Exception as e:
                    self.logger.debug(f"Error processing upload group {i+1}: {e}")
                    continue
        
        # STEP 2: Process individual file inputs (skip those already processed in groups)
        file_inputs = await context.query_selector_all('input[type="file"]')
        
        for file_input in file_inputs:
            try:
                # Create the same identifier for this file input
                input_id = await file_input.get_attribute('id')
                input_name = await file_input.get_attribute('name')
                input_class = await file_input.get_attribute('class')
                
                # Create identifier using the same logic as above
                if input_id:
                    identifier = f"id:{input_id}"
                elif input_name:
                    identifier = f"name:{input_name}"
                else:
                    # Fallback: use bounding box position as identifier
                    box = await file_input.bounding_box()
                    if box:
                        identifier = f"pos:{box['x']},{box['y']}"
                    else:
                        identifier = f"class:{input_class or 'none'}"
                
                # Skip if this file input was already processed as part of an upload group
                if identifier in processed_file_input_ids:
                    self.logger.info(f"Skipping file input already processed in upload group: {identifier}")
                    continue
                
                # Get the real label
                label = await self._get_real_label(page, file_input, input_id)
                
                # Determine if required
                required = await self._is_required(page, file_input, input_id)
                
                # Get accepted file types
                accept = await file_input.get_attribute('accept')
                
                if label and (input_id or input_name):
                    field = {
                        'id': input_id or '',
                        'name': input_name or '',
                        'label': label,
                        'type': 'file',
                        'required': required
                    }
                    
                    if accept:
                        field['accepted_types'] = accept
                    
                    fields.append(field)
                    self.logger.info(f"Processed individual file input: {label} ({identifier})")
                    
            except Exception as e:
                self.logger.debug(f"Error processing file field: {e}")
                continue
        
        return fields

    async def _extract_textarea_fields(self, page: Page, container=None) -> List[Dict]:
        """Extract textarea fields from the form container."""
        fields = []
        
        # If container is None, fall back to the full page
        context = container or page
        
        textareas = await context.query_selector_all('textarea')
        
        for textarea in textareas:
            try:
                id_attr = await textarea.get_attribute('id')
                name_attr = await textarea.get_attribute('name')
                
                # Get the real label
                label = await self._get_real_label(page, textarea, id_attr)
                
                # Determine if required
                required = await self._is_required(page, textarea, id_attr)
                
                if label and (id_attr or name_attr):
                    fields.append({
                        'id': id_attr or '',
                        'name': name_attr or '',
                        'label': label,
                        'type': 'textarea',
                        'required': required
                    })
                    
            except Exception as e:
                self.logger.debug(f"Error processing textarea field: {e}")
                continue
        
        return fields

    async def _get_real_label(self, page: Page, element: ElementHandle, id_attr: str) -> Optional[str]:
        """Get the actual human-readable label for a form field."""
        try:
            # Method 1: Traditional label[for="id"]
            if id_attr:
                label_elem = await page.query_selector(f'label[for="{id_attr}"]')
                if label_elem:
                    text = await label_elem.text_content()
                    if text and text.strip():
                        return self._clean_label(text.strip())
            
            # Method 2: Look for Greenhouse-style question structure
            # Find the parent container and look for question text
            element_box = await element.bounding_box()
            if element_box:
                # Look for text elements above the field that could be labels
                all_text_elements = await page.query_selector_all('div, span, p, h1, h2, h3, h4, h5, h6, label')
                
                candidates = []
                for text_elem in all_text_elements:
                    try:
                        text_box = await text_elem.bounding_box()
                        if not text_box:
                            continue
                        
                        # Check if this text is above our element
                        vertical_distance = element_box['y'] - (text_box['y'] + text_box['height'])
                        horizontal_overlap = min(element_box['x'] + element_box['width'], text_box['x'] + text_box['width']) - max(element_box['x'], text_box['x'])
                        
                        # Good candidate: above the element, some horizontal overlap
                        if 0 <= vertical_distance <= 200 and horizontal_overlap > 0:
                            text_content = await text_elem.text_content()
                            if text_content and text_content.strip():
                                clean_text = self._clean_label(text_content.strip())
                                if self._is_valid_label(clean_text):
                                    score = 200 - vertical_distance  # Closer is better
                                    candidates.append((clean_text, score))
                    except:
                        continue
                
                # Return the best candidate
                if candidates:
                    candidates.sort(key=lambda x: x[1], reverse=True)
                    return candidates[0][0]
            
            # Method 3: Look in parent containers
            current = element
            for _ in range(3):
                try:
                    parent = await current.query_selector('..')
                    if not parent:
                        break
                    
                    # Check if parent is a label
                    tag_name = await parent.evaluate('el => el.tagName.toLowerCase()')
                    if tag_name in ['label', 'fieldset']:
                        text = await parent.text_content()
                        if text and text.strip():
                            clean_text = self._clean_label(text.strip())
                            if self._is_valid_label(clean_text):
                                return clean_text
                    
                    current = parent
                except:
                    break
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error getting label: {e}")
            return None

    async def _extract_dropdown_options(self, page: Page, dropdown: ElementHandle) -> List[Dict]:
        """Extract options from a dropdown by clicking it."""
        options = []
        try:
            # Get dropdown ID for debugging
            dropdown_id = await dropdown.get_attribute('id') or 'unknown'
            self.logger.debug(f"Extracting options for dropdown: {dropdown_id}")
            
            # First check if this is a standard HTML select element
            tag_name = await dropdown.evaluate('el => el.tagName.toLowerCase()')
            if tag_name == 'select':
                # For standard HTML select, get options directly
                option_elements = await dropdown.query_selector_all('option')
                for option_elem in option_elements:
                    try:
                        text = await option_elem.text_content()
                        value = await option_elem.get_attribute('value')
                        
                        if text and text.strip():
                            clean_text = text.strip()
                            # Skip empty placeholder options
                            if clean_text and clean_text not in ['', 'Select...', 'Choose...']:
                                clean_value = value or clean_text.lower().replace(' ', '_')
                                options.append({
                                    'text': clean_text,
                                    'value': clean_value
                                })
                                self.logger.debug(f"Added select option: {clean_text}")
                    except Exception as e:
                        self.logger.debug(f"Error processing select option: {e}")
                
                self.logger.debug(f"Extracted {len(options)} options from HTML select")
                return options
            
            # For custom dropdowns, we need to click and find the options
            # Close any open dropdowns first
            await page.evaluate('document.querySelectorAll("[role=\\"option\\"]").forEach(el => { const container = el.closest("[role=\\"listbox\\"], .dropdown, .select"); if (container) container.style.display = "none"; })')
            await self._smart_wait(page, 'minimal')
            
            # Ensure element is visible by scrolling to it
            try:
                await dropdown.scroll_into_view_if_needed()
                await self._smart_wait(page, 'short')
            except Exception:
                pass
            
            # Get bounding box to check if element is actually visible
            try:
                box = await dropdown.bounding_box()
                is_visible = box and box['width'] > 0 and box['height'] > 0
                if not is_visible:
                    self.logger.warning(f"Dropdown {dropdown_id} is not visible. Skipping option extraction.")
                    return options
            except Exception:
                pass
            
            # Get dropdown position to help filter relevant options
            dropdown_box = await dropdown.bounding_box()
            
            # Try different strategies to open the dropdown
            opened = False
            
            # Strategy 1: Direct click
            try:
                await dropdown.click(timeout=2500)  # 5000 -> 2500
                await self._smart_wait(page, 'medium')
                opened = True
            except Exception as e:
                self.logger.debug(f"Direct click failed: {e}")
                
            # Strategy 2: Try to find and click an arrow or toggle inside the dropdown
            if not opened:
                try:
                    # Look for common dropdown arrow/toggle elements
                    selectors = [
                        'svg', 
                        '[class*="arrow"]', 
                        '[class*="caret"]', 
                        '[class*="chevron"]',
                        '[class*="toggle"]',
                        'button'
                    ]
                    
                    for selector in selectors:
                        arrow = await dropdown.query_selector(selector)
                        if arrow:
                            await arrow.click(timeout=2500)  # 5000 -> 2500
                            await self._smart_wait(page, 'medium')
                            opened = True
                            self.logger.debug(f"Clicked dropdown arrow using selector: {selector}")
                            break
                except Exception as e:
                    self.logger.debug(f"Arrow click strategy failed: {e}")
            
            # Strategy 3: JavaScript click
            if not opened:
                try:
                    await page.evaluate('element => element.click()', dropdown)
                    await self._smart_wait(page, 'medium')
                    opened = True
                    self.logger.debug("Used JavaScript click")
                except Exception as e:
                    self.logger.debug(f"JavaScript click failed: {e}")
            
            # Find the options using multiple selectors
            option_selectors = [
                '[role="option"]',
                'li[data-value]',
                'option',
                '.dropdown-option',
                '.select-option',
                '[class*="option"]'
            ]
            
            # First try to find options within a dropdown container/listbox near our dropdown
            listbox_selectors = [
                '[role="listbox"]',
                '[class*="dropdown"]',
                '[class*="select"]',
                '[class*="menu"]',
                '[class*="list"]',
                'ul'
            ]
            
            # Look for options within a dropdown container first
            option_elements = []
            for listbox_selector in listbox_selectors:
                listboxes = await page.query_selector_all(listbox_selector)
                if listboxes:
                    for listbox in listboxes:
                        # Check if this listbox is visible and near our dropdown
                        try:
                            box = await listbox.bounding_box()
                            if box and box['width'] > 0 and box['height'] > 0:
                                # Check proximity to our dropdown (within reasonable distance)
                                if dropdown_box:
                                    distance = abs(box['y'] - dropdown_box['y']) + abs(box['x'] - dropdown_box['x'])
                                    if distance > 500:  # Too far away, likely not related
                                        continue
                                
                                # Try all option selectors in this listbox
                                for option_selector in option_selectors:
                                    elements = await listbox.query_selector_all(option_selector)
                                    if elements and len(elements) > 0:
                                        # Filter out elements that are clearly not dropdown options
                                        filtered_elements = []
                                        for elem in elements:
                                            elem_text = await elem.text_content()
                                            if elem_text and elem_text.strip():
                                                text = elem_text.strip()
                                                # Skip navigation items, long text, etc.
                                                if (len(text) < 100 and 
                                                    text.lower() not in ['see all jobs', 'your settings', 'view favorites', 'add to favorites'] and
                                                    'navigation' not in text.lower() and
                                                    'menu' not in text.lower()):
                                                    filtered_elements.append(elem)
                                        
                                        if filtered_elements:
                                            self.logger.debug(f"Found {len(filtered_elements)} filtered options in listbox with selector: {option_selector}")
                                            option_elements = filtered_elements
                                            break
                                
                                if option_elements:
                                    break
                        except Exception:
                            continue
                
                if option_elements:
                    break
            
            # If we couldn't find options within a container, look for visible options near the dropdown
            if not option_elements:
                for selector in option_selectors:
                    elements = await page.query_selector_all(selector)
                    if elements and len(elements) > 0:
                        # Filter by proximity and content
                        filtered_elements = []
                        for elem in elements:
                            try:
                                elem_box = await elem.bounding_box()
                                elem_text = await elem.text_content()
                                
                                if elem_box and elem_text and elem_text.strip():
                                    text = elem_text.strip()
                                    
                                    # Skip if too far from dropdown
                                    if dropdown_box:
                                        distance = abs(elem_box['y'] - dropdown_box['y']) + abs(elem_box['x'] - dropdown_box['x'])
                                        if distance > 500:
                                            continue
                                    
                                    # Skip navigation items and other non-dropdown text
                                    if (len(text) < 100 and 
                                        text.lower() not in ['see all jobs', 'your settings', 'view favorites', 'add to favorites'] and
                                        'navigation' not in text.lower() and
                                        'menu' not in text.lower() and
                                        'footer' not in text.lower()):
                                        filtered_elements.append(elem)
                            except Exception:
                                continue
                        
                        if filtered_elements:
                            self.logger.debug(f"Found {len(filtered_elements)} filtered options with selector: {selector}")
                            option_elements = filtered_elements
                            break
            
            # Process found options
            for i, option_elem in enumerate(option_elements):
                try:
                    text = await option_elem.text_content()
                    value = (await option_elem.get_attribute('value') or 
                           await option_elem.get_attribute('data-value') or
                           await option_elem.get_attribute('data-option-value'))
                    
                    if text and text.strip():
                        clean_text = text.strip()
                        # Skip placeholder options and empty options
                        if clean_text.lower() in ['select...', 'choose...', 'select an option', ''] or len(clean_text) < 1:
                            continue
                        
                        # Additional filtering for navigation/menu items
                        if clean_text.lower() in ['see all jobs', 'your settings', 'view favorites', 'add to favorites', 'home', 'about', 'contact']:
                            continue
                        
                        # For Toast/custom forms: if the text is very long, it might be a container, not an option
                        if len(clean_text) > 100:
                            continue
                            
                        clean_value = value or clean_text.lower().replace(' ', '_').replace(',', '').replace('(', '').replace(')', '').replace('.', '').replace('/', '_')
                        
                        options.append({
                            'text': clean_text,
                            'value': clean_value
                        })
                        self.logger.debug(f"Added option {i+1}: {clean_text}")
                except Exception as option_error:
                    self.logger.debug(f"Error processing option {i+1}: {option_error}")
                    continue
            
            # Close the dropdown by pressing Escape or clicking elsewhere
            try:
                try:
                    await page.keyboard.press('Escape')
                except Exception:
                    # For iframe frames or if keyboard press fails
                    try:
                        await page.press('body', 'Escape')
                    except Exception:
                        # As a last resort, click elsewhere on the page
                        await page.click('body', position={'x': 10, 'y': 10})
            except Exception as close_error:
                self.logger.debug(f"Error closing dropdown: {close_error}")
            
            await self._smart_wait(page, 'short')
            
            self.logger.debug(f"Extracted {len(options)} options for dropdown {dropdown_id}")
            
        except Exception as e:
            self.logger.warning(f"Error extracting dropdown options: {e}")
        
        return options

    async def _extract_dropdown_options_with_loading_detection(self, page: Page, dropdown: ElementHandle) -> tuple[List[Dict], bool]:
        """Extract options from a dropdown and detect if it has dynamic loading behavior."""
        try:
            # Get dropdown ID for debugging
            dropdown_id = await dropdown.get_attribute('id') or 'unknown'
            self.logger.debug(f"Extracting options with loading detection for dropdown: {dropdown_id}")
            
            # First get initial options using the existing method
            initial_options = await self._extract_dropdown_options(page, dropdown)
            
            # For HTML select elements, they typically don't have dynamic loading
            tag_name = await dropdown.evaluate('el => el.tagName.toLowerCase()')
            if tag_name == 'select':
                return initial_options, False
            
            # For custom dropdowns, test for dynamic loading
            has_dynamic_loading = False
            
            try:
                # Try to detect if scrolling in the dropdown loads more options
                await dropdown.scroll_into_view_if_needed()
                await self._smart_wait(page, 'short')
                
                # Open the dropdown
                await dropdown.click(timeout=2000)  # Further reduced
                await self._smart_wait(page, 'short')  # Reduced from 'medium'
                
                # Count initial visible options before scrolling
                initial_option_count = len(await page.query_selector_all('[role="option"], option'))
                
                # Try scrolling to see if more options appear
                try:
                    # Press End key multiple times to trigger loading
                    for _ in range(3):
                        await page.keyboard.press('End')
                        await asyncio.sleep(self.timeouts['scroll_detection_wait'] / 1000)  # Configurable scroll wait
                    
                    # Check if more options appeared - use longer wait for dynamic loading
                    await asyncio.sleep(self.timeouts['dynamic_loading_wait'] / 1000)  # Configurable dynamic loading wait
                    new_option_count = len(await page.query_selector_all('[role="option"], option'))
                    
                    if new_option_count > initial_option_count:
                        has_dynamic_loading = True
                        self.logger.info(f"Detected dynamic loading: {initial_option_count} -> {new_option_count} options")
                    
                except Exception as scroll_error:
                    self.logger.debug(f"Error during scroll test: {scroll_error}")
                
                # Close the dropdown
                try:
                    await page.keyboard.press('Escape')
                except Exception:
                    await page.click('body', position={'x': 10, 'y': 10})
                
                await self._smart_wait(page, 'short')
                
            except Exception as test_error:
                self.logger.debug(f"Error during dynamic loading test: {test_error}")
            
            # Additional heuristics to detect dynamic loading
            if not has_dynamic_loading and len(initial_options) > 0:
                # Check for common school/university indicators that suggest a large dataset
                option_texts = [opt['text'].lower() for opt in initial_options]
                university_indicators = ['university', 'college', 'institute', 'school']
                has_university_content = any(indicator in ' '.join(option_texts) for indicator in university_indicators)
                
                if has_university_content and len(initial_options) >= 20:
                    # School/university dropdowns with 20+ options are likely dynamic
                    has_dynamic_loading = True
                    self.logger.debug("Detected school/university dropdown with dynamic loading")
                elif not has_university_content and len(initial_options) >= 100:
                    # For non-university dropdowns, use a much higher threshold (100+)
                    # This prevents academic discipline lists (~72 items) from being marked as dynamic
                    has_dynamic_loading = True
                    self.logger.debug(f"Assuming dynamic loading due to very large option count: {len(initial_options)}")
            
            return initial_options, has_dynamic_loading
            
        except Exception as e:
            self.logger.warning(f"Error in loading detection: {e}")
            # Fall back to basic extraction
            options = await self._extract_dropdown_options(page, dropdown)
            return options, False

    async def _is_required(self, page: Page, element: ElementHandle, id_attr: str) -> bool:
        """Determine if a field is required."""
        try:
            # Check required attribute
            required_attr = await element.get_attribute('required')
            if required_attr is not None:
                return True
            
            # Check aria-required
            aria_required = await element.get_attribute('aria-required')
            if aria_required == 'true':
                return True
            
            # Look for asterisk (*) near the field
            if id_attr:
                # Look for label with asterisk
                label_elem = await page.query_selector(f'label[for="{id_attr}"]')
                if label_elem:
                    label_text = await label_elem.text_content()
                    if label_text and '*' in label_text:
                        return True
            
            # Look for asterisk in parent containers
            current = element
            for _ in range(3):
                try:
                    parent = await current.query_selector('..')
                    if not parent:
                        break
                    
                    # Check for asterisk in this container
                    asterisk_elem = await parent.query_selector('*:has-text("*")')
                    if asterisk_elem:
                        return True
                    
                    current = parent
                except:
                    break
            
            return False
            
        except Exception:
            return False

    async def _extract_file_group_label(self, group: ElementHandle) -> Optional[str]:
        """Extract the main label from a file upload group."""
        try:
            # First, try to get the group's accessible name or title
            aria_label = await group.get_attribute('aria-label')
            if aria_label and aria_label.strip():
                clean_label = self._clean_label(aria_label.strip())
                if clean_label:
                    self.logger.debug(f"Found aria-label: {clean_label}")
                    return clean_label
            
            # Look for the main heading/label in the group
            label_selectors = ['legend', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'label', '[role="heading"]']
            
            for selector in label_selectors:
                label_elem = await group.query_selector(selector)
                if label_elem:
                    text = await label_elem.text_content()
                    if text and text.strip():
                        clean_text = self._clean_label(text.strip())
                        if clean_text and not any(skip in clean_text.lower() for skip in ['attach', 'dropbox', 'google drive', 'enter manually']):
                            self.logger.debug(f"Found label from {selector}: {clean_text}")
                            return clean_text
            
            # Try to extract from group structure - look for direct text children
            all_text = await group.text_content()
            if all_text:
                lines = [line.strip() for line in all_text.split('\n') if line.strip()]
                
                # Look for the first meaningful line that could be a label
                for line in lines[:3]:  # Check first 3 lines
                    clean_line = self._clean_label(line)
                    if clean_line and len(clean_line) > 2 and len(clean_line) < 50:
                        # Skip button/option text
                        if not any(skip in clean_line.lower() for skip in [
                            'attach', 'dropbox', 'google drive', 'enter manually', 
                            'accepted file types', 'pdf', 'doc', 'docx', 'browse'
                        ]):
                            self.logger.debug(f"Found label from text content: {clean_line}")
                            return clean_line
                
                # Fallback: look for common patterns
                text_lower = all_text.lower()
                if 'resume' in text_lower and 'cv' in text_lower:
                    return "Resume/CV"
                elif 'resume' in text_lower:
                    return "Resume"
                elif 'cv' in text_lower:
                    return "CV"
                elif 'cover letter' in text_lower:
                    return "Cover Letter"
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error extracting file group label: {e}")
            return None

    async def _extract_upload_options(self, group: ElementHandle) -> List[str]:
        """Extract available upload options from a file upload group."""
        try:
            options = []
            
            # Look for buttons that indicate upload methods
            buttons = await group.query_selector_all('button')
            
            for button in buttons:
                try:
                    button_text = await button.text_content()
                    if button_text and button_text.strip():
                        text = button_text.strip()
                        if any(option in text.lower() for option in ['attach', 'dropbox', 'google drive', 'enter manually', 'browse', 'upload']):
                            options.append(text)
                except:
                    continue
            
            # Also check for text mentions of these options
            all_text = await group.text_content()
            if all_text:
                text_lower = all_text.lower()
                possible_options = ['Attach', 'Dropbox', 'Google Drive', 'Enter manually']
                for option in possible_options:
                    if option.lower() in text_lower and option not in options:
                        options.append(option)
            
            return options
            
        except Exception as e:
            self.logger.debug(f"Error extracting upload options: {e}")
            return []

    async def _extract_accepted_types(self, group: ElementHandle) -> Optional[str]:
        """Extract accepted file types from a file upload group."""
        try:
            all_text = await group.text_content()
            if all_text and 'accepted file types' in all_text.lower():
                # Find the line with accepted file types
                lines = all_text.split('\n')
                for line in lines:
                    if 'accepted file types' in line.lower():
                        # Extract the file types part
                        parts = line.split(':')
                        if len(parts) > 1:
                            types_part = parts[1].strip()
                            return types_part
            
            # Look for input[accept] in the group
            file_input = await group.query_selector('input[type="file"]')
            if file_input:
                accept = await file_input.get_attribute('accept')
                if accept:
                    return accept
            
            return None
            
        except Exception as e:
            self.logger.debug(f"Error extracting accepted types: {e}")
            return None

    def _clean_label(self, text: str) -> str:
        """Clean up label text."""
        # Remove asterisks and extra whitespace
        text = text.replace('*', '').strip()
        
        # Remove random hash IDs like "0444ca7a", "35410d3d", etc.
        import re
        text = re.sub(r'\s+[a-f0-9]{8}$', '', text)
        
        # Remove (required) markers
        text = re.sub(r'\s*\(required\)\s*', '', text)
        
        # Remove multiple spaces
        text = re.sub(r'\s+', ' ', text)
        
        return text

    def _is_valid_label(self, text: str) -> bool:
        """Check if text is a valid label (not just random text)."""
        if not text or len(text) < 3:
            return False
        
        # Skip common non-label text
        skip_patterns = [
            'select...', 'choose', 'attach', 'browse', 'upload',
            'dropbox', 'google drive', 'enter manually',
            'accepted file types', 'pdf', 'doc', 'docx'
        ]
        
        text_lower = text.lower()
        for pattern in skip_patterns:
            if pattern in text_lower:
                return False
        
        # Good labels usually contain questions or descriptive text
        return len(text.split()) >= 2 or '?' in text or text.isupper()

    def _clean_and_dedupe_fields(self, fields: List[Dict]) -> List[Dict]:
        """Remove duplicates and clean field data."""
        seen = {}
        clean_fields = []
        
        for field in fields:
            # Create identifier for deduplication
            # Primary identifier: ID if it exists and is not empty
            # Secondary identifier: label (cleaned)
            # This ensures we catch duplicates even when IDs are missing
            
            id_attr = field.get('id', '').strip()
            name_attr = field.get('name', '').strip()
            label = field.get('label', '').strip()
            
            # Use ID if available, otherwise use cleaned label as identifier
            if id_attr:
                primary_identifier = id_attr
            elif name_attr:
                primary_identifier = name_attr
            else:
                # Use label but clean it to handle slight variations
                primary_identifier = self._normalize_label_for_deduplication(label)
            
            # Also create a label-based identifier to catch cases where 
            # the same field has different IDs but same label
            label_identifier = self._normalize_label_for_deduplication(label)
            
            # Special handling for file fields
            if field.get('type') == 'file':
                primary_identifier = label_identifier + '_file'
                label_identifier = label_identifier + '_file'
            
            # Check if we've seen this field before (by either identifier)
            existing_field = None
            existing_key = None
            
            # First check by primary identifier
            if primary_identifier in seen:
                existing_field = seen[primary_identifier]
                existing_key = primary_identifier
            # Then check by label identifier if different
            elif label_identifier != primary_identifier and label_identifier in seen:
                existing_field = seen[label_identifier]  
                existing_key = label_identifier
            
            if existing_field:
                # Keep the field with more information (dropdown with options > text field, etc.)
                should_replace = False
                
                # Dropdown with options beats everything else
                if (field.get('type') == 'dropdown' and field.get('options') and
                    existing_field.get('type') != 'dropdown'):
                    should_replace = True
                # Dropdown without options beats text field
                elif (field.get('type') == 'dropdown' and existing_field.get('type') == 'text'):
                    should_replace = True
                # File with upload options beats basic file
                elif (field.get('type') == 'file' and field.get('upload_options') and
                      not existing_field.get('upload_options')):
                    should_replace = True
                # Field with ID beats field without ID
                elif id_attr and not existing_field.get('id', '').strip():
                    should_replace = True
                
                if should_replace:
                    # Remove old field from seen dict
                    if existing_key in seen:
                        del seen[existing_key]
                    # Add new field with primary identifier
                    seen[primary_identifier] = field
                    # Update in clean_fields list
                    for i, cf in enumerate(clean_fields):
                        if cf is existing_field:
                            clean_fields[i] = field
                            break
                # If not replacing, we might need to update the seen dict key
                elif existing_key != primary_identifier:
                    # Update the key but keep the existing field
                    del seen[existing_key]
                    seen[primary_identifier] = existing_field
            else:
                # New field
                seen[primary_identifier] = field
                clean_fields.append(field)
        
        return clean_fields
    
    def _normalize_label_for_deduplication(self, label: str) -> str:
        """Normalize a label for deduplication purposes."""
        if not label:
            return ""
        
        # Convert to lowercase and remove extra whitespace
        normalized = label.lower().strip()
        
        # Remove common variations and extra characters
        import re
        # Remove random IDs/hashes at the end (like "fd7093fa")
        normalized = re.sub(r'\s+[a-f0-9]{8}$', '', normalized)
        # Remove (required) markers
        normalized = re.sub(r'\s*\(required\)\s*', '', normalized)
        # Remove asterisks
        normalized = normalized.replace('*', '').strip()
        # Normalize multiple spaces
        normalized = re.sub(r'\s+', ' ', normalized)
        
        return normalized

    def _generate_user_input_template(self, fields: List[Dict]) -> List[Dict]:
        """Generate a user input template with questions and empty values for user to fill."""
        template = []
        
        for field in fields:
            template_field = {
                'id': field.get('id', ''),
                'question': field.get('label', ''),
                'value': '',
                'required': field.get('required', False),
                'type': field.get('type', 'text')
            }
            
            # Add options for dropdown fields to help user choose
            if field.get('type') == 'dropdown' and field.get('options'):
                template_field['available_options'] = [opt.get('text', '') for opt in field['options']]
                
                # Add guidance about custom input
                if field.get('supports_custom_input'):
                    template_field['supports_custom_input'] = True
                    template_field['note'] = field.get('options_note', 'You can type a custom value if your option is not listed.')
            elif field.get('type') == 'dropdown':
                # For dropdowns without extracted options
                template_field['supports_custom_input'] = True 
                template_field['note'] = field.get('options_note', 'Type the value that matches your specific case.')
            
            # Add file type information for file fields
            if field.get('type') == 'file':
                if field.get('accepted_types'):
                    template_field['accepted_file_types'] = field['accepted_types']
                if field.get('upload_options'):
                    template_field['upload_methods'] = field['upload_options']
            
            # Add phone field specific information
            if field.get('type') == 'phone':
                if field.get('country_selector'):
                    template_field['has_country_selector'] = True
                    template_field['note'] = 'This field has a country selector. Select your country code first, then enter your phone number.'
                if field.get('country_options'):
                    template_field['sample_countries'] = [opt.get('text', '') for opt in field['country_options'][:5]]
            
            template.append(template_field)
        
        return template

    async def _extract_job_title(self, page: Page) -> str:
        """Extract job title from the page."""
        try:
            # Try common selectors for job title
            selectors = ['h1', '.job-title', '[data-testid="job-title"]', 'title']
            
            for selector in selectors:
                elem = await page.query_selector(selector)
                if elem:
                    text = await elem.text_content()
                    if text and text.strip() and len(text.strip()) < 200:
                        return text.strip()
            
            # Fallback: get from page title
            title = await page.title()
            if 'Job Application for' in title:
                # Extract job title from "Job Application for TITLE at COMPANY"
                parts = title.split('Job Application for ')
                if len(parts) > 1:
                    job_part = parts[1].split(' at ')[0]
                    return job_part.strip()
            
            return "Unknown Position"
            
        except Exception:
            return "Unknown Position"

    async def _extract_company(self, page: Page) -> str:
        """Extract company name from the page."""
        try:
            # Try from page title first
            title = await page.title()
            if ' at ' in title:
                company = title.split(' at ')[-1]
                return company.strip()
            
            # Try common selectors
            selectors = ['.company-name', '[data-testid="company-name"]', 'img[alt*="Logo"]']
            
            for selector in selectors:
                elem = await page.query_selector(selector)
                if elem:
                    if selector.startswith('img'):
                        alt_text = await elem.get_attribute('alt')
                        if alt_text and 'logo' in alt_text.lower():
                            company = alt_text.replace('Logo', '').replace('logo', '').strip()
                            if company:
                                return company
                    else:
                        text = await elem.text_content()
                        if text and text.strip():
                            return text.strip()
            
            return "Unknown Company"
            
        except Exception:
            return "Unknown Company"

    def _extract_domain_from_src(self, src: str) -> str:
        """Extract a meaningful domain identifier from iframe src for selector."""
        try:
            if 'greenhouse' in src.lower():
                return 'greenhouse'
            elif 'workday' in src.lower():
                return 'workday'
            elif 'lever' in src.lower():
                return 'lever'
            else:
                # Extract domain from URL
                from urllib.parse import urlparse
                parsed = urlparse(src)
                domain = parsed.netloc.split('.')[0] if parsed.netloc else 'iframe'
                return domain
        except Exception:
            return 'iframe'


async def main():
    if len(sys.argv) not in [2, 3]:
        print("Usage: python simple_form_extractor.py <job_url> [config_file]")
        print("Example: python simple_form_extractor.py <url> config.json")
        sys.exit(1)
    
    url = sys.argv[1]
    
    # Load configuration if provided
    config = {}
    if len(sys.argv) == 3:
        config_file = sys.argv[2]
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            print(f"📋 Loaded configuration from {config_file}")
        except Exception as e:
            print(f"⚠️  Warning: Could not load config file {config_file}: {e}")
            print("Using default configuration...")
    
    extractor = SimpleFormExtractor(config)
    
    try:
        form_data = await extractor.extract_form_data(url)
        
        # Create filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"simple_form_data_{timestamp}.json"
        
        # Save to file
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(form_data, f, indent=2, ensure_ascii=False)
        
        print(f"✅ Form data extracted and saved to {filename}")
        print(f"📊 Found {form_data['total_fields']} fields ({form_data['required_fields']} required)")
        print("\n🔍 Fields Preview:")
        for i, field in enumerate(form_data['fields'][:5], 1):
            req_indicator = " *" if field.get('required') else ""
            options_info = f" ({len(field.get('options', []))} options)" if field.get('options') else ""
            print(f"  {i}. {field['label']} ({field['type']}){req_indicator}{options_info}")
        
        if len(form_data['fields']) > 5:
            print(f"  ... and {len(form_data['fields']) - 5} more fields")
        
    except Exception as e:
        logger.error(f"Error extracting form data: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
