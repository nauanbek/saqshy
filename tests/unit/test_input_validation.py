"""
Unit tests for input validation in dataclasses.

Tests:
- ContentSignals bounds checking
- NetworkSignals bounds checking
- RiskResult validation
- RiskCalculator weight validation
"""

from dataclasses import FrozenInstanceError

import pytest

from saqshy.core.risk_calculator import RiskCalculator
from saqshy.core.types import (
    BehaviorSignals,
    ContentSignals,
    GroupType,
    NetworkSignals,
    ProfileSignals,
    RiskResult,
    Signals,
    Verdict,
)


class TestContentSignalsValidation:
    """Tests for ContentSignals bounds checking."""

    def test_valid_caps_ratio(self):
        """Valid caps_ratio should not raise."""
        signals = ContentSignals(caps_ratio=0.5, text_length=100)
        assert signals.caps_ratio == 0.5

    def test_caps_ratio_zero(self):
        """caps_ratio=0 should be valid."""
        signals = ContentSignals(caps_ratio=0.0, text_length=100)
        assert signals.caps_ratio == 0.0

    def test_caps_ratio_one(self):
        """caps_ratio=1 should be valid."""
        signals = ContentSignals(caps_ratio=1.0, text_length=100)
        assert signals.caps_ratio == 1.0

    def test_caps_ratio_negative_raises(self):
        """Negative caps_ratio should raise ValueError."""
        with pytest.raises(ValueError, match="caps_ratio must be 0.0-1.0"):
            ContentSignals(caps_ratio=-0.1, text_length=100)

    def test_caps_ratio_above_one_raises(self):
        """caps_ratio > 1 should raise ValueError."""
        with pytest.raises(ValueError, match="caps_ratio must be 0.0-1.0"):
            ContentSignals(caps_ratio=1.5, text_length=100)

    def test_text_length_negative_raises(self):
        """Negative text_length should raise ValueError."""
        with pytest.raises(ValueError, match="text_length cannot be negative"):
            ContentSignals(caps_ratio=0.1, text_length=-1)

    def test_text_length_zero_valid(self):
        """text_length=0 should be valid."""
        signals = ContentSignals(caps_ratio=0.1, text_length=0)
        assert signals.text_length == 0

    def test_url_count_negative_raises(self):
        """Negative url_count should raise ValueError."""
        with pytest.raises(ValueError, match="url_count cannot be negative"):
            ContentSignals(caps_ratio=0.1, text_length=100, url_count=-1)

    def test_emoji_count_negative_raises(self):
        """Negative emoji_count should raise ValueError."""
        with pytest.raises(ValueError, match="emoji_count cannot be negative"):
            ContentSignals(caps_ratio=0.1, text_length=100, emoji_count=-1)


class TestNetworkSignalsValidation:
    """Tests for NetworkSignals bounds checking."""

    def test_valid_spam_db_similarity(self):
        """Valid spam_db_similarity should not raise."""
        signals = NetworkSignals(spam_db_similarity=0.85)
        assert signals.spam_db_similarity == 0.85

    def test_spam_db_similarity_zero(self):
        """spam_db_similarity=0 should be valid."""
        signals = NetworkSignals(spam_db_similarity=0.0)
        assert signals.spam_db_similarity == 0.0

    def test_spam_db_similarity_one(self):
        """spam_db_similarity=1 should be valid."""
        signals = NetworkSignals(spam_db_similarity=1.0)
        assert signals.spam_db_similarity == 1.0

    def test_spam_db_similarity_negative_raises(self):
        """Negative spam_db_similarity should raise ValueError."""
        with pytest.raises(ValueError, match="spam_db_similarity must be 0.0-1.0"):
            NetworkSignals(spam_db_similarity=-0.1)

    def test_spam_db_similarity_above_one_raises(self):
        """spam_db_similarity > 1 should raise ValueError."""
        with pytest.raises(ValueError, match="spam_db_similarity must be 0.0-1.0"):
            NetworkSignals(spam_db_similarity=1.5)


class TestRiskResultValidation:
    """Tests for RiskResult validation."""

    def test_valid_result(self):
        """Valid RiskResult should not raise."""
        result = RiskResult(
            score=50,
            verdict=Verdict.LIMIT,
            confidence=0.85,
        )
        assert result.score == 50

    def test_score_zero_valid(self):
        """score=0 should be valid."""
        result = RiskResult(
            score=0,
            verdict=Verdict.ALLOW,
            confidence=1.0,
        )
        assert result.score == 0

    def test_score_hundred_valid(self):
        """score=100 should be valid."""
        result = RiskResult(
            score=100,
            verdict=Verdict.BLOCK,
            confidence=1.0,
        )
        assert result.score == 100

    def test_score_negative_raises(self):
        """Negative score should raise ValueError."""
        with pytest.raises(ValueError, match="score must be 0-100"):
            RiskResult(
                score=-1,
                verdict=Verdict.ALLOW,
                confidence=1.0,
            )

    def test_score_above_hundred_raises(self):
        """score > 100 should raise ValueError."""
        with pytest.raises(ValueError, match="score must be 0-100"):
            RiskResult(
                score=101,
                verdict=Verdict.BLOCK,
                confidence=1.0,
            )

    def test_confidence_zero_valid(self):
        """confidence=0 should be valid."""
        result = RiskResult(
            score=50,
            verdict=Verdict.LIMIT,
            confidence=0.0,
        )
        assert result.confidence == 0.0

    def test_confidence_one_valid(self):
        """confidence=1 should be valid."""
        result = RiskResult(
            score=50,
            verdict=Verdict.LIMIT,
            confidence=1.0,
        )
        assert result.confidence == 1.0

    def test_confidence_negative_raises(self):
        """Negative confidence should raise ValueError."""
        with pytest.raises(ValueError, match="confidence must be 0.0-1.0"):
            RiskResult(
                score=50,
                verdict=Verdict.LIMIT,
                confidence=-0.1,
            )

    def test_confidence_above_one_raises(self):
        """confidence > 1 should raise ValueError."""
        with pytest.raises(ValueError, match="confidence must be 0.0-1.0"):
            RiskResult(
                score=50,
                verdict=Verdict.LIMIT,
                confidence=1.5,
            )


class TestRiskCalculatorWeightValidation:
    """Tests for RiskCalculator weight validation."""

    def test_default_weights_valid(self):
        """Default weights should be valid."""
        calc = RiskCalculator()
        assert calc is not None

    def test_all_group_types_have_valid_weights(self):
        """All group types should have valid weights."""
        for group_type in GroupType:
            calc = RiskCalculator(group_type=group_type)
            assert calc is not None

    def test_weight_values_reasonable(self):
        """All weights should be within reasonable bounds."""
        calc = RiskCalculator()

        for key, value in calc.profile_weights.items():
            assert abs(value) <= 100, f"profile_weights[{key}] = {value} exceeds bounds"

        for key, value in calc.content_weights.items():
            assert abs(value) <= 100, f"content_weights[{key}] = {value} exceeds bounds"

        for key, value in calc.behavior_weights.items():
            assert abs(value) <= 100, f"behavior_weights[{key}] = {value} exceeds bounds"

        for key, value in calc.network_weights.items():
            assert abs(value) <= 100, f"network_weights[{key}] = {value} exceeds bounds"


class TestSignalsImmutability:
    """Tests that Signals dataclasses are frozen."""

    def test_content_signals_frozen(self):
        """ContentSignals should be frozen."""
        signals = ContentSignals(caps_ratio=0.5, text_length=100)
        with pytest.raises(FrozenInstanceError):
            signals.caps_ratio = 0.6

    def test_network_signals_frozen(self):
        """NetworkSignals should be frozen."""
        signals = NetworkSignals(spam_db_similarity=0.5)
        with pytest.raises(FrozenInstanceError):
            signals.spam_db_similarity = 0.6

    def test_profile_signals_frozen(self):
        """ProfileSignals should be frozen."""
        signals = ProfileSignals()
        with pytest.raises(FrozenInstanceError):
            signals.has_username = True

    def test_behavior_signals_frozen(self):
        """BehaviorSignals should be frozen."""
        signals = BehaviorSignals()
        with pytest.raises(FrozenInstanceError):
            signals.is_first_message = True


class TestEdgeCases:
    """Tests for edge cases in validation."""

    def test_content_signals_boundary_values(self):
        """Test exact boundary values for ContentSignals."""
        # Exact boundaries should work
        ContentSignals(caps_ratio=0.0, text_length=0, url_count=0, emoji_count=0)
        ContentSignals(caps_ratio=1.0, text_length=1000000, url_count=100)

    def test_network_signals_boundary_values(self):
        """Test exact boundary values for NetworkSignals."""
        NetworkSignals(spam_db_similarity=0.0)
        NetworkSignals(spam_db_similarity=1.0)

    def test_valid_signals_composite(self):
        """Full Signals object with valid values should work."""
        signals = Signals(
            profile=ProfileSignals(
                has_username=True,
                has_profile_photo=True,
                is_premium=False,
                account_age_days=365,
            ),
            content=ContentSignals(
                url_count=5,
                emoji_count=3,
                caps_ratio=0.25,
                text_length=500,
            ),
            behavior=BehaviorSignals(
                time_to_first_message_seconds=60,
                is_first_message=True,
                messages_in_last_hour=10,
            ),
            network=NetworkSignals(
                spam_db_similarity=0.75,
            ),
        )
        assert signals.profile.has_username is True
        assert signals.content.url_count == 5
        assert signals.behavior.messages_in_last_hour == 10
        assert signals.network.spam_db_similarity == 0.75
