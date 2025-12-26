"""
SAQSHY URL Utilities

URL extraction, parsing, and validation functions.
"""

import re
from re import Pattern
from urllib.parse import urlparse

import structlog

logger = structlog.get_logger(__name__)


# URL extraction pattern
URL_PATTERN: Pattern[str] = re.compile(
    r"https?://[^\s<>\"'{}|\\^`\[\]]+"
    r"|www\.[^\s<>\"'{}|\\^`\[\]]+"
    r"|[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s]*)?"
)

# Known URL shorteners
SHORTENER_DOMAINS: set[str] = {
    "bit.ly",
    "goo.gl",
    "t.co",
    "tinyurl.com",
    "is.gd",
    "cli.gs",
    "ow.ly",
    "buff.ly",
    "adf.ly",
    "j.mp",
    "clck.ru",
    "fas.st",
    "cutt.ly",
    "rb.gy",
    "shorturl.at",
    "rebrand.ly",
}


def extract_urls(text: str) -> list[str]:
    """
    Extract all URLs from text.

    Args:
        text: Input text.

    Returns:
        List of URL strings found.
    """
    if not text:
        return []

    urls = URL_PATTERN.findall(text)

    # Clean up URLs
    cleaned = []
    for url in urls:
        url = url.rstrip(".,;:!?)'\"")
        if url:
            cleaned.append(url)

    return cleaned


def extract_domains(urls: list[str]) -> set[str]:
    """
    Extract unique domains from URLs.

    Args:
        urls: List of URL strings.

    Returns:
        Set of unique domain names.
    """
    domains = set()

    for url in urls:
        domain = get_domain(url)
        if domain:
            domains.add(domain)

    return domains


def get_domain(url: str) -> str | None:
    """
    Extract domain from a URL.

    Args:
        url: URL string.

    Returns:
        Domain name or None.
    """
    try:
        # Add protocol if missing
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        parsed = urlparse(url)
        domain = parsed.netloc.lower()

        # Remove www. prefix
        if domain.startswith("www."):
            domain = domain[4:]

        # Remove port
        if ":" in domain:
            domain = domain.split(":")[0]

        return domain if domain else None

    except ValueError as e:
        logger.debug(
            "url_domain_parse_failed",
            url=url[:100] if url else "",
            error=str(e),
        )
        return None
    except Exception as e:
        logger.warning(
            "unexpected_domain_extraction_error",
            url=url[:100] if url else "",
            error=str(e),
            error_type=type(e).__name__,
        )
        return None


def is_shortened_url(url: str) -> bool:
    """
    Check if URL uses a shortener service.

    Args:
        url: URL string.

    Returns:
        True if URL is from a known shortener.
    """
    domain = get_domain(url)
    return domain in SHORTENER_DOMAINS if domain else False


def is_suspicious_tld(url: str) -> bool:
    """
    Check if URL has a suspicious TLD.

    Suspicious TLDs are often used for phishing
    due to low registration costs.

    Args:
        url: URL string.

    Returns:
        True if URL has suspicious TLD.
    """
    suspicious_tlds = {
        ".xyz",
        ".top",
        ".work",
        ".click",
        ".link",
        ".tk",
        ".ml",
        ".ga",
        ".cf",
        ".gq",
        ".pw",
        ".cc",
        ".ws",
    }

    domain = get_domain(url)
    if not domain:
        return False

    for tld in suspicious_tlds:
        if domain.endswith(tld):
            return True

    return False


def is_whitelisted(url: str, whitelist: set[str]) -> bool:
    """
    Check if URL is from a whitelisted domain.

    Supports both exact matches and subdomain matches.

    Args:
        url: URL string.
        whitelist: Set of whitelisted domains.

    Returns:
        True if URL is whitelisted.
    """
    domain = get_domain(url)
    if not domain:
        return False

    # Check exact match
    if domain in whitelist:
        return True

    # Check subdomain match
    for whitelisted in whitelist:
        if domain.endswith("." + whitelisted):
            return True

    return False


def normalize_url(url: str) -> str:
    """
    Normalize URL for comparison.

    Operations:
    - Add https:// if missing
    - Convert to lowercase
    - Remove trailing slash
    - Remove www. prefix

    Args:
        url: URL string.

    Returns:
        Normalized URL.
    """
    if not url:
        return ""

    # Add protocol
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    # Lowercase
    url = url.lower()

    # Parse and rebuild
    try:
        parsed = urlparse(url)
        domain = parsed.netloc

        # Remove www.
        if domain.startswith("www."):
            domain = domain[4:]

        # Rebuild
        path = parsed.path.rstrip("/")
        normalized = f"{parsed.scheme}://{domain}{path}"

        if parsed.query:
            normalized += f"?{parsed.query}"

        return normalized

    except ValueError as e:
        logger.debug(
            "url_normalize_parse_failed",
            url=url[:100] if url else "",
            error=str(e),
        )
        return url.rstrip("/")
    except Exception as e:
        logger.warning(
            "unexpected_url_normalize_error",
            url=url[:100] if url else "",
            error=str(e),
            error_type=type(e).__name__,
        )
        return url.rstrip("/")
