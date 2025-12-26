"""
SAQSHY Profile Analyzer

Analyzes Telegram user profiles for trust and risk signals.

This module extracts profile-based signals for the risk scoring system.
All analysis is performed in-memory with no external API calls.
Target performance: <10ms per message.

Signal Categories:
    Trust signals (reduce risk): account age, profile completeness, premium status
    Risk signals (increase risk): random usernames, crypto bio, emoji spam

Implementation Notes:
    - Account age uses tiered scoring (not binary old/new)
    - Emoji detection targets scam clusters, not all emoji use
    - Username analysis detects auto-generated patterns
    - Bio analysis detects promotional/crypto content
"""

import re

import structlog

from saqshy.core.types import MessageContext, ProfileSignals

logger = structlog.get_logger(__name__)


class ProfileAnalyzer:
    """
    Analyzes user profile data for risk signals.

    Extracts signals from:
    - Account age (tiered trust scoring)
    - Profile completeness (photo, bio, username)
    - Username patterns (auto-generated detection)
    - Bio content (links, crypto terms)
    - Name analysis (scam emoji clusters)
    - Premium and bot status

    Thread Safety:
        This class is stateless and thread-safe. All methods use
        only the input data and class constants.

    Performance:
        All analysis methods are designed for <10ms execution time.
        No I/O operations are performed.

    Example:
        >>> analyzer = ProfileAnalyzer()
        >>> signals = await analyzer.analyze(message_context)
        >>> print(signals.account_age_days, signals.has_username)
    """

    # ==========================================================================
    # Username Pattern Detection
    # ==========================================================================
    # Patterns that suggest auto-generated or suspicious usernames

    RANDOM_USERNAME_PATTERNS: list[re.Pattern[str]] = [
        # user123456, User_12345678 (Telegram default pattern)
        re.compile(r"^user[_]?\d{5,}$", re.IGNORECASE),
        # Letters followed by LONG number sequence: john12345678 (6+ digits)
        re.compile(r"^[a-z]{2,8}\d{6,}$", re.IGNORECASE),
        # Short prefix + underscore + numbers: ab_12345
        re.compile(r"^[a-z]{1,3}_\d{5,}$", re.IGNORECASE),
        # Hex-like strings (10+ hex chars - pure hex patterns)
        re.compile(r"^[a-f0-9]{10,}$", re.IGNORECASE),
        # Telegram auto-generated pattern: FirstnameXXXXX (capitalized name + 5+ digits)
        re.compile(r"^[A-Z][a-z]+\d{5,}$"),
        # Bot-like patterns with numbers at both ends: 123abc456
        re.compile(r"^\d{2,}[a-z]+\d{2,}$", re.IGNORECASE),
        # Very long random letters (18+ chars with no underscores)
        re.compile(r"^[a-z]{18,}$", re.IGNORECASE),
        # Mixed alphanumeric with MANY digits (12+ chars, >50% digits)
        # e.g., a1b2c3d4e5f6g7 - truly random-looking sequences
        re.compile(r"^(?=.*[a-z])(?=.*\d)(?=(?:.*\d){6,})[a-z\d]{12,}$", re.IGNORECASE),
    ]

    # ==========================================================================
    # Crypto Terms Detection
    # ==========================================================================
    # Terms in bio that suggest crypto/trading focus (may indicate spam account)

    CRYPTO_TERMS: frozenset[str] = frozenset(
        {
            # Cryptocurrencies
            "btc",
            "bitcoin",
            "eth",
            "ethereum",
            "usdt",
            "bnb",
            "sol",
            "solana",
            "xrp",
            "doge",
            "shib",
            "ada",
            "cardano",
            "avax",
            "matic",
            "ltc",
            # Crypto concepts
            "crypto",
            "defi",
            "nft",
            "token",
            "airdrop",
            "staking",
            "hodl",
            "blockchain",
            "web3",
            "dao",
            "yield",
            # Trading/Investment
            "trading",
            "trader",
            "invest",
            "investor",
            "profit",
            "forex",
            "signal",
            "portfolio",
            "roi",
            # Exchanges/Wallets
            "binance",
            "coinbase",
            "kraken",
            "metamask",
            "trustwallet",
            "wallet",
            "exchange",
            # Russian equivalents
            "крипто",
            "биткоин",
            "эфир",
            "трейдинг",
            "инвест",
        }
    )

    # ==========================================================================
    # URL Detection Pattern
    # ==========================================================================
    # Pattern to detect URLs in bio text

    URL_PATTERN: re.Pattern[str] = re.compile(
        r"https?://[^\s]+|"  # Full URLs
        r"www\.[^\s]+|"  # www. prefixed
        r"t\.me/[^\s]+|"  # Telegram links
        r"\w+\.(com|ru|org|net|io|me|cc|xyz|link|top)[/\s]?",  # Domain patterns
        re.IGNORECASE,
    )

    # ==========================================================================
    # Emoji Detection
    # ==========================================================================
    # Comprehensive emoji pattern for counting
    # Note: Handles variation selectors (U+FE0F) that follow some emojis

    EMOJI_PATTERN: re.Pattern[str] = re.compile(
        "(?:"
        "["
        "\U0001f600-\U0001f64f"  # Emoticons
        "\U0001f300-\U0001f5ff"  # Symbols & Pictographs
        "\U0001f680-\U0001f6ff"  # Transport & Map Symbols
        "\U0001f700-\U0001f77f"  # Alchemical Symbols
        "\U0001f780-\U0001f7ff"  # Geometric Shapes Extended
        "\U0001f800-\U0001f8ff"  # Supplemental Arrows-C
        "\U0001f900-\U0001f9ff"  # Supplemental Symbols and Pictographs
        "\U0001fa00-\U0001fa6f"  # Chess Symbols
        "\U0001fa70-\U0001faff"  # Symbols and Pictographs Extended-A
        "\U00002702-\U000027b0"  # Dingbats
        "\U000024c2-\U0001f251"  # Enclosed Characters
        "\U0001f1e0-\U0001f1ff"  # Flags
        "\U00002600-\U000026ff"  # Miscellaneous Symbols (includes hearts, stars)
        "\U00002700-\U000027bf"  # Dingbats extended
        "]"
        "\ufe0f?"  # Optional variation selector-16 (emoji presentation)
        ")"
    )

    # ==========================================================================
    # Scam Emoji Clusters
    # ==========================================================================
    # Specific emoji combinations commonly used in scam profiles
    # 2+ emojis from the SAME cluster = scam signal
    # Single emoji or unrelated emojis = NORMAL, no penalty

    SCAM_EMOJI_CLUSTERS: list[frozenset[str]] = [
        # Crypto pump / money scheme emojis
        frozenset({"💰", "🚀", "📈", "💵", "💸", "🤑", "💲"}),
        # Fake giveaway / prize emojis
        frozenset({"🎁", "🎉", "🏆", "🎊", "🥇", "🎯", "✨"}),
        # Urgency / warning emojis
        frozenset({"⚠️", "🔴", "❗", "‼️", "❌", "🚨", "⛔"}),
        # Fake verification / trust emojis
        frozenset({"✅", "💯", "🔒", "✔️", "🛡️", "👍", "🔐"}),
        # Fire / hot deal emojis
        frozenset({"🔥", "💥", "⚡", "💎", "🌟", "⭐", "★"}),
    ]

    # ==========================================================================
    # Account Age Estimation (from User ID)
    # ==========================================================================
    # Telegram user IDs are sequential. These thresholds estimate account age
    # based on ID ranges. Note: This is a heuristic approximation.

    USER_ID_AGE_THRESHOLDS: list[tuple[int, int]] = [
        # (max_user_id, estimated_age_days)
        (100_000_000, 3650),  # ~10 years (very old accounts)
        (500_000_000, 2555),  # ~7 years
        (1_000_000_000, 1825),  # ~5 years
        (2_000_000_000, 1095),  # ~3 years
        (3_500_000_000, 730),  # ~2 years
        (5_000_000_000, 365),  # ~1 year
        (6_000_000_000, 180),  # ~6 months
        (6_500_000_000, 90),  # ~3 months
        (7_000_000_000, 30),  # ~1 month
        (7_500_000_000, 14),  # ~2 weeks
    ]

    # Default age for IDs beyond the last threshold
    DEFAULT_NEW_ACCOUNT_DAYS: int = 7

    def __init__(self) -> None:
        """
        Initialize ProfileAnalyzer.

        The analyzer is stateless and uses only compiled patterns
        defined as class attributes.
        """
        pass

    async def analyze(self, context: MessageContext) -> ProfileSignals:
        """
        Analyze user profile and extract all signals.

        This is the main entry point for profile analysis. It extracts
        signals from the MessageContext and returns a ProfileSignals
        dataclass with all detected signals populated.

        Args:
            context: MessageContext containing user data and message metadata.
                     Relevant fields: username, first_name, last_name,
                     is_bot, is_premium, raw_user

        Returns:
            ProfileSignals dataclass with all extracted signals:
                - Trust signals (negative impact on risk score)
                - Risk signals (positive impact on risk score)

        Note:
            This method is async for interface consistency with other
            analyzers but performs no I/O operations. All analysis
            is done in-memory in <10ms.
        """
        # Extract user data from context
        username = context.username or ""
        first_name = context.first_name or ""
        last_name = context.last_name or ""
        is_bot = context.is_bot
        is_premium = context.is_premium

        # Get additional data from raw_user dict if available
        raw_user = context.raw_user or {}
        bio = raw_user.get("bio", "") or ""
        user_id = raw_user.get("id", 0) or context.user_id
        has_photo = bool(raw_user.get("photo"))

        # Also check for photo in other possible locations
        if not has_photo:
            has_photo = bool(raw_user.get("has_profile_photo", False))

        # Calculate account age from user ID (heuristic)
        account_age_days = self._estimate_account_age(user_id)

        # Analyze username for random/auto-generated patterns
        has_username = bool(username)
        username_has_random_chars = self._check_random_username(username)

        # Analyze bio content
        has_bio = bool(bio.strip())
        bio_has_links = self._check_bio_links(bio)
        bio_has_crypto_terms = self._check_crypto_terms(bio)

        # Analyze name for emoji spam (scam clusters)
        full_name = f"{first_name} {last_name}".strip()
        name_has_emoji_spam = self._check_emoji_spam(full_name)

        # Check name components exist
        has_first_name = bool(first_name.strip())
        has_last_name = bool(last_name.strip())

        return ProfileSignals(
            account_age_days=account_age_days,
            has_username=has_username,
            has_profile_photo=has_photo,
            has_bio=has_bio,
            has_first_name=has_first_name,
            has_last_name=has_last_name,
            is_premium=is_premium,
            is_bot=is_bot,
            username_has_random_chars=username_has_random_chars,
            bio_has_links=bio_has_links,
            bio_has_crypto_terms=bio_has_crypto_terms,
            name_has_emoji_spam=name_has_emoji_spam,
        )

    def _estimate_account_age(self, user_id: int) -> int:
        """
        Estimate account age from Telegram user ID.

        Telegram user IDs are assigned sequentially, so newer accounts
        have higher IDs. This method uses known ID thresholds to
        estimate approximate account age.

        Args:
            user_id: Telegram user ID (positive integer).

        Returns:
            Estimated account age in days.

        Note:
            This is a heuristic approximation. For accurate account age,
            use Telegram's getChatMember API when available.
        """
        if user_id <= 0:
            return 0

        for max_id, age_days in self.USER_ID_AGE_THRESHOLDS:
            if user_id < max_id:
                return age_days

        # Very new account (ID beyond all thresholds)
        return self.DEFAULT_NEW_ACCOUNT_DAYS

    def _check_random_username(self, username: str) -> bool:
        """
        Check if username appears to be randomly generated.

        Detects patterns like:
        - user123456 (Telegram default pattern)
        - abc12345678 (letters + many numbers)
        - a1b2c3d4e5 (alternating pattern)
        - hexadecimal strings
        - Very long random letter sequences

        Args:
            username: Telegram username (without @ prefix).

        Returns:
            True if username matches a known random pattern.
        """
        if not username:
            return False

        # Strip @ if present
        username = username.lstrip("@")

        # Check against all random patterns
        for pattern in self.RANDOM_USERNAME_PATTERNS:
            if pattern.match(username):
                return True

        # Additional check: high digit ratio (>60% digits suggests auto-generated)
        if len(username) >= 8:
            digit_count = sum(1 for c in username if c.isdigit())
            if digit_count / len(username) > 0.6:
                return True

        return False

    def _check_bio_links(self, bio: str) -> bool:
        """
        Check if bio contains links.

        Detects:
        - Full URLs (http://, https://)
        - www. prefixed URLs
        - t.me/ Telegram links
        - Bare domain patterns (example.com)

        Args:
            bio: User bio text.

        Returns:
            True if bio contains any links.
        """
        if not bio:
            return False

        return bool(self.URL_PATTERN.search(bio))

    def _check_crypto_terms(self, bio: str) -> bool:
        """
        Check if bio contains crypto-related terms.

        Matches against a comprehensive list of:
        - Cryptocurrency names (BTC, ETH, etc.)
        - Trading/investment terms
        - DeFi/NFT vocabulary
        - Exchange and wallet names
        - Russian equivalents

        Args:
            bio: User bio text.

        Returns:
            True if bio contains crypto terms.
        """
        if not bio:
            return False

        # Normalize to lowercase for matching
        bio_lower = bio.lower()

        # Check each term with word boundary awareness
        for term in self.CRYPTO_TERMS:
            # For short terms (3 chars or less), require word boundaries
            if len(term) <= 3:
                # Use regex word boundary for short terms
                if re.search(rf"\b{re.escape(term)}\b", bio_lower):
                    return True
            else:
                # For longer terms, simple substring match is sufficient
                if term in bio_lower:
                    return True

        return False

    def _check_emoji_spam(self, name: str) -> bool:
        """
        Check if name contains scam emoji clusters.

        This method detects SCAM patterns, not all emoji use.
        A single emoji or unrelated emojis are NORMAL and do not
        trigger this signal.

        Scam detection criteria:
        - 3+ total emojis in name (excessive emoji use)
        - OR 2+ emojis from the SAME scam cluster

        Args:
            name: User's full name (first_name + last_name).

        Returns:
            True if name has scam emoji pattern.
        """
        if not name:
            return False

        # Extract all emojis from name
        emojis = self.EMOJI_PATTERN.findall(name)

        if not emojis:
            return False

        # Normalize emojis by removing variation selector (U+FE0F) for comparison
        # This ensures "❤️" (with selector) matches "❤" (without)
        normalized_emojis = [e.rstrip("\ufe0f") for e in emojis]
        emoji_set = set(normalized_emojis)
        total_emoji_count = len(emojis)

        # Check 1: Excessive emoji count (3+ is suspicious in a name)
        if total_emoji_count >= 3:
            return True

        # Check 2: Scam cluster detection (2+ from same cluster)
        for cluster in self.SCAM_EMOJI_CLUSTERS:
            # Normalize cluster emojis for comparison
            normalized_cluster = {e.rstrip("\ufe0f") for e in cluster}
            cluster_matches = emoji_set & normalized_cluster
            if len(cluster_matches) >= 2:
                return True

        return False


def get_account_age_tier_signal(account_age_days: int) -> tuple[str | None, int]:
    """
    Get tiered account age signal and weight.

    This function implements tiered scoring for account age:
    - Very new accounts (<7 days): HIGH risk signal
    - New accounts (<30 days): MODERATE risk signal
    - Established accounts (1+ years): TRUST signals (negative weight)

    Args:
        account_age_days: Account age in days.

    Returns:
        Tuple of (signal_name, weight) or (None, 0) if no signal applies.

    Example:
        >>> signal, weight = get_account_age_tier_signal(5)
        >>> print(signal, weight)  # "account_under_7_days", 15
        >>> signal, weight = get_account_age_tier_signal(1100)
        >>> print(signal, weight)  # "account_age_3_years", -15
    """
    if account_age_days < 7:
        return ("account_under_7_days", 15)
    elif account_age_days < 30:
        return ("account_under_30_days", 8)
    elif account_age_days >= 365 * 3:
        return ("account_age_3_years", -15)
    elif account_age_days >= 365 * 2:
        return ("account_age_2_years", -10)
    elif account_age_days >= 365:
        return ("account_age_1_year", -5)
    else:
        # 30 days to 1 year: no special signal
        return (None, 0)
