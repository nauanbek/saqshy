"""
SAQSHY Risk Calculator

Calculates cumulative risk score from all signals.

The RiskCalculator is the heart of SAQSHY's spam detection system.
It combines signals from profile, content, behavior, and network analyzers
to produce a final risk score between 0-100.

Key principles:
1. No single signal is decisive - cumulative scoring only
2. Trust signals (negative weights) can offset risk signals
3. Group type determines threshold calibration
4. Scores are clamped to 0-100 range
"""

from dataclasses import dataclass, field

from saqshy.core.constants import (
    BEHAVIOR_WEIGHTS,
    CONTENT_WEIGHTS,
    CRYPTO_WEIGHT_OVERRIDES,
    DEALS_WEIGHT_OVERRIDES,
    LLM_GRAY_ZONE,
    NETWORK_WEIGHTS,
    PROFILE_WEIGHTS,
    TECH_WEIGHT_OVERRIDES,
    THRESHOLDS,
)
from saqshy.core.sandbox import TRUST_SCORE_ADJUSTMENTS, TrustLevel
from saqshy.core.types import (
    BehaviorSignals,
    ContentSignals,
    GroupType,
    NetworkSignals,
    ProfileSignals,
    RiskResult,
    Signals,
    ThreatType,
    Verdict,
)


@dataclass
class ScoreBreakdown:
    """Detailed breakdown of score calculation."""

    profile_score: int = 0
    content_score: int = 0
    behavior_score: int = 0
    network_score: int = 0
    total_score: int = 0
    contributing_factors: list[str] = field(default_factory=list)
    mitigating_factors: list[str] = field(default_factory=list)


class RiskCalculator:
    """
    Calculates risk score from combined signals.

    The calculator applies group-type-specific weights and thresholds
    to produce a verdict for each message.

    Trust Level Integration:
        The calculator applies TRUST_SCORE_ADJUSTMENTS based on user's trust level:
        - ESTABLISHED: -20 (significantly reduces risk)
        - TRUSTED: -10 (reduces risk)
        - PROVISIONAL: 0 (neutral)
        - UNTRUSTED: +5 (slightly increases risk)

        This allows trusted users to have lower risk scores.
    """

    def __init__(
        self,
        group_type: GroupType = GroupType.GENERAL,
        trust_level: TrustLevel = TrustLevel.UNTRUSTED,
    ):
        """
        Initialize the risk calculator.

        Args:
            group_type: The type of group, affects weights and thresholds.
            trust_level: User's trust level, affects score adjustment.
        """
        self.group_type = group_type
        self.trust_level = trust_level
        self._load_weights()
        self._validate_weights()

    def _load_weights(self) -> None:
        """Load and adjust weights based on group type."""
        # Start with base weights
        self.profile_weights = PROFILE_WEIGHTS.copy()
        self.content_weights = CONTENT_WEIGHTS.copy()
        self.behavior_weights = BEHAVIOR_WEIGHTS.copy()
        self.network_weights = NETWORK_WEIGHTS.copy()

        # Apply group-type-specific overrides
        if self.group_type == GroupType.DEALS:
            self.content_weights.update(DEALS_WEIGHT_OVERRIDES)
        elif self.group_type == GroupType.CRYPTO:
            self.content_weights.update(CRYPTO_WEIGHT_OVERRIDES)
        elif self.group_type == GroupType.TECH:
            self.content_weights.update(TECH_WEIGHT_OVERRIDES)

    def _validate_weights(self) -> None:
        """
        Validate all weight values are reasonable.

        Raises:
            ValueError: If any weight has unreasonable magnitude (>100).
            TypeError: If any weight is not numeric.
        """
        all_weights = [
            ("profile", self.profile_weights),
            ("content", self.content_weights),
            ("behavior", self.behavior_weights),
            ("network", self.network_weights),
        ]

        for category, weights in all_weights:
            for key, value in weights.items():
                if not isinstance(value, (int, float)):
                    raise TypeError(
                        f"Weight '{category}.{key}' must be numeric, got {type(value).__name__}"
                    )
                if abs(value) > 100:
                    raise ValueError(
                        f"Weight '{category}.{key}' has unreasonable magnitude: {value}"
                    )

        # Validate group type has thresholds defined
        if self.group_type not in THRESHOLDS:
            raise ValueError(f"Unknown group_type: {self.group_type}")

    def calculate(self, signals: Signals) -> RiskResult:
        """
        Calculate risk score from signals.

        Args:
            signals: Combined signals from all analyzers.

        Returns:
            RiskResult with score, verdict, and breakdown.
        """
        breakdown = ScoreBreakdown()

        # Calculate individual category scores
        breakdown.profile_score = self._calculate_profile_score(signals.profile, breakdown)
        breakdown.content_score = self._calculate_content_score(signals.content, breakdown)
        breakdown.behavior_score = self._calculate_behavior_score(
            signals.behavior, breakdown, signals.profile
        )
        breakdown.network_score = self._calculate_network_score(signals.network, breakdown)

        # Sum all scores
        raw_score = (
            breakdown.profile_score
            + breakdown.content_score
            + breakdown.behavior_score
            + breakdown.network_score
        )

        # Apply trust level adjustment
        trust_adjustment = TRUST_SCORE_ADJUSTMENTS.get(self.trust_level.value, 0)
        raw_score += trust_adjustment

        # Record trust adjustment in breakdown
        if trust_adjustment != 0:
            if trust_adjustment < 0:
                breakdown.mitigating_factors.append(
                    f"Trust level: {self.trust_level.value} ({trust_adjustment})"
                )
            else:
                breakdown.contributing_factors.append(
                    f"Trust level: {self.trust_level.value} (+{trust_adjustment})"
                )

        # Clamp to 0-100 range (preserve raw_score for diagnostics)
        # When raw_score < 0, it indicates strong trust signals were applied
        # When raw_score > 100, it indicates severe risk signals were detected
        final_score = max(0, min(100, raw_score))
        breakdown.total_score = final_score

        # Determine verdict based on thresholds
        verdict = self._score_to_verdict(final_score)

        # Detect threat type
        threat_type = self._detect_threat_type(signals, final_score)

        # Check if LLM review is needed (gray zone)
        needs_llm = LLM_GRAY_ZONE[0] <= final_score <= LLM_GRAY_ZONE[1]

        return RiskResult(
            score=final_score,
            raw_score=raw_score,  # Preserve unclamped score for diagnostics
            verdict=verdict,
            threat_type=threat_type,
            profile_score=breakdown.profile_score,
            content_score=breakdown.content_score,
            behavior_score=breakdown.behavior_score,
            network_score=breakdown.network_score,
            signals=signals,
            needs_llm=needs_llm,
            contributing_factors=breakdown.contributing_factors,
            mitigating_factors=breakdown.mitigating_factors,
        )

    def _calculate_profile_score(self, profile: ProfileSignals, breakdown: ScoreBreakdown) -> int:
        """Calculate profile risk score."""
        score = 0

        # Account age scoring
        if profile.account_age_days < 1:
            score += self.profile_weights.get("account_age_under_24_hours", 25)
            breakdown.contributing_factors.append("Account created less than 24 hours ago")
        elif profile.account_age_days < 7:
            score += self.profile_weights.get("account_age_under_7_days", 15)
            breakdown.contributing_factors.append("Account less than 7 days old")
        elif profile.account_age_days >= 365 * 3:
            score += self.profile_weights.get("account_age_3_years", -15)
            breakdown.mitigating_factors.append("Account 3+ years old")
        elif profile.account_age_days >= 365:
            score += self.profile_weights.get("account_age_1_year", -10)
            breakdown.mitigating_factors.append("Account 1+ year old")

        # Profile completeness
        if profile.has_profile_photo:
            score += self.profile_weights.get("has_profile_photo", -5)
        else:
            score += self.profile_weights.get("no_profile_photo", 8)
            breakdown.contributing_factors.append("No profile photo")

        if profile.has_username:
            score += self.profile_weights.get("has_username", -3)
        else:
            score += self.profile_weights.get("no_username", 5)

        if profile.is_premium:
            score += self.profile_weights.get("is_premium", -10)
            breakdown.mitigating_factors.append("Premium user")

        # Risk signals
        if profile.username_has_random_chars:
            score += self.profile_weights.get("username_random_chars", 12)
            breakdown.contributing_factors.append("Username contains random characters")

        if profile.name_has_emoji_spam:
            score += self.profile_weights.get("name_has_emoji_spam", 15)
            breakdown.contributing_factors.append("Name contains emoji spam")

        if profile.bio_has_crypto_terms:
            score += self.profile_weights.get("bio_has_crypto_terms", 10)

        if profile.bio_has_links:
            score += self.profile_weights.get("bio_has_links", 8)

        return score

    def _calculate_content_score(self, content: ContentSignals, breakdown: ScoreBreakdown) -> int:
        """Calculate content risk score."""
        score = 0

        # Crypto scam phrases (highest risk)
        if content.has_crypto_scam_phrases:
            score += self.content_weights.get("crypto_scam_phrase", 35)
            breakdown.contributing_factors.append("Contains crypto scam phrases")

        # Wallet addresses
        if content.has_wallet_addresses:
            score += self.content_weights.get("wallet_address", 20)
            breakdown.contributing_factors.append("Contains wallet address")

        # URL analysis
        if content.url_count > 0:
            score += self.content_weights.get("has_urls", 5)

            if content.url_count >= 3:
                score += self.content_weights.get("multiple_urls_3_plus", 12)
                breakdown.contributing_factors.append("Multiple URLs")

            if content.has_shortened_urls:
                score += self.content_weights.get("has_shortened_urls", 15)
                breakdown.contributing_factors.append("Shortened URLs")

            if content.has_suspicious_tld:
                score += self.content_weights.get("has_suspicious_tld", 18)
                breakdown.contributing_factors.append("Suspicious TLD")

            if content.has_whitelisted_urls:
                score += self.content_weights.get("has_whitelisted_domains", -8)
                breakdown.mitigating_factors.append("Whitelisted domains")

        # Text patterns
        if content.caps_ratio > 0.8:
            score += self.content_weights.get("excessive_caps_80_percent", 15)
            breakdown.contributing_factors.append("Excessive caps")
        elif content.caps_ratio > 0.5:
            score += self.content_weights.get("excessive_caps_50_percent", 8)

        if content.emoji_count >= 20:
            score += self.content_weights.get("excessive_emoji_20_plus", 18)
        elif content.emoji_count >= 10:
            score += self.content_weights.get("excessive_emoji_10_plus", 10)

        # Other patterns
        if content.has_money_patterns:
            score += self.content_weights.get("money_pattern", 12)

        if content.has_urgency_patterns:
            score += self.content_weights.get("urgency_pattern", 10)

        if content.has_phone_numbers:
            score += self.content_weights.get("phone_number", 8)

        # Forward signals
        if content.forward_from_channel:
            score += self.content_weights.get("is_forward_from_channel", 12)
        elif content.has_forward:
            score += self.content_weights.get("is_forward", 5)

        return score

    def _calculate_behavior_score(
        self,
        behavior: BehaviorSignals,
        breakdown: ScoreBreakdown,
        profile: ProfileSignals | None = None,
    ) -> int:
        """Calculate behavior risk score."""
        score = 0

        # Channel subscription - conditional trust signal
        # Reduced base bonus and capped for new accounts to prevent bypass
        if behavior.is_channel_subscriber:
            # Base bonus reduced from -25 to -15
            base_bonus = -15

            # Additional bonus for subscription duration
            duration_bonus = 0
            if behavior.channel_subscription_duration_days >= 30:
                duration_bonus = -10  # Total: -25 for 30+ days subscriber
            elif behavior.channel_subscription_duration_days >= 7:
                duration_bonus = -5  # Total: -20 for 7+ days subscriber

            total_bonus = base_bonus + duration_bonus

            # Cap bonus for new accounts (< 7 days old) to prevent compromised account bypass
            if profile is not None and profile.account_age_days < 7:
                # New accounts get max -10 even if channel subscriber
                total_bonus = max(total_bonus, -10)
                breakdown.mitigating_factors.append(
                    f"Channel subscriber (capped to {total_bonus} for new account)"
                )
            else:
                breakdown.mitigating_factors.append(
                    f"Channel subscriber ({total_bonus} trust bonus)"
                )

            score += total_bonus

        # Message history
        if behavior.previous_messages_approved >= 10:
            score += self.behavior_weights.get("previous_messages_approved_10_plus", -15)
            breakdown.mitigating_factors.append("10+ approved messages")
        elif behavior.previous_messages_approved >= 5:
            score += self.behavior_weights.get("previous_messages_approved_5_plus", -10)
        elif behavior.previous_messages_approved >= 1:
            score += self.behavior_weights.get("previous_messages_approved_1_plus", -5)

        # Reply signals
        if behavior.is_reply:
            score += self.behavior_weights.get("is_reply", -3)
            if behavior.is_reply_to_admin:
                score += self.behavior_weights.get("is_reply_to_admin", -5)

        # Group membership duration - longer membership = more trust
        if behavior.group_membership_days >= 90:
            score += self.behavior_weights.get("group_member_90_days", -15)
            breakdown.mitigating_factors.append("Group member for 90+ days")
        elif behavior.group_membership_days >= 30:
            score += self.behavior_weights.get("group_member_30_days", -10)
            breakdown.mitigating_factors.append("Group member for 30+ days")
        elif behavior.group_membership_days >= 7:
            score += self.behavior_weights.get("group_member_7_days", -5)

        # Risk signals
        if behavior.is_first_message:
            score += self.behavior_weights.get("is_first_message", 8)

        # Time to first message
        if behavior.time_to_first_message_seconds is not None:
            if behavior.time_to_first_message_seconds < 30:
                score += self.behavior_weights.get("ttfm_under_30_seconds", 15)
                breakdown.contributing_factors.append("Very fast first message")
            elif behavior.time_to_first_message_seconds < 300:
                score += self.behavior_weights.get("ttfm_under_5_minutes", 8)

        # Join to message timing
        if behavior.join_to_message_seconds is not None:
            if behavior.join_to_message_seconds < 10:
                score += self.behavior_weights.get("join_to_message_under_10_seconds", 18)
                breakdown.contributing_factors.append("Message immediately after join")

        # Flood detection
        if behavior.messages_in_last_hour >= 10:
            score += self.behavior_weights.get("messages_in_hour_10_plus", 20)
            breakdown.contributing_factors.append("Message flood")
        elif behavior.messages_in_last_hour >= 5:
            score += self.behavior_weights.get("messages_in_hour_5_plus", 12)

        # Previous violations
        if behavior.previous_messages_blocked > 0:
            score += self.behavior_weights.get("previous_messages_blocked", 25)
            breakdown.contributing_factors.append("Previously blocked messages")

        if behavior.previous_messages_flagged > 0:
            score += self.behavior_weights.get("previous_messages_flagged", 15)

        return score

    def _calculate_network_score(self, network: NetworkSignals, breakdown: ScoreBreakdown) -> int:
        """Calculate network risk score."""
        score = 0

        # Global lists
        if network.is_in_global_whitelist:
            score += self.network_weights.get("is_in_global_whitelist", -30)
            breakdown.mitigating_factors.append("In global whitelist")

        if network.is_in_global_blocklist:
            score += self.network_weights.get("is_in_global_blocklist", 50)
            breakdown.contributing_factors.append("In global blocklist")

        # Spam database similarity
        if network.spam_db_similarity >= 0.95:
            score += self.network_weights.get("spam_db_similarity_0.95_plus", 50)
            breakdown.contributing_factors.append("Near-exact spam match")
        elif network.spam_db_similarity >= 0.88:
            score += self.network_weights.get("spam_db_similarity_0.88_plus", 45)
            breakdown.contributing_factors.append("High spam similarity")
        elif network.spam_db_similarity >= 0.80:
            score += self.network_weights.get("spam_db_similarity_0.80_plus", 35)
        elif network.spam_db_similarity >= 0.70:
            score += self.network_weights.get("spam_db_similarity_0.70_plus", 25)

        # Cross-group behavior - tiered duplicate detection
        dup_count = network.duplicate_messages_in_other_groups
        if dup_count >= 5:
            score += self.network_weights.get("duplicate_in_5_plus_groups", 50)
            breakdown.contributing_factors.append(
                f"Duplicate in {dup_count}+ groups (coordinated spam attack)"
            )
        elif dup_count >= 3:
            score += self.network_weights.get("duplicate_in_3_groups", 35)
            breakdown.contributing_factors.append(f"Duplicate in {dup_count} groups")
        elif dup_count >= 2:
            score += self.network_weights.get("duplicate_in_2_groups", 20)
            breakdown.contributing_factors.append(f"Duplicate in {dup_count} groups")
        elif dup_count > 0:
            # Single duplicate - lower risk but still suspicious
            score += 10
            breakdown.contributing_factors.append("Message seen in another group")

        if network.blocked_in_other_groups > 0:
            score += self.network_weights.get("blocked_in_other_groups", 40)
            breakdown.contributing_factors.append("Blocked in other groups")

        if network.flagged_in_other_groups > 0:
            score += self.network_weights.get("flagged_in_other_groups", 25)

        # Groups in common (weak trust signal)
        if network.groups_in_common >= 5:
            score += self.network_weights.get("groups_in_common_5_plus", -5)

        return score

    def _score_to_verdict(self, score: int) -> Verdict:
        """Convert score to verdict based on group thresholds.

        Raises:
            ValueError: If thresholds tuple has wrong length.
            KeyError: If group_type is not in THRESHOLDS.
        """
        if self.group_type not in THRESHOLDS:
            raise KeyError(f"Unknown group_type: {self.group_type}")

        thresholds = THRESHOLDS[self.group_type]

        # Validate thresholds tuple has exactly 4 values
        if len(thresholds) != 4:
            raise ValueError(
                f"THRESHOLDS[{self.group_type}] must have exactly 4 values "
                f"(watch, limit, review, block), got {len(thresholds)}"
            )

        watch, limit, review, block = thresholds

        if score >= block:
            return Verdict.BLOCK
        elif score >= review:
            return Verdict.REVIEW
        elif score >= limit:
            return Verdict.LIMIT
        elif score >= watch:
            return Verdict.WATCH
        else:
            return Verdict.ALLOW

    def _detect_threat_type(self, signals: Signals, score: int) -> ThreatType:
        """Detect the type of threat based on signals.

        Priority order (most specific to least specific):
        1. CRYPTO_SCAM: Crypto scam phrases detected (highest priority)
        2. SCAM: Wallet addresses with high score
        3. PHISHING: Suspicious URLs/patterns (future expansion)
        4. RAID: Coordinated cross-group attack
        5. FLOOD: Message burst from single user
        6. SPAM: High spam DB similarity
        7. PROMOTION: Commercial content
        8. UNKNOWN: Score >= 30 but no specific signals
        9. NONE: Score < 30
        """
        if score < 30:
            return ThreatType.NONE

        # Collect candidate threat types with priority scores
        candidates: list[tuple[int, ThreatType]] = []

        # Priority 1: Crypto scam (highest specificity)
        if signals.content.has_crypto_scam_phrases:
            candidates.append((100, ThreatType.CRYPTO_SCAM))

        # Priority 2: Scam with wallet addresses
        if signals.content.has_wallet_addresses and score >= 50:
            candidates.append((90, ThreatType.SCAM))

        # Priority 3: Coordinated raid (cross-group attack)
        if signals.network.duplicate_messages_in_other_groups >= 3:
            candidates.append((85, ThreatType.RAID))
        elif signals.network.duplicate_messages_in_other_groups > 0:
            candidates.append((70, ThreatType.RAID))

        # Priority 4: Flood (message burst)
        if signals.behavior.messages_in_last_hour >= 10:
            candidates.append((75, ThreatType.FLOOD))

        # Priority 5: Spam DB match
        if signals.network.spam_db_similarity >= 0.95:
            candidates.append((95, ThreatType.SPAM))  # Very high similarity = high priority
        elif signals.network.spam_db_similarity >= 0.80:
            candidates.append((65, ThreatType.SPAM))

        # Priority 6: Promotional content (lowest priority)
        if signals.content.url_count >= 3 or signals.content.has_money_patterns:
            candidates.append((50, ThreatType.PROMOTION))

        # Return highest priority threat type
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            return candidates[0][1]

        return ThreatType.UNKNOWN
