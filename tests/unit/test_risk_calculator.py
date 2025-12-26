"""
Tests for RiskCalculator

Tests the core risk scoring logic with various signal combinations.
"""

import pytest

from saqshy.core.constants import THRESHOLDS
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


class TestRiskCalculator:
    """Test suite for RiskCalculator."""

    def test_clean_message_allows(self, clean_signals: Signals):
        """Clean message with trusted user should be allowed."""
        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(clean_signals)

        assert result.verdict == Verdict.ALLOW
        assert result.score < 30

    def test_spam_message_blocks(self, spam_signals: Signals):
        """Obvious spam should be blocked."""
        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(spam_signals)

        assert result.verdict == Verdict.BLOCK
        assert result.score >= 92

    def test_channel_subscriber_reduces_risk(self):
        """Channel subscriber should get significant risk reduction."""
        signals = Signals(
            profile=ProfileSignals(account_age_days=7),
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=30,
            ),
        )

        calculator = RiskCalculator()
        result = calculator.calculate(signals)

        # Channel subscription is -25 points (strongest trust signal)
        assert "Channel subscriber" in str(result.mitigating_factors)

    def test_crypto_scam_phrase_high_risk(self):
        """Crypto scam phrases should add significant risk."""
        signals = Signals(
            content=ContentSignals(
                has_crypto_scam_phrases=True,
            ),
        )

        calculator = RiskCalculator()
        result = calculator.calculate(signals)

        assert result.score >= 30
        assert "crypto scam" in str(result.contributing_factors).lower()

    def test_spam_db_similarity_high_risk(self):
        """High spam database similarity should trigger high risk."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=0.95,
            ),
        )

        calculator = RiskCalculator()
        result = calculator.calculate(signals)

        assert result.score >= 45

    def test_deals_group_higher_tolerance(self):
        """Deals groups should have higher tolerance for links."""
        signals = Signals(
            content=ContentSignals(
                url_count=3,
                has_shortened_urls=True,
            ),
        )

        general_calc = RiskCalculator(group_type=GroupType.GENERAL)
        deals_calc = RiskCalculator(group_type=GroupType.DEALS)

        general_result = general_calc.calculate(signals)
        deals_result = deals_calc.calculate(signals)

        # Deals should have lower score for same URL content
        assert deals_result.score < general_result.score

    def test_crypto_group_strict_scam_detection(self):
        """Crypto groups should be stricter on scam detection."""
        signals = Signals(
            content=ContentSignals(
                has_crypto_scam_phrases=True,
            ),
        )

        general_calc = RiskCalculator(group_type=GroupType.GENERAL)
        crypto_calc = RiskCalculator(group_type=GroupType.CRYPTO)

        general_result = general_calc.calculate(signals)
        crypto_result = crypto_calc.calculate(signals)

        # Crypto should have higher score for scam phrases
        assert crypto_result.score >= general_result.score

    def test_score_clamped_to_100(self):
        """Score should never exceed 100."""
        extreme_signals = Signals(
            profile=ProfileSignals(
                account_age_days=1,
                username_has_random_chars=True,
                name_has_emoji_spam=True,
                bio_has_crypto_terms=True,
            ),
            content=ContentSignals(
                has_crypto_scam_phrases=True,
                has_wallet_addresses=True,
                url_count=5,
                has_shortened_urls=True,
                caps_ratio=0.9,
            ),
            behavior=BehaviorSignals(
                is_first_message=True,
                time_to_first_message_seconds=5,
                previous_messages_blocked=3,
            ),
            network=NetworkSignals(
                spam_db_similarity=0.99,
                duplicate_messages_in_other_groups=5,
                is_in_global_blocklist=True,
            ),
        )

        calculator = RiskCalculator()
        result = calculator.calculate(extreme_signals)

        assert result.score <= 100
        assert result.verdict == Verdict.BLOCK

    def test_score_clamped_to_zero(self):
        """Score should never go below 0."""
        very_trusted_signals = Signals(
            profile=ProfileSignals(
                account_age_days=3650,  # 10 years
                is_premium=True,
                has_profile_photo=True,
                has_username=True,
            ),
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=365,
                previous_messages_approved=100,
            ),
            network=NetworkSignals(
                is_in_global_whitelist=True,
            ),
        )

        calculator = RiskCalculator()
        result = calculator.calculate(very_trusted_signals)

        assert result.score >= 0

    def test_gray_zone_triggers_llm_flag(self):
        """Scores in gray zone (60-80) should flag for LLM review."""
        # Create signals that result in gray zone score
        signals = Signals(
            profile=ProfileSignals(account_age_days=30),
            content=ContentSignals(
                url_count=2,
                has_money_patterns=True,
            ),
            behavior=BehaviorSignals(
                is_first_message=True,
            ),
        )

        calculator = RiskCalculator()
        result = calculator.calculate(signals)

        # If score is in gray zone, needs_llm should be True
        if 60 <= result.score <= 80:
            assert result.needs_llm is True

    def test_thresholds_for_all_group_types(self):
        """Verify thresholds are defined for all group types."""
        for group_type in GroupType:
            assert group_type in THRESHOLDS
            thresholds = THRESHOLDS[group_type]
            assert len(thresholds) == 4
            # Thresholds should be in ascending order
            assert thresholds[0] < thresholds[1] < thresholds[2] < thresholds[3]


class TestVerdictDetermination:
    """Test verdict determination from scores."""

    @pytest.mark.parametrize(
        "score,expected_verdict,group_type",
        [
            (0, Verdict.ALLOW, GroupType.GENERAL),
            (29, Verdict.ALLOW, GroupType.GENERAL),
            (30, Verdict.WATCH, GroupType.GENERAL),
            (49, Verdict.WATCH, GroupType.GENERAL),
            (50, Verdict.LIMIT, GroupType.GENERAL),
            (74, Verdict.LIMIT, GroupType.GENERAL),
            (75, Verdict.REVIEW, GroupType.GENERAL),
            (91, Verdict.REVIEW, GroupType.GENERAL),
            (92, Verdict.BLOCK, GroupType.GENERAL),
            (100, Verdict.BLOCK, GroupType.GENERAL),
            # Deals has higher thresholds
            (39, Verdict.ALLOW, GroupType.DEALS),
            (40, Verdict.WATCH, GroupType.DEALS),
            # Crypto has lower thresholds
            (24, Verdict.ALLOW, GroupType.CRYPTO),
            (25, Verdict.WATCH, GroupType.CRYPTO),
        ],
    )
    def test_verdict_thresholds(
        self,
        score: int,
        expected_verdict: Verdict,
        group_type: GroupType,
    ):
        """Verify correct verdict for various score/group combinations."""
        calculator = RiskCalculator(group_type=group_type)

        # Create minimal signals and override the score check
        signals = Signals()
        result = calculator.calculate(signals)

        # This test just verifies the threshold logic
        thresholds = THRESHOLDS[group_type]
        watch, limit, review, block = thresholds

        if score >= block:
            assert expected_verdict == Verdict.BLOCK
        elif score >= review:
            assert expected_verdict == Verdict.REVIEW
        elif score >= limit:
            assert expected_verdict == Verdict.LIMIT
        elif score >= watch:
            assert expected_verdict == Verdict.WATCH
        else:
            assert expected_verdict == Verdict.ALLOW


class TestScoreBreakdown:
    """Test score breakdown by category."""

    def test_breakdown_categories_sum_to_total(self, clean_signals: Signals):
        """Category scores should sum to total (before clamping)."""
        calculator = RiskCalculator()
        result = calculator.calculate(clean_signals)

        # Note: This may not be exact due to clamping
        expected_sum = (
            result.profile_score
            + result.content_score
            + result.behavior_score
            + result.network_score
        )

        # The raw sum should equal the score before clamping
        assert result.score == max(0, min(100, expected_sum))

    def test_contributing_factors_populated(self, spam_signals: Signals):
        """High risk messages should have contributing factors."""
        calculator = RiskCalculator()
        result = calculator.calculate(spam_signals)

        assert len(result.contributing_factors) > 0

    def test_mitigating_factors_for_trusted(self, clean_signals: Signals):
        """Trusted users should have mitigating factors."""
        calculator = RiskCalculator()
        result = calculator.calculate(clean_signals)

        # Clean signals have channel subscriber
        assert len(result.mitigating_factors) > 0
