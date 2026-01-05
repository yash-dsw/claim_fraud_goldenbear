"""
Rule-based fraud detection system.
Applies predefined rules to detect potential fraud indicators.
"""

from datetime import datetime
from utils import calculate_days_between, parse_amount


class RuleBasedDetector:
    """Implements rule-based fraud detection logic."""
    
    def __init__(self):
        self.flags = []
    
    def detect(self, policy_data, claim_data):
        """
        Run all rule-based fraud detection checks.
        Returns a list of fraud flags.
        """
        self.flags = []
        
        # Run all detection rules
        self._check_timing_red_flags(policy_data, claim_data)
        self._check_loss_history(policy_data, claim_data)
        self._check_amount_anomalies(policy_data, claim_data)
        self._check_fire_protection_inconsistencies(policy_data, claim_data)
        self._check_new_business_early_claim(policy_data, claim_data)
        self._check_building_condition_inconsistencies(policy_data, claim_data)
        self._check_multiple_recent_losses(policy_data)
        
        return self.flags
    
    def _add_flag(self, description, risk_level, details=""):
        """Add a fraud flag to the list."""
        self.flags.append({
            "description": description,
            "risk_level": risk_level,  # LOW, MODERATE, HIGH, CRITICAL
            "details": details
        })
    
    def _check_unauthorized_claimant(self, policy_data, claim_data):
        """Check if claim is filed by someone other than the named insured."""
        named_insured = policy_data.get("named_insured", "").strip().lower()
        claimant_name = claim_data.get("insured_name", "").strip().lower()
        
        if named_insured and claimant_name:
            # Check if names are significantly different (not just capitalization)
            if named_insured != claimant_name and named_insured not in claimant_name:
                self._add_flag(
                    "Claim filed by unauthorized person",
                    "CRITICAL",
                    f"Policy holder: {policy_data.get('named_insured', 'N/A')}, Claimant: {claim_data.get('insured_name', 'N/A')}"
                )
    
    def _check_timing_red_flags(self, policy_data, claim_data):
        """Check for suspicious timing between policy and claim."""
        policy_date = policy_data.get("effective_date", "")
        claim_date = claim_data.get("date_of_loss", "")
        
        if policy_date and claim_date:
            days = calculate_days_between(policy_date, claim_date)
            
            if days is not None:
                # Claim within 30 days of policy inception
                if days <= 30:
                    self._add_flag(
                        "Claim occurred within 30 days of policy effective date",
                        "HIGH",
                        f"Only {days} days between policy start and loss"
                    )
                # Claim within 90 days
                elif days <= 90:
                    self._add_flag(
                        "Claim occurred within 90 days of policy effective date",
                        "MODERATE",
                        f"{days} days between policy start and loss"
                    )
    
    def _check_loss_history(self, policy_data, claim_data):
        """Check for concerning loss history patterns."""
        loss_history = policy_data.get("loss_history", [])
        loss_count = len(loss_history)
        
        # Multiple losses in recent history
        if loss_count >= 5:
            self._add_flag(
                "Excessive prior losses",
                "HIGH",
                f"{loss_count} losses in history"
            )
        elif loss_count >= 3:
            self._add_flag(
                "Multiple prior losses reported",
                "MODERATE",
                f"{loss_count} losses in history"
            )
        
        # Check for similar loss types
        claim_type = claim_data.get("claim_type", "").lower()
        if claim_type and loss_history:
            similar_losses = [loss for loss in loss_history 
                            if claim_type in loss.get("type", "").lower()]
            if len(similar_losses) >= 2:
                self._add_flag(
                    "Pattern of similar loss types",
                    "HIGH",
                    f"Current claim type '{claim_type}' matches {len(similar_losses)} prior losses"
                )
    
    def _check_amount_anomalies(self, policy_data, claim_data):
        """Check for unusual claim amounts."""
        estimated_loss = claim_data.get("estimated_loss_amount", "")
        
        if estimated_loss:
            amount = parse_amount(estimated_loss)
            
            # Very high claim amounts warrant scrutiny
            if amount >= 500000:
                self._add_flag(
                    "High-value claim requiring enhanced scrutiny",
                    "MODERATE",
                    f"Claim amount: ${amount:,.2f}"
                )
            
            # Check if claim is suspiciously round number
            if amount > 0 and amount % 10000 == 0:
                self._add_flag(
                    "Claim amount is a suspiciously round number",
                    "LOW",
                    f"Exact amount: ${amount:,.2f}"
                )
    
    def _check_fire_protection_inconsistencies(self, policy_data, claim_data):
        """Check for fire-related inconsistencies."""
        claim_type = claim_data.get("claim_type", "").lower()
        cause_of_loss = claim_data.get("cause_of_loss", "").lower()
        loss_description = claim_data.get("loss_description", "").lower()
        
        # If this is a fire claim (check type, cause, or description)
        if "fire" in claim_type or "fire" in cause_of_loss or "fire" in loss_description:
            # Check fire protection details from policy
            fire_hydrant_dist = policy_data.get("distance_to_fire_hydrant", "")
            sprinklered = policy_data.get("sprinklered_percent", "")
            fire_protection_class = policy_data.get("fire_protection_class", "")
            
            # If policy indicated good fire protection
            if fire_hydrant_dist:
                try:
                    dist = float(fire_hydrant_dist)
                    if dist <= 500:  # Within 500 feet
                        self._add_flag(
                            "Fire claim despite nearby fire hydrant",
                            "MODERATE",
                            f"Fire hydrant only {dist} feet away per policy"
                        )
                except:
                    pass
            
            # High sprinkler coverage but still had fire
            if sprinklered:
                try:
                    # Handle both "38.25" and "38.25%" formats
                    percent_str = str(sprinklered).replace('%', '').strip()
                    percent = float(percent_str)
                    if percent >= 80:
                        self._add_flag(
                            "Fire claim despite high sprinkler coverage",
                            "MODERATE",
                            f"Building {percent}% sprinklered per policy"
                        )
                except:
                    pass
    
    def _check_new_business_early_claim(self, policy_data, claim_data):
        """Check if new business has early claim."""
        years_in_business = policy_data.get("years_in_business", "")
        policy_date = policy_data.get("effective_date", "")
        claim_date = claim_data.get("date_of_loss", "")
        
        try:
            years = int(years_in_business)
            # New business (< 2 years)
            if years < 2:
                if policy_date and claim_date:
                    days = calculate_days_between(policy_date, claim_date)
                    if days and days <= 60:
                        self._add_flag(
                            "New business with early claim",
                            "HIGH",
                            f"Business only {years} years old, claim within {days} days"
                        )
        except:
            pass
    
    def _check_building_condition_inconsistencies(self, policy_data, claim_data):
        """Check for building condition inconsistencies."""
        year_built = policy_data.get("year_built", "")
        wiring_year = policy_data.get("wiring_year", "")
        roofing_year = policy_data.get("roofing_year", "")
        plumbing_year = policy_data.get("plumbing_year", "")
        
        claim_cause = claim_data.get("cause_of_loss", "").lower()
        loss_description = claim_data.get("loss_description", "").lower()
        
        # Recent improvements but related claim
        current_year = datetime.now().year
        
        # Check electrical/fire claims
        if "electrical" in claim_cause or "fire" in claim_cause or "electrical" in loss_description or "fire" in loss_description:
            if wiring_year:
                try:
                    wiring_age = current_year - int(wiring_year)
                    if wiring_age <= 2:
                        self._add_flag(
                            "Electrical/fire claim despite recent wiring update",
                            "HIGH",
                            f"Wiring updated in {wiring_year} per policy"
                        )
                except:
                    pass
        
        # Check roof/water claims
        if "roof" in claim_cause or "water" in claim_cause or "leak" in claim_cause or "roof" in loss_description or "water" in loss_description or "leak" in loss_description:
            if roofing_year:
                try:
                    roof_age = current_year - int(roofing_year)
                    if roof_age <= 2:
                        self._add_flag(
                            "Roof/water claim despite recent roofing update",
                            "MODERATE",
                            f"Roofing updated in {roofing_year} per policy"
                        )
                except:
                    pass
        
        # Check plumbing/water claims
        if "plumbing" in claim_cause or "water" in claim_cause or "plumbing" in loss_description:
            if plumbing_year:
                try:
                    plumbing_age = current_year - int(plumbing_year)
                    if plumbing_age <= 2:
                        self._add_flag(
                            "Plumbing/water claim despite recent plumbing update",
                            "MODERATE",
                            f"Plumbing updated in {plumbing_year} per policy"
                        )
                except:
                    pass
    
    def _check_multiple_recent_losses(self, policy_data):
        """Check for multiple losses in short time frame."""
        loss_history = policy_data.get("loss_history", [])
        
        if len(loss_history) >= 2:
            # Try to parse dates and check if multiple losses in last year
            recent_losses = []
            for loss in loss_history:
                loss_date = loss.get("date_of_occurrence", "")
                if loss_date:
                    try:
                        date_obj = datetime.strptime(loss_date, '%m/%d/%Y')
                        days_ago = (datetime.now() - date_obj).days
                        if days_ago <= 365:
                            recent_losses.append(loss)
                    except:
                        pass
            
            if len(recent_losses) >= 2:
                self._add_flag(
                    "Multiple losses within past year",
                    "HIGH",
                    f"{len(recent_losses)} losses in last 12 months"
                )
    
    def get_overall_risk_score(self):
        """
        Calculate an overall risk score based on flags.
        Returns: (score, risk_level)
        """
        risk_weights = {
            "LOW": 1,
            "MODERATE": 3,
            "HIGH": 7,
            "CRITICAL": 10
        }
        
        total_score = sum(risk_weights.get(flag["risk_level"], 0) for flag in self.flags)
        
        # Determine overall risk level
        if total_score == 0:
            return 0, "LOW"
        elif total_score <= 3:
            return total_score, "LOW"
        elif total_score <= 7:
            return total_score, "MODERATE"
        elif total_score <= 15:
            return total_score, "HIGH"
        else:
            return total_score, "CRITICAL"
