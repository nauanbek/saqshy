"""
SAQSHY Content Analyzer

Analyzes message content for spam and scam signals.
Performs URL extraction, pattern matching, and text analysis.

This module is optimized for speed (<50ms per message) and provides
group-type-aware analysis with different whitelists and thresholds.
"""

import re
from urllib.parse import urlparse

import structlog

from saqshy.core.constants import (
    ALLOWED_SHORTENERS,
    CRYPTO_SCAM_PHRASES,
    SUSPICIOUS_TLDS,
    WHITELIST_DOMAINS_DEALS,
    WHITELIST_DOMAINS_GENERAL,
    WHITELIST_DOMAINS_TECH,
)
from saqshy.core.types import ContentSignals, GroupType, MessageContext

logger = structlog.get_logger(__name__)


class ContentAnalyzer:
    """
    Analyzes message content for risk signals.

    Extracts signals from:
    - Text characteristics (length, caps, emojis, language)
    - URLs (count, domains, shorteners, suspicious TLDs)
    - Pattern matching (crypto scam phrases, money, urgency)
    - Contact information (phone numbers, wallet addresses)
    - Media and forwarding metadata

    Group type awareness:
    - DEALS groups: use extended domain whitelist and allow shorteners
    - TECH groups: use tech domain whitelist (github, docs, etc.)
    - CRYPTO groups: wallet addresses are less suspicious
    - GENERAL groups: use base whitelist only
    """

    # URL extraction pattern - comprehensive regex for URLs
    URL_PATTERN = re.compile(
        r"https?://[^\s<>\[\]()\"'{}|\\^`]+|"  # Standard URLs with protocol
        r"www\.[^\s<>\[\]()\"'{}|\\^`]+|"  # www. prefixed
        r"[a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:/[^\s<>\[\]()\"'{}|\\^`]*)?",  # domain.tld
        re.IGNORECASE,
    )

    # Common URL shorteners (superset - includes both allowed and not allowed)
    KNOWN_SHORTENERS: set[str] = {
        # General shorteners
        "bit.ly",
        "goo.gl",
        "tinyurl.com",
        "t.co",
        "ow.ly",
        "is.gd",
        "buff.ly",
        "j.mp",
        "tr.im",
        "su.pr",
        "cli.gs",
        "short.to",
        "cutt.ly",
        "rb.gy",
        "shorturl.at",
        "rebrand.ly",
        "adf.ly",
        # Affiliate/deals shorteners (may be allowed in deals groups)
        "clck.ru",
        "fas.st",
        "got.by",
        "ali.ski",
        "s.click.aliexpress.com",
        "trk.mail.ru",
        "amzn.to",
    }

    # Money-related patterns (multilingual)
    MONEY_PATTERN = re.compile(
        r"\$\s?\d+(?:[.,]\d+)?(?:\s?(?:k|K|m|M|usd|USD|usdt|USDT))?\b|"  # $100, $5k
        r"\d+\s?(?:dollars?|USD|usd|usdt|USDT)\b|"  # 100 dollars
        r"(?:earn|make|get|win|receive)\s+(?:easy\s+)?money|"  # earn money
        r"(?:зарабо|получ|выигр)\w*\s+(?:деньги|денег)|"  # Russian: earn money
        r"\d+\s?(?:руб|рублей|RUB)\b|"  # 1000 rubles
        r"\u20bd\s?\d+|"  # Ruble symbol
        r"\u20ac\s?\d+|\d+\s?\u20ac|"  # Euro
        r"\u00a3\s?\d+|\d+\s?\u00a3|"  # Pound
        r"\d+(?:,\d{3})*(?:\.\d{2})?\s*(?:USD|EUR|RUB|USDT|BTC|ETH)\b",  # amounts with currency
        re.IGNORECASE,
    )

    # Urgency patterns (multilingual)
    URGENCY_PATTERN = re.compile(
        r"(?:limited\s+)?(?:time|spots?|offer)|"
        r"act\s+now|"
        r"hurry\s+up|"
        r"don'?t\s+miss|"
        r"last\s+chance|"
        r"only\s+\d+\s+(?:left|remaining|spots?)|"
        r"expires?\s+(?:soon|today|tomorrow)|"
        r"urgent|"
        r"quick|"
        r"fast\s+(?:money|cash|profit)|"
        # Russian patterns
        r"(?:ограничен|успей|торопи|не\s+упусти|последний\s+шанс|срочно|быстр)",
        re.IGNORECASE,
    )

    # Phone number patterns (international formats)
    PHONE_PATTERN = re.compile(
        r"\+?\d{1,4}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}|"  # International
        r"\+7\s?\(?\d{3}\)?\s?\d{3}[-\s]?\d{2}[-\s]?\d{2}|"  # Russian
        r"\+1\s?\(?\d{3}\)?\s?\d{3}[-\s]?\d{4}|"  # US
        r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",  # 123-456-7890
        re.IGNORECASE,
    )

    # Crypto wallet address patterns
    WALLET_PATTERN = re.compile(
        r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b|"  # Bitcoin legacy (P2PKH/P2SH)
        r"\bbc1[a-zA-HJ-NP-Z0-9]{25,90}\b|"  # Bitcoin Bech32
        r"\b0x[a-fA-F0-9]{40}\b|"  # Ethereum
        r"\bT[A-Za-z1-9]{33}\b|"  # Tron (TRC20)
        r"\b[LM3][a-km-zA-HJ-NP-Z1-9]{26,33}\b|"  # Litecoin
        r"\bbnb1[a-z0-9]{38}\b|"  # Binance Chain
        r"\b[45][0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b",  # Monero
        re.IGNORECASE,
    )

    # Emoji pattern for counting
    EMOJI_PATTERN = re.compile(
        "["
        "\U0001f600-\U0001f64f"  # emoticons
        "\U0001f300-\U0001f5ff"  # symbols & pictographs
        "\U0001f680-\U0001f6ff"  # transport & map symbols
        "\U0001f700-\U0001f77f"  # alchemical symbols
        "\U0001f780-\U0001f7ff"  # Geometric Shapes Extended
        "\U0001f800-\U0001f8ff"  # Supplemental Arrows-C
        "\U0001f900-\U0001f9ff"  # Supplemental Symbols and Pictographs
        "\U0001fa00-\U0001fa6f"  # Chess Symbols
        "\U0001fa70-\U0001faff"  # Symbols and Pictographs Extended-A
        "\U00002702-\U000027b0"  # Dingbats
        "\U000024c2-\U0001f251"
        "]+"
    )

    # Cyrillic and Latin character patterns
    CYRILLIC_PATTERN = re.compile(r"[\u0400-\u04FF]")
    LATIN_PATTERN = re.compile(r"[a-zA-Z]")

    def __init__(self) -> None:
        """Initialize ContentAnalyzer with compiled regex patterns."""
        # Pre-compile crypto scam phrase patterns for efficient matching
        self._crypto_scam_patterns: list[re.Pattern[str]] = []
        for phrase in CRYPTO_SCAM_PHRASES:
            # Escape special regex characters in the phrase
            escaped = re.escape(phrase)
            # Create pattern that matches the phrase with word-like boundaries
            # Using lookahead/lookbehind for better boundary detection
            pattern = re.compile(
                rf"(?:^|[\s\.,!?:;\-\"'()\[\]]){escaped}(?:[\s\.,!?:;\-\"'()\[\]]|$)",
                re.IGNORECASE,
            )
            self._crypto_scam_patterns.append(pattern)

    async def analyze(self, context: MessageContext) -> ContentSignals:
        """
        Analyze message content and extract signals.

        This is the main entry point for content analysis. It extracts all
        signals defined in ContentSignals dataclass and returns them.

        Args:
            context: MessageContext containing message data and metadata.

        Returns:
            ContentSignals with all extracted signals populated.

        Note:
            This method is async for interface consistency but performs
            no I/O operations. All analysis is done in-memory.
        """
        text = context.text or ""
        group_type = context.group_type

        # Text analysis
        text_length = len(text)
        word_count = len(text.split()) if text else 0
        caps_ratio = self._calculate_caps_ratio(text)
        emoji_count = self._count_emojis(text)
        has_cyrillic = self._has_cyrillic(text)
        has_latin = self._has_latin(text)
        language = self._detect_language(text, has_cyrillic, has_latin)

        # URL extraction and analysis
        urls = self._extract_urls(text)
        url_count = len(urls)
        domains = self._extract_domains(urls)
        unique_domains = len(domains)

        has_shortened_urls = self._check_shortened_urls(domains, group_type)
        has_whitelisted_urls = self._check_whitelisted_urls(domains, group_type)
        has_suspicious_tld = self._check_suspicious_tlds(urls)

        # Pattern matching
        has_crypto_scam_phrases = self._check_crypto_scam_phrases(text)
        has_money_patterns = self._check_money_patterns(text)
        has_urgency_patterns = self._check_urgency_patterns(text)
        has_phone_numbers = self._check_phone_numbers(text)
        has_wallet_addresses = self._check_wallet_addresses(text)

        # Media and forwarding (from context metadata)
        has_media = context.has_media
        has_forward = context.is_forward
        forward_from_channel = self._is_forward_from_channel(context)

        return ContentSignals(
            text_length=text_length,
            word_count=word_count,
            caps_ratio=caps_ratio,
            emoji_count=emoji_count,
            has_cyrillic=has_cyrillic,
            has_latin=has_latin,
            language=language,
            url_count=url_count,
            has_shortened_urls=has_shortened_urls,
            has_whitelisted_urls=has_whitelisted_urls,
            has_suspicious_tld=has_suspicious_tld,
            unique_domains=unique_domains,
            has_crypto_scam_phrases=has_crypto_scam_phrases,
            has_money_patterns=has_money_patterns,
            has_urgency_patterns=has_urgency_patterns,
            has_phone_numbers=has_phone_numbers,
            has_wallet_addresses=has_wallet_addresses,
            has_media=has_media,
            has_forward=has_forward,
            forward_from_channel=forward_from_channel,
        )

    def _calculate_caps_ratio(self, text: str) -> float:
        """
        Calculate the ratio of uppercase letters to total letters.

        Only considers alphabetic characters (ignores numbers, punctuation).

        Args:
            text: Input text to analyze.

        Returns:
            Float between 0.0 and 1.0 representing caps ratio.
        """
        if not text:
            return 0.0

        letters = [c for c in text if c.isalpha()]
        if not letters:
            return 0.0

        uppercase = sum(1 for c in letters if c.isupper())
        return uppercase / len(letters)

    def _count_emojis(self, text: str) -> int:
        """
        Count the number of emoji characters in text.

        Args:
            text: Input text to analyze.

        Returns:
            Number of emoji characters found.
        """
        if not text:
            return 0

        emojis = self.EMOJI_PATTERN.findall(text)
        return sum(len(e) for e in emojis)

    def _has_cyrillic(self, text: str) -> bool:
        """
        Check if text contains Cyrillic characters.

        Args:
            text: Input text to analyze.

        Returns:
            True if Cyrillic characters are found.
        """
        return bool(self.CYRILLIC_PATTERN.search(text)) if text else False

    def _has_latin(self, text: str) -> bool:
        """
        Check if text contains Latin characters.

        Args:
            text: Input text to analyze.

        Returns:
            True if Latin characters are found.
        """
        return bool(self.LATIN_PATTERN.search(text)) if text else False

    def _detect_language(self, text: str, has_cyrillic: bool, has_latin: bool) -> str:
        """
        Detect the primary language of the text.

        Uses simple heuristic based on character set ratio.
        For more accurate detection, consider langdetect library.

        Args:
            text: Input text to analyze.
            has_cyrillic: Whether text contains Cyrillic characters.
            has_latin: Whether text contains Latin characters.

        Returns:
            Language code: "ru" for Russian, "en" for English,
            "mixed" for mixed content, "unknown" otherwise.
        """
        if not text:
            return "unknown"

        cyrillic_count = len(self.CYRILLIC_PATTERN.findall(text))
        latin_count = len(self.LATIN_PATTERN.findall(text))

        if cyrillic_count == 0 and latin_count == 0:
            return "unknown"

        total = cyrillic_count + latin_count

        if cyrillic_count / total > 0.7:
            return "ru"
        elif latin_count / total > 0.7:
            return "en"
        elif has_cyrillic and has_latin:
            return "mixed"
        elif has_cyrillic:
            return "ru"
        elif has_latin:
            return "en"

        return "unknown"

    def _extract_urls(self, text: str) -> list[str]:
        """
        Extract all URLs from text.

        Handles various URL formats including:
        - Full URLs with protocol (https://example.com)
        - www-prefixed URLs (www.example.com)
        - Bare domains with TLDs (example.com)

        Args:
            text: Input text to analyze.

        Returns:
            List of URL strings found in text.
        """
        if not text:
            return []

        urls = self.URL_PATTERN.findall(text)

        # Clean up URLs - remove trailing punctuation
        cleaned_urls = []
        for url in urls:
            url = url.rstrip(".,;:!?)'\"")
            if url:
                cleaned_urls.append(url)

        return cleaned_urls

    def _extract_domains(self, urls: list[str]) -> set[str]:
        """
        Extract unique domains from URLs.

        Normalizes domains to lowercase and removes www prefix.

        Args:
            urls: List of URL strings.

        Returns:
            Set of unique domain names.
        """
        domains: set[str] = set()

        for url in urls:
            try:
                # Add protocol if missing for proper parsing
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url

                parsed = urlparse(url)
                domain = parsed.netloc.lower()

                # Remove www. prefix
                if domain.startswith("www."):
                    domain = domain[4:]

                # Remove port if present
                if ":" in domain:
                    domain = domain.split(":")[0]

                if domain:
                    domains.add(domain)

            except ValueError as e:
                # URL parsing failed - try fallback extraction
                logger.debug(
                    "url_parse_failed_trying_fallback",
                    url=url[:100] if url else "",
                    error=str(e),
                )
                try:
                    match = re.search(
                        r"(?:https?://)?(?:www\.)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
                        url,
                    )
                    if match:
                        domains.add(match.group(1).lower())
                except re.error as regex_err:
                    logger.warning(
                        "domain_regex_extraction_failed",
                        url=url[:100] if url else "",
                        error=str(regex_err),
                    )
            except (AttributeError, TypeError, IndexError) as e:
                # Unexpected error during URL parsing - log and continue
                logger.warning(
                    "unexpected_url_parsing_error",
                    url=url[:100] if url else "",
                    error=str(e),
                    error_type=type(e).__name__,
                )

        return domains

    def _check_shortened_urls(self, domains: set[str], group_type: GroupType) -> bool:
        """
        Check if any domain is a known URL shortener.

        For DEALS groups, shorteners in ALLOWED_SHORTENERS are permitted.

        Args:
            domains: Set of domain names.
            group_type: Type of group for context-aware checking.

        Returns:
            True if suspicious (non-allowed) shortened URLs are found.
        """
        for domain in domains:
            if domain in self.KNOWN_SHORTENERS:
                # In deals groups, allowed shorteners are okay
                if group_type == GroupType.DEALS and domain in ALLOWED_SHORTENERS:
                    continue
                return True

        return False

    def _check_whitelisted_urls(self, domains: set[str], group_type: GroupType) -> bool:
        """
        Check if any domain is whitelisted for the group type.

        Supports both exact domain matches and subdomain matches.

        Args:
            domains: Set of domain names.
            group_type: Type of group for selecting appropriate whitelist.

        Returns:
            True if any domain is in the whitelist.
        """
        # Select appropriate whitelist based on group type
        if group_type == GroupType.DEALS:
            whitelist = WHITELIST_DOMAINS_DEALS
        elif group_type == GroupType.TECH:
            whitelist = WHITELIST_DOMAINS_TECH
        else:
            whitelist = WHITELIST_DOMAINS_GENERAL

        for domain in domains:
            # Check exact match
            if domain in whitelist:
                return True

            # Check if it's a subdomain of whitelisted domain
            for whitelisted in whitelist:
                if domain.endswith("." + whitelisted):
                    return True

        return False

    def _check_suspicious_tlds(self, urls: list[str]) -> bool:
        """
        Check if any URL has a suspicious TLD.

        Suspicious TLDs are often used for phishing and spam due to
        low registration costs and lax policies.

        Args:
            urls: List of URL strings.

        Returns:
            True if any URL has a suspicious TLD.
        """
        for url in urls:
            try:
                if not url.startswith(("http://", "https://")):
                    url = "https://" + url

                parsed = urlparse(url)
                domain = parsed.netloc.lower()

                # Remove www prefix and port
                if domain.startswith("www."):
                    domain = domain[4:]
                if ":" in domain:
                    domain = domain.split(":")[0]

                # Extract TLD (last part after final dot)
                if "." in domain:
                    tld = "." + domain.split(".")[-1]
                    if tld in SUSPICIOUS_TLDS:
                        return True

            except ValueError as e:
                # URL parsing error - log and continue checking other URLs
                logger.debug(
                    "tld_check_url_parse_failed",
                    url=url[:100] if url else "",
                    error=str(e),
                )
            except (AttributeError, TypeError, IndexError) as e:
                # Unexpected error during TLD check - log and continue
                logger.warning(
                    "unexpected_tld_check_error",
                    url=url[:100] if url else "",
                    error=str(e),
                    error_type=type(e).__name__,
                )

        return False

    def _check_crypto_scam_phrases(self, text: str) -> bool:
        """
        Check if text contains known crypto scam phrases.

        Uses pre-compiled regex patterns with boundary detection
        for accurate matching. Case-insensitive.

        These are HIGH RISK signals (+35 points) - distinct from neutral
        crypto keywords like "bitcoin", "ethereum", etc.

        Args:
            text: Input text to analyze.

        Returns:
            True if any crypto scam phrase is found.
        """
        if not text:
            return False

        for pattern in self._crypto_scam_patterns:
            if pattern.search(text):
                return True

        return False

    def _check_money_patterns(self, text: str) -> bool:
        """
        Check if text contains money-related patterns.

        Matches currency amounts and money-making phrases in
        English and Russian.

        Args:
            text: Input text to analyze.

        Returns:
            True if money patterns are found.
        """
        if not text:
            return False

        return bool(self.MONEY_PATTERN.search(text))

    def _check_urgency_patterns(self, text: str) -> bool:
        """
        Check if text contains urgency-inducing patterns.

        Matches phrases like "limited time", "act now", "hurry up"
        in English and Russian.

        Args:
            text: Input text to analyze.

        Returns:
            True if urgency patterns are found.
        """
        if not text:
            return False

        return bool(self.URGENCY_PATTERN.search(text))

    def _check_phone_numbers(self, text: str) -> bool:
        """
        Check if text contains phone numbers.

        Matches various international phone formats.
        Validates that matches have reasonable digit counts (7-15).

        Args:
            text: Input text to analyze.

        Returns:
            True if valid phone numbers are found.
        """
        if not text:
            return False

        matches = self.PHONE_PATTERN.findall(text)

        for match in matches:
            # Remove formatting characters
            digits = re.sub(r"[^\d]", "", match)
            # Valid phone numbers typically have 7-15 digits
            if 7 <= len(digits) <= 15:
                return True

        return False

    def _check_wallet_addresses(self, text: str) -> bool:
        """
        Check if text contains cryptocurrency wallet addresses.

        Supports: Bitcoin (legacy & Bech32), Ethereum, Tron,
        Litecoin, Binance Chain, and Monero.

        Note: In CRYPTO groups, wallet addresses may be less suspicious
        as they are normal for crypto discussions.

        Args:
            text: Input text to analyze.

        Returns:
            True if wallet addresses are found.
        """
        if not text:
            return False

        return bool(self.WALLET_PATTERN.search(text))

    def _is_forward_from_channel(self, context: MessageContext) -> bool:
        """
        Check if the message is forwarded from a channel.

        Args:
            context: MessageContext with forward metadata.

        Returns:
            True if forwarded from a channel.
        """
        if not context.is_forward:
            return False

        if context.forward_from_chat_id is None:
            return False

        # Check raw message for forward_from_chat type
        forward_chat = context.raw_message.get("forward_from_chat", {})
        return forward_chat.get("type") == "channel"
