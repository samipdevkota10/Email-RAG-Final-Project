"""
HTML cleaning and text extraction utilities for email offer extraction.
Strips scripts, styles, tracking pixels, and converts HTML to readable text.
"""

import re
from html import unescape
from typing import Optional, List
from bs4 import BeautifulSoup


def clean_html(html_content: Optional[str]) -> str:
    """
    Clean HTML content by removing scripts, styles, and converting to readable text.
    
    Args:
        html_content: Raw HTML string from email body
        
    Returns:
        Clean, readable text with normalized whitespace
    """
    if not html_content:
        return ""
    
    try:
        soup = BeautifulSoup(html_content, 'lxml')
    except Exception:
        # Fallback to html.parser if lxml not available
        soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove script and style elements
    for script in soup(["script", "style", "noscript"]):
        script.decompose()
    
    # Remove tracking pixels (common patterns)
    for img in soup.find_all("img"):
        if img is None:
            continue
        # Remove very small images (likely tracking pixels)
        width = img.get("width", "")
        height = img.get("height", "")
        if (isinstance(width, str) and width.isdigit() and int(width) <= 1) or \
           (isinstance(height, str) and height.isdigit() and int(height) <= 1):
            img.decompose()
            continue
        # Remove images with common tracking pixel attributes
        src = img.get("src", "")
        if src and isinstance(src, str):
            src_lower = src.lower()
            if any(tracker in src_lower for tracker in ["track", "pixel", "beacon", "analytics"]):
                img.decompose()
    
    # Get text content
    text = soup.get_text()
    
    # Decode HTML entities
    text = unescape(text)
    
    # Normalize whitespace
    text = normalize_whitespace(text)
    
    return text


def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text.
    
    Args:
        text: Input text
        
    Returns:
        Text with normalized whitespace
    """
    # Replace various whitespace characters with single space
    text = re.sub(r'\s+', ' ', text)
    # Remove leading/trailing whitespace
    text = text.strip()
    return text


def extract_candidate_blocks(
    header_text: Optional[str],
    body_html: Optional[str],
    max_body_chars: int = 2000
) -> str:
    """
    Extract candidate text blocks likely to contain offers.
    
    Strategy:
    - Include header text (subject line)
    - Include first N characters of body
    - Include lines containing offer keywords
    
    Args:
        header_text: Email header/subject text
        body_html: Email body HTML
        max_body_chars: Maximum characters to extract from body
        
    Returns:
        Combined candidate text for offer extraction
    """
    blocks = []
    
    # Add header text
    if header_text:
        blocks.append(header_text.strip())
    
    # Clean and extract body text
    body_text = clean_html(body_html)
    
    if body_text:
        # Get first portion of body
        first_chunk = body_text[:max_body_chars]
        blocks.append(first_chunk)
        
        # Extract lines with offer keywords (even if beyond first chunk)
        offer_keywords = [
            r'%', r'off', r'save', r'\$', r'code', r'promo',
            r'free shipping', r'shop', r'today', r'ends', r'discount'
        ]
        
        lines = body_text.split('\n')
        keyword_lines = []
        for line in lines:
            line_lower = line.lower()
            if any(re.search(keyword, line_lower) for keyword in offer_keywords):
                keyword_lines.append(line.strip())
        
        # Add keyword lines (avoid duplicates)
        for line in keyword_lines[:10]:  # Limit to 10 lines
            if line and line not in blocks:
                blocks.append(line)
    
    # Combine blocks
    combined = " ".join(blocks)
    
    # Final normalization
    return normalize_whitespace(combined)

