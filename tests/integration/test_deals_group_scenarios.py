"""
Integration Tests for Deals Group Scenarios (PRIORITY)

Deals groups have special handling:
- Higher thresholds (40/60/80/95) vs general (30/50/75/92)
- Links are NORMAL - valid retailer links should not trigger
- WHITELIST_DOMAINS_DEALS reduces score (amazon, ebay, walmart, etc.)
- ALLOWED_SHORTENERS (clck.ru, fas.st, amzn.to) are permitted
- Money patterns and urgency are normal in deals context
- Target: <5% false positive rate for legitimate deals

These tests ensure the system correctly handles deals/shopping group content.
"""

import pytest

from saqshy.core.constants import (
    ALLOWED_SHORTENERS,
    DEALS_WEIGHT_OVERRIDES,
    THRESHOLDS,
    WHITELIST_DOMAINS_DEALS,
)
from saqshy.core.risk_calculator import RiskCalculator
from saqshy.core.types import (
    BehaviorSignals,
    ContentSignals,
    GroupType,
    NetworkSignals,
    ProfileSignals,
    Signals,
    Verdict,
)
from tests.fixtures.scenarios import (
    BEHAVIOR_CHANNEL_SUBSCRIBER_LONG,
    BEHAVIOR_CHANNEL_SUBSCRIBER_NEW,
    BEHAVIOR_FIRST_MESSAGE_FAST,
    BEHAVIOR_NEUTRAL,
    CONTENT_CLEAN,
    CONTENT_CRYPTO_SCAM,
    CONTENT_DEALS_PROMO,
    NETWORK_CLEAN,
    NETWORK_SPAM_HIGH,
    SCENARIO_DEALS_AFFILIATE_LINK,
    SPAMMER_NEW_ACCOUNT,
    TRUSTED_REGULAR,
    TRUSTED_VETERAN,
)


class TestDealsGroupThresholds:
    """Test that deals groups have correct higher thresholds."""

    def test_deals_thresholds_are_higher(self):
        """Deals thresholds should be higher than general."""
        general_thresholds = THRESHOLDS[GroupType.GENERAL]
        deals_thresholds = THRESHOLDS[GroupType.DEALS]

        # All thresholds should be higher in deals
        assert deals_thresholds[0] > general_thresholds[0]  # WATCH
        assert deals_thresholds[1] > general_thresholds[1]  # LIMIT
        assert deals_thresholds[2] > general_thresholds[2]  # REVIEW
        assert deals_thresholds[3] > general_thresholds[3]  # BLOCK

    def test_deals_block_threshold_is_95(self):
        """Deals BLOCK threshold should be 95 (vs 92 for general)."""
        assert THRESHOLDS[GroupType.DEALS][3] == 95

    @pytest.mark.parametrize(
        "score,expected_verdict",
        [
            (0, Verdict.ALLOW),
            (39, Verdict.ALLOW),
            (40, Verdict.WATCH),
            (59, Verdict.WATCH),
            (60, Verdict.LIMIT),
            (79, Verdict.LIMIT),
            (80, Verdict.REVIEW),
            (94, Verdict.REVIEW),
            (95, Verdict.BLOCK),
            (100, Verdict.BLOCK),
        ],
    )
    def test_deals_verdict_mapping(self, score: int, expected_verdict: Verdict):
        """Verify correct verdict mapping for deals group."""
        calculator = RiskCalculator(group_type=GroupType.DEALS)
        verdict = calculator._score_to_verdict(score)
        assert verdict == expected_verdict


class TestDealsWeightOverrides:
    """Test that weight overrides are correctly applied in deals groups."""

    def test_url_penalty_reduced(self):
        """URL penalty should be reduced in deals groups."""
        # In DEALS: has_urls = 2 (vs 5 in general)
        assert DEALS_WEIGHT_OVERRIDES.get("has_urls", 5) == 2

    def test_multiple_urls_penalty_reduced(self):
        """Multiple URLs penalty should be reduced."""
        # In DEALS: multiple_urls_3_plus = 5 (vs 12 in general)
        assert DEALS_WEIGHT_OVERRIDES.get("multiple_urls_3_plus", 12) == 5

    def test_shortened_urls_penalty_reduced(self):
        """Shortened URLs penalty should be reduced."""
        # In DEALS: has_shortened_urls = 5 (vs 15 in general)
        assert DEALS_WEIGHT_OVERRIDES.get("has_shortened_urls", 15) == 5

    def test_money_pattern_penalty_reduced(self):
        """Money pattern penalty should be reduced."""
        # In DEALS: money_pattern = 3 (vs 12 in general)
        assert DEALS_WEIGHT_OVERRIDES.get("money_pattern", 12) == 3

    def test_urgency_pattern_penalty_reduced(self):
        """Urgency pattern penalty should be reduced."""
        # In DEALS: urgency_pattern = 3 (vs 10 in general)
        assert DEALS_WEIGHT_OVERRIDES.get("urgency_pattern", 10) == 3

    def test_crypto_scam_penalty_still_high(self):
        """Crypto scam penalty should remain high in deals."""
        # Crypto scam should NOT be reduced
        assert DEALS_WEIGHT_OVERRIDES.get("crypto_scam_phrase", 35) == 35


class TestDealsWhitelistedDomains:
    """Test whitelisted domains for deals groups."""

    @pytest.mark.parametrize(
        "domain",
        [
            "amazon.com",
            "amazon.co.uk",
            "ebay.com",
            "walmart.com",
            "target.com",
            "bestbuy.com",
            "newegg.com",
            "aliexpress.com",
            "ozon.ru",
            "wildberries.ru",
        ],
    )
    def test_retailer_domains_whitelisted(self, domain: str):
        """Major retailers should be in deals whitelist."""
        assert domain in WHITELIST_DOMAINS_DEALS

    @pytest.mark.parametrize(
        "shortener",
        [
            "clck.ru",
            "fas.st",
            "bit.ly",
            "t.co",
            "amzn.to",
        ],
    )
    def test_allowed_shorteners_exist(self, shortener: str):
        """Common affiliate shorteners should be allowed."""
        assert shortener in ALLOWED_SHORTENERS


class TestDealsLinkHandling:
    """Test that valid retailer links don't trigger false positives."""

    def test_amazon_link_in_deals_allowed(self):
        """Amazon link in deals group should not cause BLOCK."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                url_count=1,
                has_shortened_urls=False,
                has_whitelisted_urls=True,  # amazon.com is whitelisted
                has_money_patterns=True,  # "$29.99"
            ),
            behavior=BEHAVIOR_NEUTRAL.signals,
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.DEALS)
        result = calculator.calculate(signals)

        assert result.verdict == Verdict.ALLOW
        assert result.score < 40

    def test_multiple_retailer_links_allowed(self):
        """Multiple links to whitelisted retailers should be fine."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                url_count=3,  # amazon, walmart, target
                has_shortened_urls=False,
                has_whitelisted_urls=True,
                unique_domains=3,
                has_money_patterns=True,
            ),
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_NEW.signals,
            network=NETWORK_CLEAN.signals,
        )

        deals_calc = RiskCalculator(group_type=GroupType.DEALS)
        general_calc = RiskCalculator(group_type=GroupType.GENERAL)

        deals_result = deals_calc.calculate(signals)
        general_result = general_calc.calculate(signals)

        # Deals group should score <= general (content score should be lower)
        assert deals_result.content_score <= general_result.content_score
        assert deals_result.verdict in (Verdict.ALLOW, Verdict.WATCH)

    def test_affiliate_shortener_allowed_in_deals(self):
        """Affiliate shorteners (amzn.to, clck.ru) should be allowed in deals."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                url_count=2,
                has_shortened_urls=True,  # amzn.to, clck.ru
                has_whitelisted_urls=False,  # shortener, not direct domain
                has_money_patterns=True,
            ),
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_NEW.signals,
            network=NETWORK_CLEAN.signals,
        )

        deals_calc = RiskCalculator(group_type=GroupType.DEALS)
        general_calc = RiskCalculator(group_type=GroupType.GENERAL)

        deals_result = deals_calc.calculate(signals)
        general_result = general_calc.calculate(signals)

        # Deals should have reduced penalty for shorteners
        assert deals_result.content_score < general_result.content_score


class TestDealsFalsePositiveScenarios:
    """Test common false positive scenarios in deals groups."""

    def test_channel_subscriber_with_promo_link_in_deals_group(self):
        """CRITICAL: Channel subscriber posting Amazon link in deals group = ALLOW."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                url_count=1,
                has_shortened_urls=True,  # amzn.to
                has_whitelisted_urls=True,  # amazon
                has_money_patterns=True,  # "$199.99"
                has_urgency_patterns=True,  # "limited time"
                emoji_count=3,
            ),
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=14,
                previous_messages_approved=5,
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.DEALS)
        result = calculator.calculate(signals)

        assert result.verdict == Verdict.ALLOW, (
            f"Channel subscriber with Amazon deal should be ALLOW, got {result.verdict} "
            f"(score: {result.score})"
        )

    def test_affiliate_link_post_not_blocked(self):
        """Legitimate affiliate link post should not be blocked."""
        scenario = SCENARIO_DEALS_AFFILIATE_LINK
        calculator = RiskCalculator(group_type=scenario.group_type)
        result = calculator.calculate(scenario.signals)

        assert result.verdict != Verdict.BLOCK
        assert result.verdict in (Verdict.ALLOW, Verdict.WATCH)

    def test_deal_with_price_comparison(self):
        """Deal post with price comparison (multiple links, money) should be fine."""
        signals = Signals(
            profile=TRUSTED_VETERAN.signals,
            content=ContentSignals(
                text_length=300,
                word_count=50,
                url_count=4,  # Amazon, Walmart, BestBuy, Target
                has_shortened_urls=True,  # Some affiliate links
                has_whitelisted_urls=True,
                unique_domains=4,
                has_money_patterns=True,  # Multiple prices
                has_urgency_patterns=True,  # "Sale ends tonight!"
                emoji_count=5,
            ),
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_LONG.signals,
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.DEALS)
        result = calculator.calculate(signals)

        # With all trust signals, this should be ALLOW
        assert result.verdict == Verdict.ALLOW

    def test_new_user_first_deal_post(self):
        """New user's first deal post should not be harshly penalized."""
        signals = Signals(
            profile=ProfileSignals(
                account_age_days=30,
                has_username=True,
                has_profile_photo=True,
            ),
            content=ContentSignals(
                url_count=1,
                has_whitelisted_urls=True,  # amazon.com
                has_money_patterns=True,
            ),
            behavior=BehaviorSignals(
                is_first_message=True,
                time_to_first_message_seconds=600,  # 10 minutes after join
                is_channel_subscriber=True,
                channel_subscription_duration_days=7,
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.DEALS)
        result = calculator.calculate(signals)

        # Should not be BLOCK or REVIEW
        assert result.verdict in (Verdict.ALLOW, Verdict.WATCH, Verdict.LIMIT)

    def test_forwarded_deal_from_channel(self):
        """Forwarded deal from official channel should be allowed."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                url_count=2,
                has_whitelisted_urls=True,
                has_money_patterns=True,
                has_forward=True,
                forward_from_channel=True,
            ),
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_NEW.signals,
            network=NETWORK_CLEAN.signals,
        )

        deals_calc = RiskCalculator(group_type=GroupType.DEALS)
        general_calc = RiskCalculator(group_type=GroupType.GENERAL)

        deals_result = deals_calc.calculate(signals)
        general_result = general_calc.calculate(signals)

        # Forward penalty should be reduced in deals
        assert deals_result.content_score <= general_result.content_score


class TestDealsVsGeneralComparison:
    """Compare scoring between deals and general groups."""

    def test_same_content_scores_lower_in_deals(self):
        """Promotional content should score lower in deals group."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=CONTENT_DEALS_PROMO.signals,
            behavior=BEHAVIOR_NEUTRAL.signals,
            network=NETWORK_CLEAN.signals,
        )

        deals_calc = RiskCalculator(group_type=GroupType.DEALS)
        general_calc = RiskCalculator(group_type=GroupType.GENERAL)

        deals_result = deals_calc.calculate(signals)
        general_result = general_calc.calculate(signals)

        # Deals should give lower score for promotional content
        assert deals_result.score < general_result.score

    def test_promo_allowed_in_deals_limited_in_general(self):
        """Content allowed in deals might be limited in general."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                url_count=3,
                has_shortened_urls=True,
                has_whitelisted_urls=True,
                has_money_patterns=True,
                has_urgency_patterns=True,
                emoji_count=5,
            ),
            behavior=BEHAVIOR_NEUTRAL.signals,
            network=NETWORK_CLEAN.signals,
        )

        deals_calc = RiskCalculator(group_type=GroupType.DEALS)
        general_calc = RiskCalculator(group_type=GroupType.GENERAL)

        deals_result = deals_calc.calculate(signals)
        general_result = general_calc.calculate(signals)

        # In deals: likely ALLOW or WATCH
        # In general: likely WATCH or LIMIT
        assert deals_result.verdict.value <= general_result.verdict.value or (
            deals_result.verdict == Verdict.ALLOW
            and general_result.verdict in (Verdict.WATCH, Verdict.LIMIT)
        )


class TestDealsSpamDetection:
    """Test that actual spam is still detected in deals groups."""

    def test_crypto_scam_still_blocked_in_deals(self):
        """Crypto scam should still be blocked in deals group."""
        signals = Signals(
            profile=SPAMMER_NEW_ACCOUNT.signals,
            content=CONTENT_CRYPTO_SCAM.signals,
            behavior=BEHAVIOR_FIRST_MESSAGE_FAST.signals,
            network=NETWORK_SPAM_HIGH.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.DEALS)
        result = calculator.calculate(signals)

        # Even with higher thresholds, crypto scam should be blocked
        assert result.verdict == Verdict.BLOCK

    def test_spam_db_high_match_adds_network_score_in_deals(self):
        """High spam DB similarity should still add network score in deals."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=CONTENT_CLEAN.signals,
            behavior=BEHAVIOR_NEUTRAL.signals,
            network=NetworkSignals(
                spam_db_similarity=0.95,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.DEALS)
        result = calculator.calculate(signals)

        # spam_db_similarity_0.95_plus = +50
        # Network score should be 50 regardless of group type
        assert result.network_score == 50
        # Contributing factors should mention spam
        assert "spam" in str(result.contributing_factors).lower()

    def test_suspicious_tld_penalized_in_deals(self):
        """Suspicious TLDs should still be penalized."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                url_count=2,
                has_shortened_urls=False,
                has_whitelisted_urls=False,
                has_suspicious_tld=True,  # .xyz, .top, etc.
                has_money_patterns=True,
            ),
            behavior=BEHAVIOR_NEUTRAL.signals,
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.DEALS)
        result = calculator.calculate(signals)

        # Suspicious TLD should add penalty
        assert result.content_score > 0


class TestDealsFPRateTarget:
    """
    Test cases designed to verify <5% FP rate for deals groups.

    These represent common legitimate deals that should NOT be blocked.
    """

    @pytest.mark.parametrize(
        "description,content_signals,behavior_signals,expected_max_verdict",
        [
            (
                "Simple Amazon deal",
                ContentSignals(url_count=1, has_whitelisted_urls=True, has_money_patterns=True),
                BehaviorSignals(previous_messages_approved=3, is_channel_subscriber=True),
                Verdict.ALLOW,
            ),
            (
                "Multi-store price comparison",
                ContentSignals(
                    url_count=4,
                    has_whitelisted_urls=True,
                    has_money_patterns=True,
                    has_urgency_patterns=True,
                ),
                BehaviorSignals(previous_messages_approved=5, is_channel_subscriber=True),
                Verdict.WATCH,
            ),
            (
                "Affiliate link with shortener",
                ContentSignals(
                    url_count=2,
                    has_shortened_urls=True,
                    has_whitelisted_urls=False,
                    has_money_patterns=True,
                ),
                BehaviorSignals(
                    previous_messages_approved=10,
                    is_channel_subscriber=True,
                    channel_subscription_duration_days=30,
                ),
                Verdict.ALLOW,
            ),
            (
                "Flash sale announcement",
                ContentSignals(
                    url_count=1,
                    has_whitelisted_urls=True,
                    has_urgency_patterns=True,
                    caps_ratio=0.3,
                    emoji_count=5,
                ),
                BehaviorSignals(previous_messages_approved=8, is_channel_subscriber=True),
                Verdict.ALLOW,
            ),
            (
                "Cashback deal post",
                ContentSignals(
                    url_count=2,
                    has_shortened_urls=True,
                    has_money_patterns=True,
                    has_urgency_patterns=True,
                ),
                BehaviorSignals(previous_messages_approved=15, is_channel_subscriber=True),
                Verdict.ALLOW,
            ),
        ],
    )
    def test_legitimate_deal_patterns(
        self,
        description: str,
        content_signals: ContentSignals,
        behavior_signals: BehaviorSignals,
        expected_max_verdict: Verdict,
    ):
        """Legitimate deal patterns should not exceed expected verdict."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=content_signals,
            behavior=behavior_signals,
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.DEALS)
        result = calculator.calculate(signals)

        # Map verdicts to order for comparison
        verdict_order = {
            Verdict.ALLOW: 0,
            Verdict.WATCH: 1,
            Verdict.LIMIT: 2,
            Verdict.REVIEW: 3,
            Verdict.BLOCK: 4,
        }

        assert verdict_order[result.verdict] <= verdict_order[expected_max_verdict], (
            f"'{description}' got {result.verdict} (score: {result.score}), "
            f"expected at most {expected_max_verdict}"
        )

    def test_fp_rate_across_deal_patterns(self):
        """
        Aggregate test: most legitimate deal patterns should be ALLOW/WATCH.

        This test runs multiple legitimate deal scenarios and checks
        that the overall false positive rate is below 5%.
        """
        legitimate_deals = [
            # Tuple of (content_signals, behavior_signals)
            (
                ContentSignals(url_count=1, has_whitelisted_urls=True, has_money_patterns=True),
                BehaviorSignals(previous_messages_approved=5, is_channel_subscriber=True),
            ),
            (
                ContentSignals(
                    url_count=2,
                    has_whitelisted_urls=True,
                    has_money_patterns=True,
                    has_urgency_patterns=True,
                ),
                BehaviorSignals(previous_messages_approved=3, is_channel_subscriber=True),
            ),
            (
                ContentSignals(url_count=1, has_shortened_urls=True, has_money_patterns=True),
                BehaviorSignals(
                    previous_messages_approved=8,
                    is_channel_subscriber=True,
                    channel_subscription_duration_days=14,
                ),
            ),
            (
                ContentSignals(
                    url_count=3, has_whitelisted_urls=True, has_money_patterns=True, emoji_count=4
                ),
                BehaviorSignals(previous_messages_approved=10, is_channel_subscriber=True),
            ),
            (
                ContentSignals(url_count=1, has_whitelisted_urls=True, has_forward=True),
                BehaviorSignals(previous_messages_approved=2, is_channel_subscriber=True),
            ),
        ]

        calculator = RiskCalculator(group_type=GroupType.DEALS)

        blocked_count = 0
        for content, behavior in legitimate_deals:
            signals = Signals(
                profile=TRUSTED_REGULAR.signals,
                content=content,
                behavior=behavior,
                network=NETWORK_CLEAN.signals,
            )
            result = calculator.calculate(signals)

            if result.verdict in (Verdict.REVIEW, Verdict.BLOCK):
                blocked_count += 1

        # FP rate should be < 5% (less than 1 out of 5 scenarios blocked)
        fp_rate = blocked_count / len(legitimate_deals)
        assert fp_rate < 0.05, f"FP rate {fp_rate:.2%} exceeds 5% target"
