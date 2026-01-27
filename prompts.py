"""
Prompts for the AI agent-based fraud detection.
"""

EXTRACT_POLICY_NUMBER_PROMPT = """Extract the policy number or claim number from the following email information.

EMAIL SUBJECT:
{subject}

EMAIL BODY:
{body}

Look for patterns like:
- Policy numbers (e.g., "Policy: P12345", "Policy #12345", "Policy Number: ABC123")
- Claim numbers (e.g., "Claim: C12345", "Claim #12345", "Claim Number: XYZ789")
- Reference numbers or case numbers

Return ONLY the policy or claim number found, without any prefix like "Policy:" or "Claim:".
If multiple numbers are found, return the most relevant one (policy number preferred over claim number).
If no policy or claim number is found, return "UNKNOWN".

Your response should be ONLY the extracted number (e.g., "P12345" or "C1" or "UNKNOWN"), nothing else."""


SUMMARY_ONLY_PROMPT = """You are summarizing fraud detection results for an insurance claim.

POLICY INFORMATION:
{policy_data}

CLAIM INFORMATION:
{claim_data}

FRAUD INDICATORS DETECTED (Rule-Based Analysis):
{rule_based_flags}

RISK ASSESSMENT:
- Fraud Risk: {risk_level}
- Risk Score: {risk_score}
- Total Indicators: {flags_count}

Create a professional summary in the following format:

**Key Findings:**
- [Point 1: Main fraud concern in one sentence]
- [Point 2: Secondary concern in one sentence]
- [Point 3: Additional observation if applicable]

**Risk Factors:**
- [List specific risk factors identified]

**Recommendations:**
- [Action 1: Specific recommendation]
- [Action 2: Additional suggestion]
- [Action 3: Follow-up action if needed]

Use clear, professional language. Be specific about the fraud indicators.
Keep it comprehensive but concise (max 150 words total).
Do NOT add your own risk assessment - use the provided fraud risk level.
"""


def format_policy_data(policy_dict):
    """Format policy data for the prompt."""
    formatted = []
    for key, value in policy_dict.items():
        if value and value != "" and key != "loss_history":
            formatted.append(f"- {key.replace('_', ' ').title()}: {value}")
    
    # Add loss history separately
    if policy_dict.get("loss_history"):
        formatted.append("\nLoss History:")
        for i, loss in enumerate(policy_dict["loss_history"], 1):
            formatted.append(f"  Loss {i}:")
            for k, v in loss.items():
                if v:
                    formatted.append(f"    - {k.replace('_', ' ').title()}: {v}")
    
    return "\n".join(formatted)


def format_claim_data(claim_dict):
    """Format claim data for the prompt."""
    formatted = []
    for key, value in claim_dict.items():
        if value and value != "" and key != "full_text":
            formatted.append(f"- {key.replace('_', ' ').title()}: {value}")
    
    # Add a portion of full text if it exists
    if claim_dict.get("full_text"):
        full_text = claim_dict["full_text"][:1000]  # First 1000 chars
        formatted.append(f"\nClaim Description (excerpt):\n{full_text}...")
    
    return "\n".join(formatted)


def format_rule_flags(flags_list):
    """Format rule-based flags for the prompt."""
    if not flags_list:
        return "No critical rule-based flags detected."
    
    formatted = []
    for i, flag in enumerate(flags_list, 1):
        formatted.append(f"{i}. {flag['description']} (Risk Level: {flag['risk_level']})")
        if flag.get('details'):
            formatted.append(f"   Details: {flag['details']}")
    
    return "\n".join(formatted)
