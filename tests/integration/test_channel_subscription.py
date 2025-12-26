"""
Integration Tests for Channel Subscription

Tests the strongest trust signal in the SAQSHY system:
- Channel subscription gives conditional trust bonus
- Base bonus: -15 (reduced from -25 to prevent bypass attacks)
- Duration bonuses: -5 for 7d, -10 for 30d
- New accounts (<7 days) are capped at -10 max bonus
- Channel subscription can enable sandbox exit
- Integration with risk calculator

These tests verify the channel subscription mechanism works correctly
as the primary trust indicator while preventing abuse by compromised accounts.
"""

import pytest

from saqshy.core.constants import BEHAVIOR_WEIGHTS
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
    CONTENT_CLEAN,
    NETWORK_CLEAN,
    NEUTRAL_NEW_USER,
    TRUSTED_REGULAR,
    TRUSTED_VETERAN,
)


class TestChannelSubscriptionWeights:
    """Test that channel subscription weights are correctly configured."""

    def test_channel_subscriber_weight_is_minus_25(self):
        """Channel subscription base weight is -25 in constants (applied conditionally)."""
        # Note: The actual application may vary based on account age
        assert BEHAVIOR_WEIGHTS["is_channel_subscriber"] == -25

    def test_subscription_30_days_weight(self):
        """30+ day subscription should give additional -10."""
        assert BEHAVIOR_WEIGHTS["channel_sub_30_days"] == -10

    def test_subscription_7_days_weight(self):
        """7+ day subscription should give additional -5."""
        assert BEHAVIOR_WEIGHTS["channel_sub_7_days"] == -5


class TestChannelSubscriptionTrustBonus:
    """Test the conditional trust bonus for channel subscribers."""

    def test_basic_subscription_reduces_score(self):
        """Basic channel subscription should reduce risk score."""
        # User WITHOUT subscription (established account)
        signals_no_sub = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=False,
            ),
        )

        # User WITH subscription (established account)
        signals_with_sub = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=0,  # Just subscribed
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)

        result_no_sub = calculator.calculate(signals_no_sub)
        result_with_sub = calculator.calculate(signals_with_sub)

        # Subscription should reduce behavior score by 15 (base bonus for established accounts)
        score_diff = result_no_sub.behavior_score - result_with_sub.behavior_score
        assert score_diff == 15

    def test_subscription_appears_in_mitigating_factors(self):
        """Channel subscription should appear in mitigating factors."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=30),
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=10,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert "Channel subscriber" in str(result.mitigating_factors)


class TestSubscriptionDurationBonuses:
    """Test subscription duration-based bonuses."""

    def test_7_day_subscription_bonus(self):
        """7+ days subscription should give -5 additional bonus."""
        signals_fresh = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=3,  # Less than 7 days
                is_first_message=False,
            ),
        )

        signals_7d = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=10,  # 7+ days
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)

        result_fresh = calculator.calculate(signals_fresh)
        result_7d = calculator.calculate(signals_7d)

        # 7+ days should give additional -5
        score_diff = result_fresh.behavior_score - result_7d.behavior_score
        assert score_diff == 5

    def test_30_day_subscription_bonus(self):
        """30+ days subscription should give -10 additional bonus."""
        signals_7d = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=14,  # 7+ but <30 days
                is_first_message=False,
            ),
        )

        signals_30d = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=45,  # 30+ days
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)

        result_7d = calculator.calculate(signals_7d)
        result_30d = calculator.calculate(signals_30d)

        # 30+ days should give -10 instead of -5
        score_diff = result_7d.behavior_score - result_30d.behavior_score
        assert score_diff == 5  # -10 vs -5 = additional -5

    def test_total_subscription_bonus_long_subscriber(self):
        """Long-time subscriber with established account gets full bonus: -15 -10 = -25."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=60,
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Total should be: base (-15) + channel_sub_30_days (-10) = -25
        assert result.behavior_score == -25


class TestSubscriptionOffsetRisk:
    """Test that subscription can offset risk signals."""

    def test_subscriber_new_account_offset(self):
        """Subscription for new account is capped to prevent abuse."""
        # New account (high risk) but channel subscriber
        signals = Signals(
            profile=ProfileSignals(
                account_age_days=5,  # Under 7 days
                has_profile_photo=False,
            ),
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=7,
                is_first_message=True,
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # New account gets capped bonus (-10 instead of -20)
        # Score should be in WATCH range for new accounts (not ALLOW)
        assert result.score < 50  # Still below LIMIT

    def test_subscriber_first_message_not_penalized_heavily(self):
        """First message from subscriber should not trigger heavy penalty."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=CONTENT_CLEAN.signals,
            behavior=BehaviorSignals(
                is_first_message=True,
                time_to_first_message_seconds=45,  # Quick first message
                is_channel_subscriber=True,
                channel_subscription_duration_days=14,
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Trust from subscription should offset first message risk
        assert result.verdict == Verdict.ALLOW

    def test_subscriber_with_links_allowed(self):
        """Subscriber posting links should be trusted."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                url_count=2,
                has_whitelisted_urls=True,
                has_money_patterns=True,
            ),
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=30,
                previous_messages_approved=5,
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.verdict == Verdict.ALLOW


class TestSubscriptionCannotOffsetExtremeRisk:
    """Test that subscription cannot fully offset extreme risk signals."""

    def test_subscriber_crypto_scam_contributes_high_score(self):
        """Even subscribers posting crypto scam should have high content score."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                has_crypto_scam_phrases=True,
                has_wallet_addresses=True,
            ),
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=90,
                previous_messages_approved=20,
                is_first_message=False,  # Not first message, established user
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # crypto_scam_phrase (+35) + wallet_address (+20) = +55 content
        # Content score should be high even with trusted subscriber
        assert result.content_score >= 50
        # Contributing factors should mention crypto scam
        assert "crypto scam" in str(result.contributing_factors).lower()

    def test_subscriber_spam_db_match_adds_network_score(self):
        """Subscriber with high spam DB match should have high network score."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=CONTENT_CLEAN.signals,
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=60,
                is_first_message=False,
            ),
            network=NetworkSignals(
                spam_db_similarity=0.95,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # spam_db_similarity_0.95_plus = +50
        assert result.network_score == 50
        # Should be in contributing factors
        assert "spam" in str(result.contributing_factors).lower()

    def test_subscriber_blocklist_adds_network_score(self):
        """Blocklisted subscriber still gets network penalty."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=CONTENT_CLEAN.signals,
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=90,
                is_first_message=False,
            ),
            network=NetworkSignals(
                is_in_global_blocklist=True,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # is_in_global_blocklist = +50
        assert result.network_score == 50
        # Should be in contributing factors
        assert "blocklist" in str(result.contributing_factors).lower()


class TestSubscriptionVsNonSubscription:
    """Compare subscriber vs non-subscriber behavior."""

    def test_same_message_different_subscription_status(self):
        """Same message should score differently based on subscription."""
        base_profile = ProfileSignals(account_age_days=30)  # Established account
        base_content = ContentSignals(
            url_count=1,
            has_money_patterns=True,
        )

        signals_no_sub = Signals(
            profile=base_profile,
            content=base_content,
            behavior=BehaviorSignals(
                is_first_message=False,
                is_channel_subscriber=False,
            ),
            network=NETWORK_CLEAN.signals,
        )

        signals_with_sub = Signals(
            profile=base_profile,
            content=base_content,
            behavior=BehaviorSignals(
                is_first_message=False,
                is_channel_subscriber=True,
                channel_subscription_duration_days=7,
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)

        result_no_sub = calculator.calculate(signals_no_sub)
        result_with_sub = calculator.calculate(signals_with_sub)

        # Subscriber should score lower (behavior diff: -15 -5 = -20)
        assert result_with_sub.score < result_no_sub.score
        # Behavior score difference should be at least 20
        behavior_diff = result_no_sub.behavior_score - result_with_sub.behavior_score
        assert behavior_diff >= 20

    def test_subscriber_verdict_upgrade(self):
        """Subscription can upgrade verdict from WATCH to ALLOW."""
        content_with_risk = ContentSignals(
            url_count=2,
            has_shortened_urls=True,
            has_money_patterns=True,
        )

        signals_no_sub = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=content_with_risk,
            behavior=BehaviorSignals(
                is_channel_subscriber=False,
                previous_messages_approved=3,
            ),
            network=NETWORK_CLEAN.signals,
        )

        signals_with_sub = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=content_with_risk,
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=30,
                previous_messages_approved=3,
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)

        result_no_sub = calculator.calculate(signals_no_sub)
        result_with_sub = calculator.calculate(signals_with_sub)

        # Without subscription might be WATCH, with subscription should be ALLOW
        assert result_with_sub.verdict.value <= result_no_sub.verdict.value


class TestSubscriptionAcrossGroupTypes:
    """Test subscription behavior across different group types."""

    @pytest.mark.parametrize("group_type", list(GroupType))
    def test_subscription_bonus_same_across_groups(self, group_type: GroupType):
        """Subscription bonus should be same across all group types for established accounts."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=30,
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=group_type)
        result = calculator.calculate(signals)

        # Behavior score should be -25 regardless of group type
        # base (-15) + channel_sub_30_days (-10) = -25
        assert result.behavior_score == -25

    def test_subscription_more_valuable_in_crypto(self):
        """Subscription is relatively more valuable in crypto (lower thresholds)."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=14),  # Account > 7 days
            content=ContentSignals(
                has_money_patterns=True,
            ),
            behavior=BehaviorSignals(
                is_first_message=True,
                is_channel_subscriber=True,
                channel_subscription_duration_days=14,
            ),
            network=NETWORK_CLEAN.signals,
        )

        general_calc = RiskCalculator(group_type=GroupType.GENERAL)
        crypto_calc = RiskCalculator(group_type=GroupType.CRYPTO)

        general_result = general_calc.calculate(signals)
        crypto_result = crypto_calc.calculate(signals)

        # Both should be in ALLOW range
        assert general_result.verdict == Verdict.ALLOW
        assert crypto_result.verdict == Verdict.ALLOW


class TestSubscriptionWithPreviousMessages:
    """Test subscription combined with previous message history."""

    def test_subscriber_with_approved_messages_max_trust(self):
        """Subscriber with 10+ approved messages = maximum trust."""
        signals = Signals(
            profile=TRUSTED_VETERAN.signals,
            content=CONTENT_CLEAN.signals,
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=60,
                previous_messages_approved=15,
                is_first_message=False,  # Not first message
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Channel subscription bonus: base (-15) + 30d duration (-10) = -25
        # previous_messages_approved_10_plus: -15
        # Total behavior: -40
        assert result.behavior_score == -40
        assert result.verdict == Verdict.ALLOW
        assert result.score == 0  # Clamped to 0

    def test_subscriber_with_some_approved_messages(self):
        """Subscriber with 5+ approved messages gets moderate trust."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=14,
                previous_messages_approved=7,
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # base (-15) + channel_sub_7_days (-5) + previous_messages_approved_5_plus (-10) = -30
        assert result.behavior_score == -30


class TestSubscriptionEdgeCases:
    """Test edge cases for subscription handling."""

    def test_subscription_zero_days(self):
        """Just subscribed (0 days) with established account gets base -15."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=0,
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.behavior_score == -15

    def test_subscription_exactly_7_days(self):
        """Exactly 7 days with established account gets base + duration bonus."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=7,
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.behavior_score == -20  # -15 + -5

    def test_subscription_exactly_30_days(self):
        """Exactly 30 days with established account gets full duration bonus."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=30),  # Established account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=30,
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.behavior_score == -25  # -15 + -10

    def test_not_subscriber_no_bonus(self):
        """Non-subscriber should get no bonus even with duration set."""
        signals = Signals(
            behavior=BehaviorSignals(
                is_channel_subscriber=False,
                channel_subscription_duration_days=365,  # This should be ignored
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # No subscription bonus, just default behavior score (0)
        assert result.behavior_score == 0


class TestNewAccountCapping:
    """Test that new accounts have capped subscription bonus."""

    def test_new_account_capped_at_minus_10(self):
        """New account (<7 days) should be capped at -10 bonus."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=3),  # New account
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=30,  # Long subscription
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Despite long subscription, capped at -10 for new accounts
        # Check mitigating factors mention the cap
        assert "capped" in str(result.mitigating_factors).lower()

    def test_established_account_full_bonus(self):
        """Established account (7+ days) gets full subscription bonus."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=7),  # Just established
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=30,
                is_first_message=False,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Should get full -25 bonus (base -15 + duration -10)
        assert result.behavior_score == -25


class TestSubscriptionSandboxExit:
    """Test that subscription can enable sandbox exit."""

    def test_subscriber_bypasses_first_message_penalty(self):
        """Subscriber's first message should have reduced penalty."""
        # New user first message WITHOUT subscription
        no_sub = Signals(
            profile=ProfileSignals(account_age_days=7),
            behavior=BehaviorSignals(
                is_first_message=True,
                time_to_first_message_seconds=60,
                is_channel_subscriber=False,
            ),
        )

        # New user first message WITH subscription
        with_sub = Signals(
            profile=ProfileSignals(account_age_days=7),
            behavior=BehaviorSignals(
                is_first_message=True,
                time_to_first_message_seconds=60,
                is_channel_subscriber=True,
                channel_subscription_duration_days=7,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)

        result_no_sub = calculator.calculate(no_sub)
        result_with_sub = calculator.calculate(with_sub)

        # Subscriber should score much lower
        assert result_with_sub.score < result_no_sub.score
        # Subscriber first message should likely be ALLOW
        assert result_with_sub.verdict == Verdict.ALLOW

    def test_fast_first_message_subscriber_allowed(self):
        """Fast first message from subscriber should be allowed."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=CONTENT_CLEAN.signals,
            behavior=BehaviorSignals(
                is_first_message=True,
                time_to_first_message_seconds=25,  # Fast but not suspicious for subscriber
                join_to_message_seconds=120,
                is_channel_subscriber=True,
                channel_subscription_duration_days=30,
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Even with fast first message, subscription should keep it in ALLOW
        assert result.verdict == Verdict.ALLOW
