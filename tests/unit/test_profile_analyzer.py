"""
Unit tests for ProfileAnalyzer.

Tests cover:
- Account age estimation and tier boundaries
- Username pattern detection (random/auto-generated)
- Bio analysis (links, crypto terms)
- Name emoji spam detection (scam clusters)
- Edge cases (empty values, missing data)
- Multilingual content
"""

import pytest

from saqshy.analyzers.profile import ProfileAnalyzer, get_account_age_tier_signal
from saqshy.core.types import MessageContext


@pytest.fixture
def analyzer() -> ProfileAnalyzer:
    """Create ProfileAnalyzer instance for testing."""
    return ProfileAnalyzer()


def create_context(
    user_id: int = 1000000000,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
    is_bot: bool = False,
    is_premium: bool = False,
    bio: str | None = None,
    has_photo: bool = False,
) -> MessageContext:
    """Helper to create MessageContext with user data."""
    raw_user = {
        "id": user_id,
        "bio": bio,
    }
    if has_photo:
        raw_user["photo"] = {"small_file_id": "test123"}

    return MessageContext(
        message_id=1,
        chat_id=12345,
        user_id=user_id,
        text="Test message",
        username=username,
        first_name=first_name,
        last_name=last_name,
        is_bot=is_bot,
        is_premium=is_premium,
        raw_user=raw_user,
    )


# =============================================================================
# Account Age Estimation Tests
# =============================================================================


class TestAccountAgeEstimation:
    """Tests for account age estimation from user ID."""

    @pytest.mark.asyncio
    async def test_very_old_account(self, analyzer: ProfileAnalyzer) -> None:
        """User ID < 100M should estimate ~10 years old."""
        context = create_context(user_id=50_000_000)
        signals = await analyzer.analyze(context)
        assert signals.account_age_days == 3650

    @pytest.mark.asyncio
    async def test_old_account(self, analyzer: ProfileAnalyzer) -> None:
        """User ID 500M-1B should estimate ~5 years old."""
        context = create_context(user_id=800_000_000)
        signals = await analyzer.analyze(context)
        assert signals.account_age_days == 1825

    @pytest.mark.asyncio
    async def test_established_account(self, analyzer: ProfileAnalyzer) -> None:
        """User ID 2B-3.5B should estimate ~2 years old."""
        context = create_context(user_id=2_500_000_000)
        signals = await analyzer.analyze(context)
        assert signals.account_age_days == 730

    @pytest.mark.asyncio
    async def test_new_account(self, analyzer: ProfileAnalyzer) -> None:
        """User ID 7B-7.5B should estimate ~2 weeks old."""
        context = create_context(user_id=7_200_000_000)
        signals = await analyzer.analyze(context)
        assert signals.account_age_days == 14

    @pytest.mark.asyncio
    async def test_very_new_account(self, analyzer: ProfileAnalyzer) -> None:
        """User ID > 7.5B should estimate ~7 days old."""
        context = create_context(user_id=8_000_000_000)
        signals = await analyzer.analyze(context)
        assert signals.account_age_days == 7

    @pytest.mark.asyncio
    async def test_zero_user_id(self, analyzer: ProfileAnalyzer) -> None:
        """User ID 0 should return 0 days."""
        context = create_context(user_id=0)
        signals = await analyzer.analyze(context)
        assert signals.account_age_days == 0

    @pytest.mark.asyncio
    async def test_negative_user_id(self, analyzer: ProfileAnalyzer) -> None:
        """Negative user ID should return 0 days."""
        context = create_context(user_id=-100)
        signals = await analyzer.analyze(context)
        assert signals.account_age_days == 0


# =============================================================================
# Account Age Tier Signal Tests
# =============================================================================


class TestAccountAgeTierSignal:
    """Tests for tiered account age signal function."""

    def test_under_7_days_risk_signal(self) -> None:
        """Accounts under 7 days should get +15 risk."""
        # Test boundaries: 0, 1, 6
        for days in [0, 1, 6]:
            signal, weight = get_account_age_tier_signal(days)
            assert signal == "account_under_7_days"
            assert weight == 15

    def test_boundary_day_7(self) -> None:
        """Day 7 should transition to under_30_days tier."""
        signal, weight = get_account_age_tier_signal(7)
        assert signal == "account_under_30_days"
        assert weight == 8

    def test_under_30_days_risk_signal(self) -> None:
        """Accounts 7-29 days should get +8 risk."""
        for days in [7, 15, 29]:
            signal, weight = get_account_age_tier_signal(days)
            assert signal == "account_under_30_days"
            assert weight == 8

    def test_boundary_day_30(self) -> None:
        """Day 30 should have no signal (neutral zone)."""
        signal, weight = get_account_age_tier_signal(30)
        assert signal is None
        assert weight == 0

    def test_neutral_zone_no_signal(self) -> None:
        """Accounts 30-364 days should have no signal."""
        for days in [30, 100, 200, 364]:
            signal, weight = get_account_age_tier_signal(days)
            assert signal is None
            assert weight == 0

    def test_boundary_day_365(self) -> None:
        """Day 365 should transition to 1-year trust tier."""
        signal, weight = get_account_age_tier_signal(365)
        assert signal == "account_age_1_year"
        assert weight == -5

    def test_1_year_trust_signal(self) -> None:
        """Accounts 1-2 years should get -5 trust."""
        for days in [365, 500, 729]:
            signal, weight = get_account_age_tier_signal(days)
            assert signal == "account_age_1_year"
            assert weight == -5

    def test_boundary_day_730(self) -> None:
        """Day 730 (2 years) should transition to 2-year trust tier."""
        signal, weight = get_account_age_tier_signal(730)
        assert signal == "account_age_2_years"
        assert weight == -10

    def test_2_years_trust_signal(self) -> None:
        """Accounts 2-3 years should get -10 trust."""
        for days in [730, 900, 1094]:
            signal, weight = get_account_age_tier_signal(days)
            assert signal == "account_age_2_years"
            assert weight == -10

    def test_boundary_day_1095(self) -> None:
        """Day 1095 (3 years) should transition to 3-year trust tier."""
        signal, weight = get_account_age_tier_signal(1095)
        assert signal == "account_age_3_years"
        assert weight == -15

    def test_3_years_trust_signal(self) -> None:
        """Accounts 3+ years should get -15 trust (maximum)."""
        for days in [1095, 2000, 5000]:
            signal, weight = get_account_age_tier_signal(days)
            assert signal == "account_age_3_years"
            assert weight == -15


# =============================================================================
# Username Analysis Tests
# =============================================================================


class TestUsernameAnalysis:
    """Tests for random username detection."""

    @pytest.mark.asyncio
    async def test_normal_username(self, analyzer: ProfileAnalyzer) -> None:
        """Normal usernames should not be flagged."""
        normal_usernames = [
            "john_doe",
            "alice123",  # Short suffix is normal
            "developer",
            "cool_guy_99",
            "anna_k",
            "maxim_dev",
            "python_dev_42",  # Normal pattern
            "crypto_trader",  # Words with underscore
        ]
        for username in normal_usernames:
            context = create_context(username=username)
            signals = await analyzer.analyze(context)
            assert signals.has_username is True
            assert signals.username_has_random_chars is False, f"False positive: {username}"

    @pytest.mark.asyncio
    async def test_user_prefix_pattern(self, analyzer: ProfileAnalyzer) -> None:
        """user123456 patterns should be flagged."""
        random_usernames = [
            "user123456",
            "User1234567",
            "user_12345678",
            "USER99999999",
        ]
        for username in random_usernames:
            context = create_context(username=username)
            signals = await analyzer.analyze(context)
            assert signals.username_has_random_chars is True, f"Missed: {username}"

    @pytest.mark.asyncio
    async def test_letters_plus_numbers_pattern(self, analyzer: ProfileAnalyzer) -> None:
        """Letters followed by many numbers should be flagged."""
        random_usernames = [
            "john12345678",
            "ab123456789",
            "xyz1234567",
        ]
        for username in random_usernames:
            context = create_context(username=username)
            signals = await analyzer.analyze(context)
            assert signals.username_has_random_chars is True, f"Missed: {username}"

    @pytest.mark.asyncio
    async def test_hex_like_pattern(self, analyzer: ProfileAnalyzer) -> None:
        """Hex-like strings should be flagged."""
        random_usernames = [
            "deadbeef1234",  # 12-char hex-like
            "abcdef123456",  # 12-char hex-like
            "a1b2c3d4e5f6",  # Mixed with high digit ratio
        ]
        for username in random_usernames:
            context = create_context(username=username)
            signals = await analyzer.analyze(context)
            assert signals.username_has_random_chars is True, f"Missed: {username}"

    @pytest.mark.asyncio
    async def test_high_digit_ratio(self, analyzer: ProfileAnalyzer) -> None:
        """Usernames with >60% digits should be flagged."""
        context = create_context(username="a12345678")  # 8/9 = 88% digits
        signals = await analyzer.analyze(context)
        assert signals.username_has_random_chars is True

    @pytest.mark.asyncio
    async def test_empty_username(self, analyzer: ProfileAnalyzer) -> None:
        """Empty/missing username should not crash."""
        context = create_context(username=None)
        signals = await analyzer.analyze(context)
        assert signals.has_username is False
        assert signals.username_has_random_chars is False

    @pytest.mark.asyncio
    async def test_username_with_at_prefix(self, analyzer: ProfileAnalyzer) -> None:
        """@ prefix should be stripped before analysis."""
        context = create_context(username="@user123456")
        signals = await analyzer.analyze(context)
        assert signals.username_has_random_chars is True


# =============================================================================
# Bio Analysis Tests
# =============================================================================


class TestBioAnalysis:
    """Tests for bio link and crypto term detection."""

    @pytest.mark.asyncio
    async def test_bio_with_http_link(self, analyzer: ProfileAnalyzer) -> None:
        """HTTP links in bio should be detected."""
        context = create_context(bio="Check out https://example.com")
        signals = await analyzer.analyze(context)
        assert signals.bio_has_links is True

    @pytest.mark.asyncio
    async def test_bio_with_www_link(self, analyzer: ProfileAnalyzer) -> None:
        """www links in bio should be detected."""
        context = create_context(bio="Visit www.example.com for more")
        signals = await analyzer.analyze(context)
        assert signals.bio_has_links is True

    @pytest.mark.asyncio
    async def test_bio_with_telegram_link(self, analyzer: ProfileAnalyzer) -> None:
        """t.me links in bio should be detected."""
        context = create_context(bio="Join t.me/mygroup")
        signals = await analyzer.analyze(context)
        assert signals.bio_has_links is True

    @pytest.mark.asyncio
    async def test_bio_with_domain(self, analyzer: ProfileAnalyzer) -> None:
        """Bare domains in bio should be detected."""
        context = create_context(bio="Visit mysite.com")
        signals = await analyzer.analyze(context)
        assert signals.bio_has_links is True

    @pytest.mark.asyncio
    async def test_bio_without_links(self, analyzer: ProfileAnalyzer) -> None:
        """Bio without links should not flag."""
        context = create_context(bio="I love programming and cats")
        signals = await analyzer.analyze(context)
        assert signals.bio_has_links is False

    @pytest.mark.asyncio
    async def test_bio_with_crypto_terms(self, analyzer: ProfileAnalyzer) -> None:
        """Crypto terms in bio should be detected."""
        crypto_bios = [
            "Bitcoin trader",
            "BTC maximalist",
            "DeFi enthusiast",
            "NFT collector",
            "Crypto investor",
            "ETH holder",
        ]
        for bio in crypto_bios:
            context = create_context(bio=bio)
            signals = await analyzer.analyze(context)
            assert signals.bio_has_crypto_terms is True, f"Missed: {bio}"

    @pytest.mark.asyncio
    async def test_bio_with_russian_crypto_terms(self, analyzer: ProfileAnalyzer) -> None:
        """Russian crypto terms should be detected."""
        context = create_context(bio="Криптотрейдер из Москвы")
        signals = await analyzer.analyze(context)
        assert signals.bio_has_crypto_terms is True

    @pytest.mark.asyncio
    async def test_bio_without_crypto_terms(self, analyzer: ProfileAnalyzer) -> None:
        """Normal bio should not flag crypto terms."""
        context = create_context(bio="Software developer from Berlin")
        signals = await analyzer.analyze(context)
        assert signals.bio_has_crypto_terms is False

    @pytest.mark.asyncio
    async def test_empty_bio(self, analyzer: ProfileAnalyzer) -> None:
        """Empty bio should not crash."""
        context = create_context(bio="")
        signals = await analyzer.analyze(context)
        assert signals.has_bio is False
        assert signals.bio_has_links is False
        assert signals.bio_has_crypto_terms is False

    @pytest.mark.asyncio
    async def test_short_crypto_term_boundary(self, analyzer: ProfileAnalyzer) -> None:
        """Short terms like 'btc' should require word boundaries."""
        # Should match: "BTC" as standalone word
        context = create_context(bio="I hold BTC")
        signals = await analyzer.analyze(context)
        assert signals.bio_has_crypto_terms is True

        # Should NOT match "btc" inside another word
        context = create_context(bio="I use abstract classes")
        signals = await analyzer.analyze(context)
        assert signals.bio_has_crypto_terms is False


# =============================================================================
# Emoji Spam Tests
# =============================================================================


class TestEmojiSpamDetection:
    """Tests for scam emoji cluster detection in names."""

    @pytest.mark.asyncio
    async def test_single_emoji_not_flagged(self, analyzer: ProfileAnalyzer) -> None:
        """Single emoji should NOT be flagged (normal usage)."""
        names = [
            "John 🙂",
            "Anna ❤️",
            "Max 👍",
        ]
        for name in names:
            context = create_context(first_name=name)
            signals = await analyzer.analyze(context)
            assert signals.name_has_emoji_spam is False, f"False positive: {name}"

    @pytest.mark.asyncio
    async def test_two_unrelated_emojis_not_flagged(self, analyzer: ProfileAnalyzer) -> None:
        """Two unrelated emojis should NOT be flagged."""
        context = create_context(first_name="John 🙂 ❤️")
        signals = await analyzer.analyze(context)
        assert signals.name_has_emoji_spam is False

    @pytest.mark.asyncio
    async def test_three_emojis_flagged(self, analyzer: ProfileAnalyzer) -> None:
        """3+ emojis should be flagged as excessive."""
        context = create_context(first_name="John 🙂 ❤️ 👋")
        signals = await analyzer.analyze(context)
        assert signals.name_has_emoji_spam is True

    @pytest.mark.asyncio
    async def test_crypto_pump_cluster(self, analyzer: ProfileAnalyzer) -> None:
        """Crypto pump emoji cluster should be flagged."""
        names = [
            "John 💰🚀",  # money + rocket
            "Anna 💵📈",  # money + chart
            "Max 💸🤑",  # money emojis
        ]
        for name in names:
            context = create_context(first_name=name)
            signals = await analyzer.analyze(context)
            assert signals.name_has_emoji_spam is True, f"Missed: {name}"

    @pytest.mark.asyncio
    async def test_fake_giveaway_cluster(self, analyzer: ProfileAnalyzer) -> None:
        """Fake giveaway emoji cluster should be flagged."""
        names = [
            "John 🎁🎉",  # gift + party
            "Anna 🏆🥇",  # trophy + medal
        ]
        for name in names:
            context = create_context(first_name=name)
            signals = await analyzer.analyze(context)
            assert signals.name_has_emoji_spam is True, f"Missed: {name}"

    @pytest.mark.asyncio
    async def test_urgency_cluster(self, analyzer: ProfileAnalyzer) -> None:
        """Urgency emoji cluster should be flagged."""
        names = [
            "John ⚠️❗",  # warning + exclamation
            "Anna 🔴🚨",  # red + siren
        ]
        for name in names:
            context = create_context(first_name=name)
            signals = await analyzer.analyze(context)
            assert signals.name_has_emoji_spam is True, f"Missed: {name}"

    @pytest.mark.asyncio
    async def test_verification_cluster(self, analyzer: ProfileAnalyzer) -> None:
        """Fake verification emoji cluster should be flagged."""
        names = [
            "John ✅💯",  # check + 100
            "Admin 🔒✔️",  # lock + check
        ]
        for name in names:
            context = create_context(first_name=name)
            signals = await analyzer.analyze(context)
            assert signals.name_has_emoji_spam is True, f"Missed: {name}"

    @pytest.mark.asyncio
    async def test_fire_cluster(self, analyzer: ProfileAnalyzer) -> None:
        """Fire/hot deal emoji cluster should be flagged."""
        names = [
            "John 🔥💎",  # fire + diamond
            "Anna ⚡🌟",  # lightning + star
        ]
        for name in names:
            context = create_context(first_name=name)
            signals = await analyzer.analyze(context)
            assert signals.name_has_emoji_spam is True, f"Missed: {name}"

    @pytest.mark.asyncio
    async def test_empty_name(self, analyzer: ProfileAnalyzer) -> None:
        """Empty name should not crash."""
        context = create_context(first_name="", last_name="")
        signals = await analyzer.analyze(context)
        assert signals.name_has_emoji_spam is False

    @pytest.mark.asyncio
    async def test_full_name_concatenation(self, analyzer: ProfileAnalyzer) -> None:
        """Emojis across first and last name should be counted together."""
        # 2 emojis total (one in each name) from same cluster
        context = create_context(first_name="John 💰", last_name="Doe 🚀")
        signals = await analyzer.analyze(context)
        assert signals.name_has_emoji_spam is True


# =============================================================================
# Profile Completeness Tests
# =============================================================================


class TestProfileCompleteness:
    """Tests for profile field detection."""

    @pytest.mark.asyncio
    async def test_complete_profile(self, analyzer: ProfileAnalyzer) -> None:
        """Complete profile should have all fields detected."""
        context = create_context(
            username="john_doe",
            first_name="John",
            last_name="Doe",
            bio="Software developer",
            has_photo=True,
            is_premium=True,
        )
        signals = await analyzer.analyze(context)
        assert signals.has_username is True
        assert signals.has_first_name is True
        assert signals.has_last_name is True
        assert signals.has_bio is True
        assert signals.has_profile_photo is True
        assert signals.is_premium is True
        assert signals.is_bot is False

    @pytest.mark.asyncio
    async def test_minimal_profile(self, analyzer: ProfileAnalyzer) -> None:
        """Minimal profile should detect missing fields."""
        context = create_context(first_name="John")
        signals = await analyzer.analyze(context)
        assert signals.has_username is False
        assert signals.has_first_name is True
        assert signals.has_last_name is False
        assert signals.has_bio is False
        assert signals.has_profile_photo is False
        assert signals.is_premium is False

    @pytest.mark.asyncio
    async def test_bot_profile(self, analyzer: ProfileAnalyzer) -> None:
        """Bot accounts should be detected."""
        context = create_context(first_name="MyBot", is_bot=True)
        signals = await analyzer.analyze(context)
        assert signals.is_bot is True


# =============================================================================
# Edge Cases and Robustness Tests
# =============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_none_values(self, analyzer: ProfileAnalyzer) -> None:
        """None values should be handled gracefully."""
        context = MessageContext(
            message_id=1,
            chat_id=12345,
            user_id=1000000000,
            text=None,
            username=None,
            first_name=None,
            last_name=None,
            raw_user={},
        )
        signals = await analyzer.analyze(context)
        assert signals.has_username is False
        assert signals.has_first_name is False
        assert signals.has_last_name is False

    @pytest.mark.asyncio
    async def test_whitespace_only_values(self, analyzer: ProfileAnalyzer) -> None:
        """Whitespace-only values should be treated as empty."""
        context = create_context(
            first_name="   ",
            last_name="\t\n",
            bio="   ",
        )
        signals = await analyzer.analyze(context)
        assert signals.has_first_name is False
        assert signals.has_last_name is False
        assert signals.has_bio is False

    @pytest.mark.asyncio
    async def test_unicode_content(self, analyzer: ProfileAnalyzer) -> None:
        """Unicode content should be handled properly."""
        context = create_context(
            first_name="Алексей",
            last_name="Петров",
            bio="Программист из Москвы",
        )
        signals = await analyzer.analyze(context)
        assert signals.has_first_name is True
        assert signals.has_last_name is True
        assert signals.has_bio is True

    @pytest.mark.asyncio
    async def test_very_long_username(self, analyzer: ProfileAnalyzer) -> None:
        """Very long usernames should be processed."""
        context = create_context(username="a" * 100)
        signals = await analyzer.analyze(context)
        assert signals.has_username is True

    @pytest.mark.asyncio
    async def test_special_characters_in_bio(self, analyzer: ProfileAnalyzer) -> None:
        """Special characters in bio should not crash regex."""
        special_bio = "Test [brackets] (parens) {braces} $dollar @at #hash"
        context = create_context(bio=special_bio)
        signals = await analyzer.analyze(context)
        assert signals.has_bio is True

    @pytest.mark.asyncio
    async def test_empty_raw_user(self, analyzer: ProfileAnalyzer) -> None:
        """Empty raw_user dict should be handled."""
        context = MessageContext(
            message_id=1,
            chat_id=12345,
            user_id=1000000000,
            text="Test",
            username="test_user",
            first_name="Test",
            raw_user={},
        )
        signals = await analyzer.analyze(context)
        assert signals.has_username is True

    @pytest.mark.asyncio
    async def test_missing_raw_user(self, analyzer: ProfileAnalyzer) -> None:
        """Missing raw_user (None) should be handled."""
        context = MessageContext(
            message_id=1,
            chat_id=12345,
            user_id=1000000000,
            text="Test",
            username="test_user",
            first_name="Test",
            raw_user=None,  # type: ignore
        )
        # Should handle None raw_user gracefully
        signals = await analyzer.analyze(context)
        assert signals.has_username is True
