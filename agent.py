"""
AI Agent for Fraud Detection - Simplified for summarization only.
"""

import os
from openai import OpenAI


class AgentDetector:
    """AI agent for generating human-readable summaries of fraud detection results."""
    
    def __init__(self, api_key=None):
        """Initialize the AI agent with API key."""
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY not found in environment or provided")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://openrouter.ai/api/v1"
        )
        self.model = "meta-llama/llama-3.3-70b-instruct"
    
    def summarize_findings(self, policy_data, claim_data, rule_flags, risk_level, risk_score):
        """
        Generate a human-readable summary of rule-based fraud detection results.
        
        Args:
            policy_data: Dictionary of policy information
            claim_data: Dictionary of claim information
            rule_flags: List of flags from rule-based detection
            risk_level: Overall risk level from rule-based detection
            risk_score: Risk score from rule-based detection
        
        Returns:
            Dictionary with summary
        """
        from prompts import (
            SUMMARY_ONLY_PROMPT,
            format_policy_data,
            format_claim_data,
            format_rule_flags
        )
        
        # Format data for the prompt
        formatted_policy = format_policy_data(policy_data)
        formatted_claim = format_claim_data(claim_data)
        formatted_flags = format_rule_flags(rule_flags)
        
        # Create the prompt
        prompt = SUMMARY_ONLY_PROMPT.format(
            policy_data=formatted_policy,
            claim_data=formatted_claim,
            rule_based_flags=formatted_flags,
            risk_level=risk_level,
            risk_score=risk_score,
            flags_count=len(rule_flags)
        )
        
        try:
            # Call OpenRouter API
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=500,
                temperature=0.7,
                messages=[
                    {"role": "system", "content": "You are an insurance analyst creating clear, professional summaries."},
                    {"role": "user", "content": prompt}
                ]
            )
            
            summary_text = response.choices[0].message.content
            
            return {
                "success": True,
                "summary": summary_text,
                "model_used": self.model
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "summary": f"Error generating summary: {str(e)}",
                "model_used": self.model
            }


class MockAgentDetector:
    """Mock agent for when no API key is available."""
    
    def summarize_findings(self, policy_data, claim_data, rule_flags, risk_level, risk_score):
        """Generate a basic summary without AI."""
        if not rule_flags:
            summary = "No significant fraud indicators detected."
        else:
            concerns = [f"- {flag['description']}" for flag in rule_flags[:3]]
            summary = "**Key Concerns:**\n" + "\n".join(concerns)
            summary += "\n\n**Recommendation:** Review the detected indicators and investigate further if necessary."
        
        return {
            "success": True,
            "summary": summary,
            "model_used": "Rule-Based Only (No AI)"
        }
