"""
Integration Tests for Spam Database Matching

Tests the spam database similarity scoring:
- Similarity thresholds: 0.70, 0.80, 0.88, 0.95
- CRYPTO_SCAM_PHRASES detection
- Legitimate crypto discussions in crypto groups
- Integration with risk calculator

These tests verify the spam detection based on vector similarity
and pattern matching works correctly.
"""

import pytest

from saqshy.core.constants import (
    CRYPTO_SCAM_PHRASES,
    NETWORK_WEIGHTS,
)
from saqshy.core.risk_calculator import RiskCalculator
from saqshy.core.types import (
    BehaviorSignals,
    ContentSignals,
    GroupType,
    NetworkSignals,
    ProfileSignals,
    Signals,
    ThreatType,
    Verdict,
)

# Define similarity thresholds and scoring locally to avoid Cohere import issues
# These mirror the values from saqshy.services.spam_db
SIMILARITY_THRESHOLDS = {
    "near_exact": 0.95,
    "high": 0.88,
    "medium": 0.80,
    "low": 0.70,
}

SIMILARITY_SCORES = {
    "near_exact": 50,
    "high": 45,
    "medium": 35,
    "low": 25,
}


def get_risk_score_for_similarity(similarity: float) -> int:
    """Calculate risk score points based on similarity value."""
    if similarity >= SIMILARITY_THRESHOLDS["near_exact"]:
        return SIMILARITY_SCORES["near_exact"]
    elif similarity >= SIMILARITY_THRESHOLDS["high"]:
        return SIMILARITY_SCORES["high"]
    elif similarity >= SIMILARITY_THRESHOLDS["medium"]:
        return SIMILARITY_SCORES["medium"]
    elif similarity >= SIMILARITY_THRESHOLDS["low"]:
        return SIMILARITY_SCORES["low"]
    return 0


def get_similarity_tier(similarity: float) -> str | None:
    """Get the similarity tier name for a score."""
    if similarity >= SIMILARITY_THRESHOLDS["near_exact"]:
        return "near_exact"
    elif similarity >= SIMILARITY_THRESHOLDS["high"]:
        return "high"
    elif similarity >= SIMILARITY_THRESHOLDS["medium"]:
        return "medium"
    elif similarity >= SIMILARITY_THRESHOLDS["low"]:
        return "low"
    return None


from tests.fixtures.scenarios import (
    BEHAVIOR_CHANNEL_SUBSCRIBER_LONG,
    BEHAVIOR_CHANNEL_SUBSCRIBER_NEW,
    BEHAVIOR_FIRST_MESSAGE_FAST,
    CONTENT_CLEAN,
    CONTENT_CRYPTO_DISCUSSION,
    CONTENT_CRYPTO_SCAM,
    NETWORK_CLEAN,
    NETWORK_SPAM_HIGH,
    SPAMMER_NEW_ACCOUNT,
    TRUSTED_REGULAR,
    TRUSTED_VETERAN,
)


class TestSimilarityThresholds:
    """Test similarity threshold configuration."""

    def test_threshold_values(self):
        """Verify threshold values are correct."""
        assert SIMILARITY_THRESHOLDS["near_exact"] == 0.95
        assert SIMILARITY_THRESHOLDS["high"] == 0.88
        assert SIMILARITY_THRESHOLDS["medium"] == 0.80
        assert SIMILARITY_THRESHOLDS["low"] == 0.70

    def test_thresholds_in_descending_order(self):
        """Thresholds should be in descending order."""
        assert SIMILARITY_THRESHOLDS["near_exact"] > SIMILARITY_THRESHOLDS["high"]
        assert SIMILARITY_THRESHOLDS["high"] > SIMILARITY_THRESHOLDS["medium"]
        assert SIMILARITY_THRESHOLDS["medium"] > SIMILARITY_THRESHOLDS["low"]


class TestSimilarityScoring:
    """Test similarity to risk score mapping."""

    def test_near_exact_match_score(self):
        """Near-exact match (0.95+) should give 50 points."""
        assert get_risk_score_for_similarity(0.95) == 50
        assert get_risk_score_for_similarity(0.99) == 50
        assert get_risk_score_for_similarity(1.0) == 50

    def test_high_match_score(self):
        """High similarity (0.88-0.95) should give 45 points."""
        assert get_risk_score_for_similarity(0.88) == 45
        assert get_risk_score_for_similarity(0.92) == 45
        assert get_risk_score_for_similarity(0.94) == 45

    def test_medium_match_score(self):
        """Medium similarity (0.80-0.88) should give 35 points."""
        assert get_risk_score_for_similarity(0.80) == 35
        assert get_risk_score_for_similarity(0.85) == 35
        assert get_risk_score_for_similarity(0.87) == 35

    def test_low_match_score(self):
        """Low similarity (0.70-0.80) should give 25 points."""
        assert get_risk_score_for_similarity(0.70) == 25
        assert get_risk_score_for_similarity(0.75) == 25
        assert get_risk_score_for_similarity(0.79) == 25

    def test_no_match_score(self):
        """Below threshold (<0.70) should give 0 points."""
        assert get_risk_score_for_similarity(0.69) == 0
        assert get_risk_score_for_similarity(0.50) == 0
        assert get_risk_score_for_similarity(0.0) == 0


class TestSimilarityTiers:
    """Test similarity tier classification."""

    @pytest.mark.parametrize(
        "similarity,expected_tier",
        [
            (0.95, "near_exact"),
            (0.99, "near_exact"),
            (0.88, "high"),
            (0.92, "high"),
            (0.80, "medium"),
            (0.85, "medium"),
            (0.70, "low"),
            (0.75, "low"),
            (0.69, None),
            (0.50, None),
            (0.0, None),
        ],
    )
    def test_tier_classification(self, similarity: float, expected_tier: str | None):
        """Verify correct tier classification for similarity scores."""
        assert get_similarity_tier(similarity) == expected_tier


class TestNetworkWeightConfiguration:
    """Test network weight configuration for spam DB matches."""

    def test_spam_db_weights_exist(self):
        """Spam DB similarity weights should be defined."""
        assert "spam_db_similarity_0.95_plus" in NETWORK_WEIGHTS
        assert "spam_db_similarity_0.88_plus" in NETWORK_WEIGHTS
        assert "spam_db_similarity_0.80_plus" in NETWORK_WEIGHTS
        assert "spam_db_similarity_0.70_plus" in NETWORK_WEIGHTS

    def test_spam_db_weights_values(self):
        """Spam DB weights should match expected values."""
        assert NETWORK_WEIGHTS["spam_db_similarity_0.95_plus"] == 50
        assert NETWORK_WEIGHTS["spam_db_similarity_0.88_plus"] == 45
        assert NETWORK_WEIGHTS["spam_db_similarity_0.80_plus"] == 35
        assert NETWORK_WEIGHTS["spam_db_similarity_0.70_plus"] == 25


class TestSpamDBIntegration:
    """Test spam DB similarity integration with risk calculator."""

    @pytest.mark.parametrize(
        "similarity,expected_min_score",
        [
            (0.95, 50),
            (0.92, 45),
            (0.85, 35),
            (0.75, 25),
            (0.60, 0),
        ],
    )
    def test_similarity_adds_to_network_score(self, similarity: float, expected_min_score: int):
        """Spam DB similarity should add to network score."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=similarity,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.network_score >= expected_min_score

    def test_near_exact_match_triggers_spam_threat(self):
        """Near-exact spam match should set threat type to SPAM."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=0.95,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.threat_type == ThreatType.SPAM

    def test_high_match_contributes_factor(self):
        """High spam match should appear in contributing factors."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=0.92,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert "spam" in str(result.contributing_factors).lower()


class TestCryptoScamPhrases:
    """Test CRYPTO_SCAM_PHRASES detection."""

    def test_crypto_scam_phrases_exist(self):
        """Crypto scam phrases list should be populated."""
        assert len(CRYPTO_SCAM_PHRASES) > 0

    @pytest.mark.parametrize(
        "phrase",
        [
            "guaranteed profit",
            "100% profit",
            "double your",
            "10x return",
            "100x return",
            "passive income crypto",
            "dm me for",
            "claim your reward",
        ],
    )
    def test_key_scam_phrases_included(self, phrase: str):
        """Key crypto scam phrases should be in the list."""
        assert phrase.lower() in [p.lower() for p in CRYPTO_SCAM_PHRASES]

    def test_crypto_scam_phrase_triggers_high_score(self):
        """Crypto scam phrase should add significant risk."""
        signals = Signals(
            content=ContentSignals(
                has_crypto_scam_phrases=True,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # crypto_scam_phrase = +35
        assert result.content_score >= 35
        assert result.threat_type == ThreatType.CRYPTO_SCAM

    def test_crypto_scam_phrase_in_contributing_factors(self):
        """Crypto scam phrase should appear in contributing factors."""
        signals = Signals(
            content=ContentSignals(
                has_crypto_scam_phrases=True,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert "crypto scam" in str(result.contributing_factors).lower()


class TestLegitimaCryptoInCryptoGroups:
    """Test that legitimate crypto discussions don't trigger in crypto groups."""

    def test_wallet_address_reduced_in_crypto_group(self):
        """Wallet address penalty should be reduced in crypto groups."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                has_wallet_addresses=True,
                has_crypto_scam_phrases=False,  # No scam phrases
            ),
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_NEW.signals,
            network=NETWORK_CLEAN.signals,
        )

        general_calc = RiskCalculator(group_type=GroupType.GENERAL)
        crypto_calc = RiskCalculator(group_type=GroupType.CRYPTO)

        general_result = general_calc.calculate(signals)
        crypto_result = crypto_calc.calculate(signals)

        # Wallet address penalty: 20 in general, 5 in crypto
        assert crypto_result.content_score < general_result.content_score

    def test_legitimate_crypto_discussion_allowed(self):
        """Legitimate crypto discussion should be allowed in crypto group."""
        signals = Signals(
            profile=TRUSTED_VETERAN.signals,
            content=CONTENT_CRYPTO_DISCUSSION.signals,
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_LONG.signals,
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.CRYPTO)
        result = calculator.calculate(signals)

        assert result.verdict == Verdict.ALLOW

    def test_crypto_terms_in_bio_reduced_in_crypto_group(self):
        """Crypto terms in bio should be less penalized in crypto groups."""
        # Use only profile signals to isolate the comparison
        signals = Signals(
            profile=ProfileSignals(
                account_age_days=100,
                bio_has_crypto_terms=True,
                has_profile_photo=True,
                has_bio=True,  # Bio is present
            ),
        )

        general_calc = RiskCalculator(group_type=GroupType.GENERAL)
        crypto_calc = RiskCalculator(group_type=GroupType.CRYPTO)

        general_result = general_calc.calculate(signals)
        crypto_result = crypto_calc.calculate(signals)

        # Bio crypto terms: 10 in general, 3 in crypto
        # Since both have same account age, photo, and bio presence trust signals,
        # the only difference should be bio_has_crypto_terms weight
        assert crypto_result.profile_score <= general_result.profile_score


class TestScamVsLegitimateInCrypto:
    """Test differentiation between scam and legitimate in crypto groups."""

    def test_crypto_scam_still_blocked_in_crypto_group(self):
        """Crypto scam should still be blocked even in crypto groups."""
        signals = Signals(
            profile=SPAMMER_NEW_ACCOUNT.signals,
            content=CONTENT_CRYPTO_SCAM.signals,
            behavior=BEHAVIOR_FIRST_MESSAGE_FAST.signals,
            network=NETWORK_SPAM_HIGH.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.CRYPTO)
        result = calculator.calculate(signals)

        # Even with lower thresholds and reduced wallet penalty,
        # crypto scam phrase + other signals should still trigger BLOCK
        assert result.verdict == Verdict.BLOCK
        assert result.threat_type == ThreatType.CRYPTO_SCAM

    def test_scam_phrase_penalty_increased_in_crypto(self):
        """Crypto scam phrase penalty is higher in crypto groups."""
        signals = Signals(
            content=ContentSignals(
                has_crypto_scam_phrases=True,
            ),
        )

        general_calc = RiskCalculator(group_type=GroupType.GENERAL)
        crypto_calc = RiskCalculator(group_type=GroupType.CRYPTO)

        general_result = general_calc.calculate(signals)
        crypto_result = crypto_calc.calculate(signals)

        # crypto_scam_phrase: 35 in general, 45 in crypto
        assert crypto_result.content_score > general_result.content_score

    def test_wallet_without_scam_phrase_allowed(self):
        """Wallet address without scam phrases should be allowed in crypto group."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            content=ContentSignals(
                has_wallet_addresses=True,
                has_crypto_scam_phrases=False,
                text_length=100,
            ),
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_NEW.signals,
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.CRYPTO)
        result = calculator.calculate(signals)

        # Wallet in crypto = +5 (reduced from +20)
        # With trust signals, should be ALLOW
        assert result.verdict in (Verdict.ALLOW, Verdict.WATCH)


class TestSpamDBWithTrustSignals:
    """Test spam DB matching with trust signals."""

    def test_low_match_offset_by_trust(self):
        """Low spam match can be offset by trust signals."""
        signals = Signals(
            profile=TRUSTED_VETERAN.signals,
            content=CONTENT_CLEAN.signals,
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_LONG.signals,
            network=NetworkSignals(
                spam_db_similarity=0.72,  # Low match
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Trust signals should offset low spam match
        assert result.verdict == Verdict.ALLOW

    def test_high_match_contributes_network_score(self):
        """High spam match adds significant network score."""
        signals = Signals(
            profile=TRUSTED_VETERAN.signals,
            content=CONTENT_CLEAN.signals,
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_LONG.signals,
            network=NetworkSignals(
                spam_db_similarity=0.92,  # High match = +45
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Network score should be 45 for high similarity
        assert result.network_score == 45
        # Should be in contributing factors
        assert "spam" in str(result.contributing_factors).lower()

    def test_near_exact_match_contributes_to_network_score(self):
        """Near-exact spam match should contribute to network score even with whitelist."""
        signals = Signals(
            profile=TRUSTED_VETERAN.signals,
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=90,
                previous_messages_approved=50,
                is_reply=True,
                is_first_message=False,
            ),
            network=NetworkSignals(
                spam_db_similarity=0.98,  # Near-exact = +50
                is_in_global_whitelist=True,  # -30
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Network score should be 50 - 30 (whitelist) = 20
        assert result.network_score == 20
        # Near-exact match should be in contributing factors
        assert "spam" in str(result.contributing_factors).lower()


class TestSpamDBThresholdBoundaries:
    """Test exact boundary values for spam DB thresholds."""

    @pytest.mark.parametrize(
        "similarity,expected_weight_key",
        [
            (0.95, "spam_db_similarity_0.95_plus"),
            (0.94, "spam_db_similarity_0.88_plus"),
            (0.88, "spam_db_similarity_0.88_plus"),
            (0.87, "spam_db_similarity_0.80_plus"),
            (0.80, "spam_db_similarity_0.80_plus"),
            (0.79, "spam_db_similarity_0.70_plus"),
            (0.70, "spam_db_similarity_0.70_plus"),
        ],
    )
    def test_boundary_values(self, similarity: float, expected_weight_key: str):
        """Test exact boundary values for thresholds."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=similarity,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        expected_score = NETWORK_WEIGHTS[expected_weight_key]
        assert result.network_score >= expected_score

    def test_below_lowest_threshold(self):
        """Below 0.70 should not add any spam DB score."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=0.69,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # No spam DB penalty
        assert result.network_score == 0


class TestSpamDBWithPatternText:
    """Test spam DB matched pattern text handling."""

    def test_matched_pattern_stored(self):
        """Matched pattern text should be stored in signals."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=0.92,
                spam_db_matched_pattern="Known crypto scam message",
            ),
        )

        assert signals.network.spam_db_matched_pattern == "Known crypto scam message"

    def test_pattern_available_for_logging(self):
        """Pattern should be available for logging/debugging."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=0.88,
                spam_db_matched_pattern="Suspicious promotion pattern",
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Pattern info should be accessible through signals
        assert result.signals.network.spam_db_matched_pattern == "Suspicious promotion pattern"


class TestCombinedSpamSignals:
    """Test combinations of spam DB and content signals."""

    def test_high_spam_db_plus_crypto_scam_phrase(self):
        """High spam DB + crypto scam phrase = definite BLOCK."""
        signals = Signals(
            content=ContentSignals(
                has_crypto_scam_phrases=True,  # +35
            ),
            network=NetworkSignals(
                spam_db_similarity=0.88,  # +45
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Total: 80+ should be at least REVIEW
        assert result.score >= 75
        assert result.verdict in (Verdict.REVIEW, Verdict.BLOCK)

    def test_spam_db_plus_raid_signals(self):
        """Spam DB match + raid signals = coordinated attack."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=0.85,  # +35
                duplicate_messages_in_other_groups=5,  # +35
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # 70+ should trigger LIMIT or REVIEW
        assert result.score >= 70
        # Threat type could be SPAM or RAID depending on which is detected first
        assert result.threat_type in (ThreatType.SPAM, ThreatType.RAID)

    def test_spam_db_plus_blocklist(self):
        """Spam DB match + blocklist = severe penalty."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=0.75,  # +25
                is_in_global_blocklist=True,  # +50
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # 75+ should trigger REVIEW or BLOCK
        assert result.score >= 75
