"""
Unit tests for TRUST_SCORE_ADJUSTMENTS integration.

Tests:
- Trust level affects final risk score
- Trust adjustments recorded in breakdown
- All trust levels have correct adjustments
"""

import pytest

from saqshy.core.risk_calculator import RiskCalculator
from saqshy.core.sandbox import TRUST_SCORE_ADJUSTMENTS, TrustLevel
from saqshy.core.types import (
    BehaviorSignals,
    ContentSignals,
    GroupType,
    NetworkSignals,
    ProfileSignals,
    Signals,
    Verdict,
)


class TestTrustScoreAdjustmentsConstant:
    """Tests for TRUST_SCORE_ADJUSTMENTS constant values."""

    def test_untrusted_is_positive(self):
        """UNTRUSTED should add risk."""
        assert TRUST_SCORE_ADJUSTMENTS["untrusted"] > 0

    def test_provisional_is_zero(self):
        """PROVISIONAL should have no adjustment."""
        assert TRUST_SCORE_ADJUSTMENTS["provisional"] == 0

    def test_trusted_is_negative(self):
        """TRUSTED should reduce score."""
        assert TRUST_SCORE_ADJUSTMENTS["trusted"] < 0

    def test_established_is_most_negative(self):
        """ESTABLISHED should have biggest reduction."""
        assert TRUST_SCORE_ADJUSTMENTS["established"] < TRUST_SCORE_ADJUSTMENTS["trusted"]

    def test_all_trust_levels_have_adjustments(self):
        """All TrustLevel values should have corresponding adjustments."""
        for level in TrustLevel:
            assert level.value in TRUST_SCORE_ADJUSTMENTS


class TestRiskCalculatorTrustLevel:
    """Tests for RiskCalculator trust level integration."""

    @pytest.fixture
    def base_signals(self):
        """Create signals that produce a moderate risk score."""
        return Signals(
            profile=ProfileSignals(
                has_username=True,
                has_profile_photo=True,
                is_premium=False,
                account_age_days=30,
            ),
            content=ContentSignals(
                url_count=1,
                caps_ratio=0.1,
                text_length=100,
            ),
            behavior=BehaviorSignals(
                time_to_first_message_seconds=300,
                is_first_message=False,
                messages_in_last_hour=2,
            ),
            network=NetworkSignals(
                spam_db_similarity=0.3,
            ),
        )

    def test_provisional_no_adjustment(self, base_signals):
        """PROVISIONAL should not adjust score."""
        calc = RiskCalculator(trust_level=TrustLevel.PROVISIONAL)
        result = calc.calculate(base_signals)

        # No trust adjustment in factors
        trust_factors = [
            f for f in result.mitigating_factors + result.contributing_factors
            if "Trust level" in f
        ]
        assert len(trust_factors) == 0

    def test_trusted_reduces_score(self, base_signals):
        """TRUSTED should reduce final score (or both are 0 due to clamping)."""
        calc_provisional = RiskCalculator(trust_level=TrustLevel.PROVISIONAL)
        calc_trusted = RiskCalculator(trust_level=TrustLevel.TRUSTED)

        result_provisional = calc_provisional.calculate(base_signals)
        result_trusted = calc_trusted.calculate(base_signals)

        # Score is clamped at 0, so trusted should be <= provisional
        assert result_trusted.score <= result_provisional.score

    def test_established_reduces_score_most(self, base_signals):
        """ESTABLISHED should reduce score more than TRUSTED (or both are 0)."""
        calc_trusted = RiskCalculator(trust_level=TrustLevel.TRUSTED)
        calc_established = RiskCalculator(trust_level=TrustLevel.ESTABLISHED)

        result_trusted = calc_trusted.calculate(base_signals)
        result_established = calc_established.calculate(base_signals)

        # Score is clamped at 0, so established should be <= trusted
        assert result_established.score <= result_trusted.score

    def test_untrusted_adds_risk(self, base_signals):
        """UNTRUSTED should add risk."""
        calc_provisional = RiskCalculator(trust_level=TrustLevel.PROVISIONAL)
        calc_untrusted = RiskCalculator(trust_level=TrustLevel.UNTRUSTED)

        result_provisional = calc_provisional.calculate(base_signals)
        result_untrusted = calc_untrusted.calculate(base_signals)

        assert result_untrusted.score > result_provisional.score

    def test_trust_adjustment_recorded_in_factors(self, base_signals):
        """Trust adjustment should appear in factors."""
        calc = RiskCalculator(trust_level=TrustLevel.TRUSTED)
        result = calc.calculate(base_signals)

        # Should be in mitigating factors (negative adjustment)
        trust_factors = [
            f for f in result.mitigating_factors if "Trust level" in f
        ]
        assert len(trust_factors) == 1
        assert "trusted" in trust_factors[0]

    def test_established_adjustment_in_factors(self, base_signals):
        """Established adjustment should appear in factors."""
        calc = RiskCalculator(trust_level=TrustLevel.ESTABLISHED)
        result = calc.calculate(base_signals)

        trust_factors = [
            f for f in result.mitigating_factors if "Trust level" in f
        ]
        assert len(trust_factors) == 1
        assert "established" in trust_factors[0]

    def test_untrusted_adjustment_in_factors(self, base_signals):
        """Untrusted adjustment should appear in contributing factors."""
        calc = RiskCalculator(trust_level=TrustLevel.UNTRUSTED)
        result = calc.calculate(base_signals)

        trust_factors = [
            f for f in result.contributing_factors if "Trust level" in f
        ]
        assert len(trust_factors) == 1
        assert "untrusted" in trust_factors[0]


class TestTrustLevelVerdictImpact:
    """Tests that trust level can change verdict."""

    @pytest.fixture
    def borderline_signals(self):
        """Create signals near WATCH/LIMIT boundary."""
        return Signals(
            profile=ProfileSignals(
                has_username=False,  # +10
                has_profile_photo=False,  # +8
                is_premium=False,
                account_age_days=5,  # +5 (low age)
            ),
            content=ContentSignals(
                url_count=2,  # +5 per link
                caps_ratio=0.3,  # +10
                text_length=50,
            ),
            behavior=BehaviorSignals(
                time_to_first_message_seconds=10,  # +15 (very fast)
                is_first_message=True,  # +10
                messages_in_last_hour=5,  # +10 (frequent)
            ),
            network=NetworkSignals(
                spam_db_similarity=0.0,
            ),
        )

    def test_trust_can_lower_verdict(self, borderline_signals):
        """Established trust should lower score and potentially verdict."""
        calc_untrusted = RiskCalculator(trust_level=TrustLevel.UNTRUSTED)
        calc_established = RiskCalculator(trust_level=TrustLevel.ESTABLISHED)

        result_untrusted = calc_untrusted.calculate(borderline_signals)
        result_established = calc_established.calculate(borderline_signals)

        # Established should have lower score due to -20 vs +5 adjustment
        assert result_established.score < result_untrusted.score


class TestTrustLevelWithGroupTypes:
    """Tests for trust level interaction with different group types."""

    @pytest.fixture
    def moderate_signals(self):
        """Create signals with moderate risk."""
        return Signals(
            profile=ProfileSignals(
                has_username=True,
                has_profile_photo=True,
                is_premium=False,
                account_age_days=60,
            ),
            content=ContentSignals(
                url_count=1,
                caps_ratio=0.1,
                text_length=100,
            ),
            behavior=BehaviorSignals(
                time_to_first_message_seconds=120,
                is_first_message=True,
                messages_in_last_hour=1,
            ),
            network=NetworkSignals(
                spam_db_similarity=0.2,
            ),
        )

    @pytest.mark.parametrize("group_type", list(GroupType))
    def test_trust_applies_to_all_group_types(self, moderate_signals, group_type):
        """Trust adjustment should work with all group types."""
        calc_provisional = RiskCalculator(
            group_type=group_type, trust_level=TrustLevel.PROVISIONAL
        )
        calc_established = RiskCalculator(
            group_type=group_type, trust_level=TrustLevel.ESTABLISHED
        )

        result_provisional = calc_provisional.calculate(moderate_signals)
        result_established = calc_established.calculate(moderate_signals)

        # Established should always be lower (or same if score is 0)
        assert result_established.score <= result_provisional.score

    def test_trust_stacks_with_deals_tolerance(self, moderate_signals):
        """Trust should combine with deals group type tolerance."""
        # Deals groups are more tolerant + established trust = very low score
        calc = RiskCalculator(
            group_type=GroupType.DEALS, trust_level=TrustLevel.ESTABLISHED
        )
        result = calc.calculate(moderate_signals)

        # Should have low score due to both factors
        assert result.verdict in (Verdict.ALLOW, Verdict.WATCH)
