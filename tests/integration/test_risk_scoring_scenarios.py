"""
Integration Tests for Risk Scoring Scenarios

Tests the full scoring pipeline for each group_type (general, tech, deals, crypto).
Tests threshold transitions: ALLOW -> WATCH -> LIMIT -> REVIEW -> BLOCK.
Tests trust signal combinations and attack scenarios.

These tests verify the cumulative risk scoring system works correctly
across all scenarios defined in the fixtures.
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
    ThreatType,
    Verdict,
)
from tests.fixtures.scenarios import (
    BEHAVIOR_CHANNEL_SUBSCRIBER_LONG,
    BEHAVIOR_FIRST_MESSAGE_FAST,
    BEHAVIOR_FLOOD,
    BEHAVIOR_NEUTRAL,
    CONTENT_CLEAN,
    CONTENT_CRYPTO_SCAM,
    NETWORK_CLEAN,
    NETWORK_SPAM_HIGH,
    NETWORK_WHITELISTED,
    SCENARIO_BLOCKLISTED_USER,
    SCENARIO_CRYPTO_SCAM_ATTACK,
    SCENARIO_LINK_BOMB_RAID,
    SCENARIO_TRUSTED_SUBSCRIBER,
    SCENARIO_WHITELISTED_USER,
    SPAMMER_CRYPTO_BIO,
    SPAMMER_NEW_ACCOUNT,
    TRUSTED_REGULAR,
    TRUSTED_VETERAN,
    create_signals,
    get_all_scenarios,
    get_spam_scenarios,
    get_trust_scenarios,
)


class TestGroupTypeThresholds:
    """Test threshold behavior for each group type."""

    @pytest.mark.parametrize(
        "group_type,thresholds",
        [
            (GroupType.GENERAL, (30, 50, 75, 92)),
            (GroupType.TECH, (30, 50, 75, 92)),
            (GroupType.DEALS, (40, 60, 80, 95)),
            (GroupType.CRYPTO, (25, 45, 70, 90)),
        ],
    )
    def test_thresholds_are_correct(
        self, group_type: GroupType, thresholds: tuple[int, int, int, int]
    ):
        """Verify thresholds match expected values per group type."""
        assert THRESHOLDS[group_type] == thresholds

    @pytest.mark.parametrize("group_type", list(GroupType))
    def test_thresholds_ascending_order(self, group_type: GroupType):
        """Verify thresholds are in ascending order."""
        watch, limit, review, block = THRESHOLDS[group_type]
        assert watch < limit < review < block

    @pytest.mark.parametrize("group_type", list(GroupType))
    def test_calculator_loads_correct_weights(self, group_type: GroupType):
        """Verify calculator loads group-specific weights."""
        calculator = RiskCalculator(group_type=group_type)
        assert calculator.group_type == group_type


class TestVerdictTransitions:
    """Test score-to-verdict transitions for all group types."""

    @pytest.mark.parametrize(
        "group_type,score,expected_verdict",
        [
            # GENERAL thresholds (30, 50, 75, 92)
            (GroupType.GENERAL, 0, Verdict.ALLOW),
            (GroupType.GENERAL, 29, Verdict.ALLOW),
            (GroupType.GENERAL, 30, Verdict.WATCH),
            (GroupType.GENERAL, 49, Verdict.WATCH),
            (GroupType.GENERAL, 50, Verdict.LIMIT),
            (GroupType.GENERAL, 74, Verdict.LIMIT),
            (GroupType.GENERAL, 75, Verdict.REVIEW),
            (GroupType.GENERAL, 91, Verdict.REVIEW),
            (GroupType.GENERAL, 92, Verdict.BLOCK),
            (GroupType.GENERAL, 100, Verdict.BLOCK),
            # DEALS thresholds (40, 60, 80, 95) - higher tolerance
            (GroupType.DEALS, 39, Verdict.ALLOW),
            (GroupType.DEALS, 40, Verdict.WATCH),
            (GroupType.DEALS, 59, Verdict.WATCH),
            (GroupType.DEALS, 60, Verdict.LIMIT),
            (GroupType.DEALS, 79, Verdict.LIMIT),
            (GroupType.DEALS, 80, Verdict.REVIEW),
            (GroupType.DEALS, 94, Verdict.REVIEW),
            (GroupType.DEALS, 95, Verdict.BLOCK),
            # CRYPTO thresholds (25, 45, 70, 90) - stricter
            (GroupType.CRYPTO, 24, Verdict.ALLOW),
            (GroupType.CRYPTO, 25, Verdict.WATCH),
            (GroupType.CRYPTO, 44, Verdict.WATCH),
            (GroupType.CRYPTO, 45, Verdict.LIMIT),
            (GroupType.CRYPTO, 69, Verdict.LIMIT),
            (GroupType.CRYPTO, 70, Verdict.REVIEW),
            (GroupType.CRYPTO, 89, Verdict.REVIEW),
            (GroupType.CRYPTO, 90, Verdict.BLOCK),
            # TECH thresholds (30, 50, 75, 92) - same as GENERAL
            (GroupType.TECH, 29, Verdict.ALLOW),
            (GroupType.TECH, 30, Verdict.WATCH),
            (GroupType.TECH, 75, Verdict.REVIEW),
            (GroupType.TECH, 92, Verdict.BLOCK),
        ],
    )
    def test_score_to_verdict_mapping(
        self, group_type: GroupType, score: int, expected_verdict: Verdict
    ):
        """Verify scores map to correct verdicts."""
        calculator = RiskCalculator(group_type=group_type)
        verdict = calculator._score_to_verdict(score)
        assert verdict == expected_verdict, (
            f"Score {score} in {group_type} should be {expected_verdict}, got {verdict}"
        )


class TestTrustSignalCombinations:
    """Test combinations of trust signals and their cumulative effect."""

    def test_channel_subscriber_reduces_risk(self):
        """Channel subscription (-25) significantly reduces risk."""
        base_signals = create_signals(
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_LONG,
        )
        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(base_signals)

        # Channel subscriber with 30+ days = -25 -10 = -35
        assert result.behavior_score < 0
        assert "Channel subscriber" in str(result.mitigating_factors)

    def test_channel_subscriber_plus_approved_messages(self):
        """Combining channel sub + approved messages gives strong trust."""
        signals = Signals(
            profile=TRUSTED_REGULAR.signals,
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=30,
                previous_messages_approved=15,
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Channel sub: -25 -10, approved 10+: -15 = -50 behavior
        # Profile: old account, photo, etc = negative
        assert result.verdict == Verdict.ALLOW
        assert result.score < 10

    def test_premium_user_bonus(self):
        """Premium users get trust bonus."""
        signals = Signals(
            profile=ProfileSignals(
                account_age_days=100,
                is_premium=True,
                has_profile_photo=True,
                has_username=True,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert "Premium user" in str(result.mitigating_factors)
        assert result.profile_score < 0

    def test_old_account_plus_premium_plus_subscriber(self):
        """Maximum trust: old + premium + subscriber + approved = very low score."""
        signals = Signals(
            profile=ProfileSignals(
                account_age_days=1200,  # 3+ years
                is_premium=True,
                has_profile_photo=True,
                has_username=True,
            ),
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=90,
                previous_messages_approved=50,
                is_reply=True,
                is_reply_to_admin=True,
            ),
            network=NetworkSignals(
                is_in_global_whitelist=True,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # This should result in a very low or even 0 score (clamped)
        assert result.score == 0
        assert result.verdict == Verdict.ALLOW

    def test_trust_signals_offset_risk_signals(self):
        """Trust signals can offset moderate risk signals."""
        # A trusted user posting something that looks slightly promotional
        signals = Signals(
            profile=TRUSTED_VETERAN.signals,
            content=ContentSignals(
                url_count=2,
                has_shortened_urls=False,
                has_whitelisted_urls=True,
                has_money_patterns=True,  # Mentions prices
            ),
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_LONG.signals,
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Trust signals should keep score in ALLOW range
        assert result.verdict in (Verdict.ALLOW, Verdict.WATCH)
        assert result.score < 50


class TestAttackScenarios:
    """Test various attack patterns are properly detected."""

    def test_crypto_scam_attack_blocked(self):
        """Crypto scam attack should be blocked."""
        scenario = SCENARIO_CRYPTO_SCAM_ATTACK
        calculator = RiskCalculator(group_type=scenario.group_type)
        result = calculator.calculate(scenario.signals)

        assert result.verdict == Verdict.BLOCK
        assert result.score >= scenario.expected_verdict_range[0]
        assert result.threat_type == ThreatType.CRYPTO_SCAM

    def test_link_bomb_raid_blocked(self):
        """Link bomb raid should be blocked."""
        scenario = SCENARIO_LINK_BOMB_RAID
        calculator = RiskCalculator(group_type=scenario.group_type)
        result = calculator.calculate(scenario.signals)

        assert result.verdict == Verdict.BLOCK
        assert result.score >= 92
        # Threat type could be SPAM (for spam_db match) or RAID (for duplicates)
        assert result.threat_type in (ThreatType.SPAM, ThreatType.RAID)

    def test_blocklisted_user_penalized(self):
        """Blocklisted users should get heavy penalty."""
        scenario = SCENARIO_BLOCKLISTED_USER
        calculator = RiskCalculator(group_type=scenario.group_type)
        result = calculator.calculate(scenario.signals)

        assert result.score >= 50
        assert "blocklist" in str(result.contributing_factors).lower()

    def test_flood_attack_detected(self):
        """Message flooding should be detected."""
        signals = create_signals(
            profile=SPAMMER_NEW_ACCOUNT,
            behavior=BEHAVIOR_FLOOD,
            network=NETWORK_CLEAN,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.threat_type == ThreatType.FLOOD
        assert "flood" in str(result.contributing_factors).lower()

    def test_new_user_crypto_scam_phrase_blocked(self):
        """CRITICAL: New user + crypto scam phrase = BLOCK."""
        signals = Signals(
            profile=ProfileSignals(
                account_age_days=2,
                has_profile_photo=False,
            ),
            content=ContentSignals(
                has_crypto_scam_phrases=True,
                text_length=100,
            ),
            behavior=BehaviorSignals(
                is_first_message=True,
                time_to_first_message_seconds=20,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # account_age_under_7_days: +15
        # no_profile_photo: +8
        # crypto_scam_phrase: +35
        # is_first_message: +8
        # ttfm_under_30_seconds: +15
        # Total: 81+ -> at minimum REVIEW, likely BLOCK
        assert result.score >= 75
        assert result.threat_type == ThreatType.CRYPTO_SCAM


class TestTrustedUserScenarios:
    """Test that trusted users are not falsely blocked."""

    def test_trusted_subscriber_allowed(self):
        """Trusted channel subscriber should be allowed."""
        scenario = SCENARIO_TRUSTED_SUBSCRIBER
        calculator = RiskCalculator(group_type=scenario.group_type)
        result = calculator.calculate(scenario.signals)

        assert result.verdict == Verdict.ALLOW
        assert result.score <= scenario.expected_verdict_range[1]

    def test_whitelisted_user_allowed(self):
        """Global whitelist user should be allowed."""
        scenario = SCENARIO_WHITELISTED_USER
        calculator = RiskCalculator(group_type=scenario.group_type)
        result = calculator.calculate(scenario.signals)

        assert result.verdict == Verdict.ALLOW
        assert result.score < 30

    def test_trusted_user_with_multiple_links(self):
        """CRITICAL: Trusted user with 10+ approved messages posting 3 links = WATCH not BLOCK."""
        signals = Signals(
            profile=TRUSTED_VETERAN.signals,
            content=ContentSignals(
                url_count=3,
                has_whitelisted_urls=True,
                unique_domains=3,
            ),
            behavior=BehaviorSignals(
                previous_messages_approved=12,
                is_channel_subscriber=True,
                channel_subscription_duration_days=30,
            ),
            network=NETWORK_CLEAN.signals,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # Trust signals should heavily offset the link penalty
        assert result.verdict != Verdict.BLOCK
        assert result.verdict in (Verdict.ALLOW, Verdict.WATCH)


class TestGrayZoneBehavior:
    """Test gray zone scoring and LLM flag behavior."""

    def test_gray_zone_triggers_llm_flag(self):
        """Scores in gray zone (60-80) should flag for LLM review."""
        # Construct signals that land in gray zone
        signals = Signals(
            profile=ProfileSignals(account_age_days=30),
            content=ContentSignals(
                url_count=2,
                has_money_patterns=True,
                has_urgency_patterns=True,
            ),
            behavior=BehaviorSignals(
                is_first_message=True,
                time_to_first_message_seconds=120,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # If score is in gray zone, needs_llm should be True
        if 60 <= result.score <= 80:
            assert result.needs_llm is True

    def test_below_gray_zone_no_llm(self):
        """Scores below 60 should not need LLM review."""
        signals = create_signals(
            profile=TRUSTED_REGULAR,
            content=CONTENT_CLEAN,
            behavior=BEHAVIOR_NEUTRAL,
            network=NETWORK_CLEAN,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.score < 60
        assert result.needs_llm is False

    def test_above_gray_zone_no_llm(self):
        """Scores above 80 should not need LLM review (clear spam)."""
        signals = create_signals(
            profile=SPAMMER_CRYPTO_BIO,
            content=CONTENT_CRYPTO_SCAM,
            behavior=BEHAVIOR_FIRST_MESSAGE_FAST,
            network=NETWORK_SPAM_HIGH,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.score > 80
        assert result.needs_llm is False


class TestThreatTypeDetection:
    """Test correct threat type classification."""

    def test_crypto_scam_detection(self):
        """Crypto scam phrases should classify as CRYPTO_SCAM."""
        signals = Signals(
            content=ContentSignals(
                has_crypto_scam_phrases=True,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.threat_type == ThreatType.CRYPTO_SCAM

    def test_spam_db_match_detection(self):
        """High spam DB similarity should classify as SPAM."""
        signals = Signals(
            network=NetworkSignals(
                spam_db_similarity=0.92,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.threat_type == ThreatType.SPAM

    def test_flood_detection(self):
        """Message flooding should classify as FLOOD."""
        signals = Signals(
            behavior=BehaviorSignals(
                messages_in_last_hour=15,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.threat_type == ThreatType.FLOOD

    def test_raid_detection(self):
        """Duplicate across groups should classify as RAID."""
        signals = Signals(
            network=NetworkSignals(
                duplicate_messages_in_other_groups=5,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.threat_type == ThreatType.RAID

    def test_promotion_detection(self):
        """Multiple links with money patterns should classify as PROMOTION."""
        signals = Signals(
            content=ContentSignals(
                url_count=4,
                has_money_patterns=True,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert result.threat_type == ThreatType.PROMOTION


class TestScoreClamping:
    """Test score is properly clamped to 0-100 range."""

    def test_score_clamped_to_100(self):
        """Extreme spam signals should clamp to 100."""
        extreme_signals = Signals(
            profile=ProfileSignals(
                account_age_days=0,
                username_has_random_chars=True,
                name_has_emoji_spam=True,
                bio_has_crypto_terms=True,
                bio_has_links=True,
            ),
            content=ContentSignals(
                has_crypto_scam_phrases=True,
                has_wallet_addresses=True,
                url_count=5,
                has_shortened_urls=True,
                has_suspicious_tld=True,
                caps_ratio=0.9,
                emoji_count=25,
            ),
            behavior=BehaviorSignals(
                is_first_message=True,
                time_to_first_message_seconds=5,
                join_to_message_seconds=5,
                previous_messages_blocked=5,
            ),
            network=NetworkSignals(
                spam_db_similarity=0.99,
                duplicate_messages_in_other_groups=10,
                is_in_global_blocklist=True,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(extreme_signals)

        assert result.score == 100
        assert result.verdict == Verdict.BLOCK

    def test_score_clamped_to_zero(self):
        """Maximum trust signals should clamp to 0."""
        max_trust_signals = Signals(
            profile=ProfileSignals(
                account_age_days=3650,  # 10 years
                is_premium=True,
                has_profile_photo=True,
                has_username=True,
                has_bio=True,
            ),
            behavior=BehaviorSignals(
                is_channel_subscriber=True,
                channel_subscription_duration_days=365,
                previous_messages_approved=100,
                is_reply=True,
                is_reply_to_admin=True,
            ),
            network=NetworkSignals(
                is_in_global_whitelist=True,
                groups_in_common=10,
            ),
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(max_trust_signals)

        assert result.score == 0
        assert result.verdict == Verdict.ALLOW


class TestScoreBreakdown:
    """Test score breakdown is correctly calculated."""

    def test_breakdown_categories_present(self):
        """Result should include all category scores."""
        signals = create_signals(
            profile=TRUSTED_REGULAR,
            content=CONTENT_CLEAN,
            behavior=BEHAVIOR_NEUTRAL,
            network=NETWORK_CLEAN,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        # All categories should be present
        assert hasattr(result, "profile_score")
        assert hasattr(result, "content_score")
        assert hasattr(result, "behavior_score")
        assert hasattr(result, "network_score")

    def test_breakdown_sums_to_total_before_clamp(self):
        """Category scores should sum to total before clamping."""
        signals = create_signals(
            profile=TRUSTED_REGULAR,
            content=CONTENT_CLEAN,
            behavior=BEHAVIOR_NEUTRAL,
            network=NETWORK_CLEAN,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        raw_sum = (
            result.profile_score
            + result.content_score
            + result.behavior_score
            + result.network_score
        )

        # Final score should be clamped version of raw sum
        expected = max(0, min(100, raw_sum))
        assert result.score == expected

    def test_contributing_factors_populated_for_spam(self):
        """Spam messages should have contributing factors."""
        signals = create_signals(
            profile=SPAMMER_CRYPTO_BIO,
            content=CONTENT_CRYPTO_SCAM,
            behavior=BEHAVIOR_FIRST_MESSAGE_FAST,
            network=NETWORK_SPAM_HIGH,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert len(result.contributing_factors) > 0

    def test_mitigating_factors_populated_for_trusted(self):
        """Trusted users should have mitigating factors."""
        signals = create_signals(
            profile=TRUSTED_VETERAN,
            behavior=BEHAVIOR_CHANNEL_SUBSCRIBER_LONG,
            network=NETWORK_WHITELISTED,
        )

        calculator = RiskCalculator(group_type=GroupType.GENERAL)
        result = calculator.calculate(signals)

        assert len(result.mitigating_factors) > 0


class TestAllScenarios:
    """Run all defined scenarios through the calculator."""

    @pytest.mark.parametrize(
        "scenario",
        get_all_scenarios(),
        ids=lambda s: s.name,
    )
    def test_scenario_score_in_expected_range(self, scenario):
        """Each scenario should score within expected range."""
        calculator = RiskCalculator(group_type=scenario.group_type)
        result = calculator.calculate(scenario.signals)

        min_score, max_score = scenario.expected_verdict_range
        assert min_score <= result.score <= max_score, (
            f"Scenario '{scenario.name}' scored {result.score}, expected {min_score}-{max_score}"
        )

    @pytest.mark.parametrize(
        "scenario",
        get_spam_scenarios(),
        ids=lambda s: s.name,
    )
    def test_spam_scenarios_not_allowed(self, scenario):
        """Spam scenarios should not get ALLOW verdict."""
        calculator = RiskCalculator(group_type=scenario.group_type)
        result = calculator.calculate(scenario.signals)

        assert result.verdict != Verdict.ALLOW, (
            f"Spam scenario '{scenario.name}' got ALLOW with score {result.score}"
        )

    @pytest.mark.parametrize(
        "scenario",
        get_trust_scenarios(),
        ids=lambda s: s.name,
    )
    def test_trust_scenarios_allowed(self, scenario):
        """Trust scenarios should get ALLOW verdict."""
        calculator = RiskCalculator(group_type=scenario.group_type)
        result = calculator.calculate(scenario.signals)

        assert result.verdict == Verdict.ALLOW, (
            f"Trust scenario '{scenario.name}' got {result.verdict} with score {result.score}"
        )
