"""
Tests for ContentAnalyzer

Tests content analysis including URL extraction, pattern matching, and spam detection.
"""

import pytest

from saqshy.analyzers.content import ContentAnalyzer
from saqshy.core.types import GroupType, MessageContext


class TestContentAnalyzer:
    """Test suite for ContentAnalyzer."""

    @pytest.fixture
    def analyzer(self) -> ContentAnalyzer:
        """Create ContentAnalyzer instance."""
        return ContentAnalyzer()

    async def test_empty_text(self, analyzer: ContentAnalyzer):
        """Empty text should return default signals."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text=None,
        )

        signals = await analyzer.analyze(context)

        assert signals.text_length == 0
        assert signals.word_count == 0
        assert signals.url_count == 0

    async def test_url_extraction(self, analyzer: ContentAnalyzer):
        """Test URL extraction from text."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Check out https://example.com and www.test.org for more info",
        )

        signals = await analyzer.analyze(context)

        assert signals.url_count >= 2

    async def test_shortened_url_detection(self, analyzer: ContentAnalyzer):
        """Test detection of URL shorteners."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Click here: https://bit.ly/abc123",
        )

        signals = await analyzer.analyze(context)

        assert signals.has_shortened_urls is True

    async def test_whitelisted_domains(self, analyzer: ContentAnalyzer):
        """Test whitelisted domain detection."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Here's the source: https://github.com/user/repo",
        )

        signals = await analyzer.analyze(context)

        assert signals.has_whitelisted_urls is True

    async def test_suspicious_tld(self, analyzer: ContentAnalyzer):
        """Test suspicious TLD detection."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Visit https://free-money.xyz for prizes",
        )

        signals = await analyzer.analyze(context)

        assert signals.has_suspicious_tld is True

    async def test_crypto_scam_phrases(self, analyzer: ContentAnalyzer):
        """Test crypto scam phrase detection."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Double your Bitcoin now! Guaranteed profit 100x return!",
        )

        signals = await analyzer.analyze(context)

        assert signals.has_crypto_scam_phrases is True

    async def test_clean_crypto_discussion(self, analyzer: ContentAnalyzer):
        """Normal crypto discussion should not trigger scam phrases."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Bitcoin price is up today. ETH looking good too.",
        )

        signals = await analyzer.analyze(context)

        assert signals.has_crypto_scam_phrases is False

    async def test_wallet_address_detection(self, analyzer: ContentAnalyzer):
        """Test crypto wallet address detection."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Send to: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        )

        signals = await analyzer.analyze(context)

        assert signals.has_wallet_addresses is True

    async def test_ethereum_address_detection(self, analyzer: ContentAnalyzer):
        """Test Ethereum address detection."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="My ETH wallet: 0x742d35Cc6634C0532925a3b844Bc9e7595f8bE8A",
        )

        signals = await analyzer.analyze(context)

        assert signals.has_wallet_addresses is True

    async def test_phone_number_detection(self, analyzer: ContentAnalyzer):
        """Test phone number detection."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Contact me at +7 (999) 123-45-67",
        )

        signals = await analyzer.analyze(context)

        assert signals.has_phone_numbers is True

    async def test_caps_ratio_calculation(self, analyzer: ContentAnalyzer):
        """Test caps ratio calculation."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="THIS IS ALL CAPS MESSAGE",
        )

        signals = await analyzer.analyze(context)

        assert signals.caps_ratio > 0.9

    async def test_emoji_counting(self, analyzer: ContentAnalyzer):
        """Test emoji counting."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Great news! \U0001f389\U0001f680\U0001f4b0 Big things coming!",
        )

        signals = await analyzer.analyze(context)

        assert signals.emoji_count >= 3

    async def test_forward_detection(self, analyzer: ContentAnalyzer):
        """Test forward detection."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Forwarded message",
            is_forward=True,
            forward_from_chat_id=-200,
            raw_message={"forward_from_chat": {"type": "channel", "id": -200}},
        )

        signals = await analyzer.analyze(context)

        assert signals.has_forward is True
        assert signals.forward_from_channel is True

    async def test_money_pattern_detection(self, analyzer: ContentAnalyzer):
        """Test money pattern detection."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Earn $1000 per day with this simple trick!",
        )

        signals = await analyzer.analyze(context)

        assert signals.has_money_patterns is True

    async def test_urgency_pattern_detection(self, analyzer: ContentAnalyzer):
        """Test urgency pattern detection."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Limited time offer! Act now or miss out!",
        )

        signals = await analyzer.analyze(context)

        assert signals.has_urgency_patterns is True


class TestContentAnalyzerGroupTypes:
    """Test ContentAnalyzer with different group types."""

    async def test_deals_group_shortener_tolerance(self):
        """Deals groups should allow certain shorteners."""
        analyzer = ContentAnalyzer()

        # Test with deals group type
        deals_context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Hot deal: https://clck.ru/abc123",
            group_type=GroupType.DEALS,
        )
        general_context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="Hot deal: https://clck.ru/abc123",
            group_type=GroupType.GENERAL,
        )

        deals_signals = await analyzer.analyze(deals_context)
        general_signals = await analyzer.analyze(general_context)

        # clck.ru is allowed in deals groups but flagged in general
        # Both should detect the URL, but deals should NOT flag it as shortened
        assert deals_signals.url_count >= 1
        assert general_signals.url_count >= 1
        # clck.ru is in ALLOWED_SHORTENERS for deals
        assert deals_signals.has_shortened_urls is False
        assert general_signals.has_shortened_urls is True

    async def test_tech_group_whitelists(self):
        """Tech groups should have extended whitelists."""
        analyzer = ContentAnalyzer()

        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="See docs at https://docs.python.org/3/library/",
            group_type=GroupType.TECH,
        )

        signals = await analyzer.analyze(context)

        assert signals.has_whitelisted_urls is True


class TestURLExtraction:
    """Detailed tests for URL extraction."""

    @pytest.fixture
    def analyzer(self) -> ContentAnalyzer:
        return ContentAnalyzer()

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com",
            "http://example.com",
            "https://example.com/path",
            "https://example.com/path?query=value",
            "www.example.com",
            "example.com",
            "sub.example.com",
            "https://example.com:8080/path",
        ],
    )
    async def test_url_formats(self, analyzer: ContentAnalyzer, url: str):
        """Test various URL formats are detected."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text=f"Check this: {url}",
        )

        signals = await analyzer.analyze(context)

        assert signals.url_count >= 1

    async def test_multiple_urls(self, analyzer: ContentAnalyzer):
        """Test multiple URLs in same message."""
        context = MessageContext(
            message_id=1,
            chat_id=-100,
            user_id=1,
            text="""
            Link 1: https://example.com
            Link 2: https://test.org
            Link 3: www.another.net
            """,
        )

        signals = await analyzer.analyze(context)

        assert signals.url_count >= 3
        assert signals.unique_domains >= 3
