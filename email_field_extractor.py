"""
Email Field Extractor - Simple regex-based extraction
Extracts only required fields: Policy Number, Subject, Document Name, Comments, Timestamp
"""

import os
import json
import re
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()


# ============================================================================
# LLM-BASED EXTRACTION (COMMENTED OUT - NOT USED)
# ============================================================================
# EMAIL_EXTRACTION_PROMPT = """Extract the following information from the email subject and body provided below.
#
# **Required Fields:**
# 1. Sender Email - The email of the person/broker sending the submission
# 2. Sender Name - The name of the sender
# 3. Receiver Email - The email of the person/underwriter receiving the submission
# 4. Receiver Name - The name of the receiver or team
# 5. Policy Number - The insurance policy number mentioned
# 6. Agency Name - The name of the agency/company
# 7. Agency ID - Any agency identification number
# 8. Email Summary - A concise 2-3 sentence summary highlighting CRITICAL details an underwriter might overlook, such as: special conditions, coverage modifications, pending requirements, risk concerns, time-sensitive requests, unusual property characteristics, prior loss history mentions, or any red flags that require immediate attention
#
# **Email Data:**
# From: {from_email}
# To: {to_email}
# Subject: {subject}
# Body: {body}
#
# **Instructions:**
# - The SENDER is the person/agent submitting the policy information (typically from the "From" field or email signature)
# - The RECEIVER is the person/team receiving the submission (typically the "To" field or addressed in the body)
# - Look carefully at the email body content for names, email addresses, and signatures
# - If the body contains sender information (signature, name at end), use that for the sender
# - If the body addresses a team ("Underwriting Team", "Claims Team", etc), use that as the receiver name
# - For emails and names mentioned IN THE BODY TEXT, prioritize those over the from/to fields if they provide more detail
# - If from_email and to_email are the same, look in the body for the actual sender and recipient information
# - Extract policy numbers, agency names, and IDs from both subject and body
# - For the Email Summary: Focus on CRITICAL UNDERWRITING DETAILS that might be easily missed, including: special conditions, endorsements, coverage modifications, pending requirements, deadlines, risk concerns (prior losses, claims history, property issues), unusual circumstances, broker requests, or any red flags requiring immediate attention. Do NOT just restate basic information - highlight what's important for underwriting decisions.
# - If a field cannot be found anywhere, use "Not Found" as the value
#
# **Output Format:**
# Return ONLY a valid JSON object with these exact keys:
# {{
#   "sender_email": "extracted email or Not Found",
#   "sender_name": "extracted name or Not Found",
#   "receiver_email": "extracted email or Not Found",
#   "receiver_name": "extracted name or Not Found",
#   "policy_number": "extracted policy number or Not Found",
#   "agency_name": "extracted agency name or Not Found",
#   "agency_id": "extracted agency ID or Not Found",
#   "email_summary": "2-3 sentence summary focusing on critical underwriting details, risk concerns, special conditions, or any important information that requires immediate attention"
# }}
#
# Do not include any explanation or additional text, only the JSON object."""


class EmailFieldExtractor:
    """Extract structured fields from email metadata using regex"""
    
    def __init__(self):
        """Initialize the extractor (no API key needed)"""
        # LLM-based extraction disabled - using regex instead
        # self.api_key = os.getenv("OPENROUTER_API_KEY")
        # if not self.api_key:
        #     raise ValueError("OPENROUTER_API_KEY not found in environment variables")
        # 
        # self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        # self.model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
        pass
    
    def extract_policy_number_regex(self, text: str) -> str:
        """
        Extract 8-digit alphanumeric policy number using regex.
        Must contain at least one digit (not all letters).
        
        Args:
            text: Text to search (email subject or body)
        
        Returns:
            Policy number if found, "Not Found" otherwise
        """
        if not text:
            return "Not Found"
        
        # Pattern: 8-character alphanumeric that contains at least one digit
        # Matches: 12345678, ABC12345, A1B2C3D4
        # Does NOT match: CRITICAL, ABCDEFGH (all letters)
        pattern = r'\b(?=.*\d)[A-Z0-9]{8}\b'
        
        matches = re.findall(pattern, text.upper())
        
        # Return first match
        if matches:
            return matches[0]
        
        return "Not Found"
    
    def extract_fields(self, email_metadata: dict, pdf_filename: str = None) -> dict:
        """
        Extract only required fields from email metadata using regex/direct extraction.
        
        Required fields:
        - Policy Number (8 digit alphanumeric from subject/body)
        - Subject (direct from email)
        - Document Name (from pdf_filename parameter or attachments)
        - Comments (empty string)
        - Timestamp (email received date)
        
        Args (added):
            pdf_filename: Optional PDF filename to use as document_name
        
        Args:
            email_metadata: Dictionary containing email data with keys:
                - from: sender email/name
                - toRecipients: recipient email(s)
                - subject: email subject line
                - bodyPreview or body: email body content
                - hasAttachments: boolean
                - attachments: list of attachment info (if available)
                - receivedDateTime: email received timestamp
        
        Returns:
            Dictionary with extracted fields (only required fields)
        """
        if not email_metadata:
            return self._empty_result()
        
        # Extract email components
        subject = email_metadata.get("subject", "")
        body = email_metadata.get("bodyPreview", email_metadata.get("body", ""))
        received_datetime = email_metadata.get("receivedDateTime", "")
        
        # REQUIRED FIELD 1: Policy Number - Extract using regex from subject and body
        policy_number = self.extract_policy_number_regex(subject)
        if policy_number == "Not Found":
            # Try body if not found in subject
            policy_number = self.extract_policy_number_regex(body)
        
        # REQUIRED FIELD 2: Subject - Direct extraction
        email_subject = subject if subject else "Not Found"
        
        # REQUIRED FIELD 3: Document Name - From parameter, attachments, or companion JSON
        document_name = "Not Found"
        
        # First check if pdf_filename was provided as parameter
        if pdf_filename:
            document_name = pdf_filename
        # Otherwise try to get from attachments in email metadata
        elif email_metadata.get("hasAttachments"):
            attachments = email_metadata.get("attachments", [])
            if attachments and len(attachments) > 0:
                # Get first PDF attachment name
                pdf_attachments = [att.get("name", "") for att in attachments if att.get("name", "").lower().endswith('.pdf')]
                if pdf_attachments:
                    document_name = pdf_attachments[0]
                else:
                    # If no PDF, get first attachment
                    document_name = attachments[0].get("name", "Not Found")
        
        # If still not found, try to get from companion JSON filename field
        if document_name == "Not Found":
            # Check if there's a filename in the metadata (from companion JSON)
            if email_metadata.get("filename"):
                document_name = email_metadata.get("filename")
            elif email_metadata.get("name"):
                document_name = email_metadata.get("name")
        
        # REQUIRED FIELD 4: Comments - Empty (as per requirement)
        comments = ""
        
        # REQUIRED FIELD 5: Timestamp - Email received date
        timestamp = received_datetime if received_datetime else datetime.now().isoformat()
        
        # Build result with ONLY required fields
        result = {
            "policy_number": policy_number,
            "subject": email_subject,
            "document_name": document_name,
            "comments": comments,
            "timestamp": timestamp
        }
        
        # ===================================================================
        # COMMENTED OUT: Other fields not needed (kept for reference)
        # ===================================================================
        # from_field = email_metadata.get("from", "")
        # to_field = email_metadata.get("toRecipients", "")
        # 
        # if isinstance(to_field, list):
        #     to_field = ", ".join(to_field) if to_field else ""
        # 
        # result["sender_email"] = from_field if from_field else "Not Found"
        # result["sender_name"] = "Not Found"
        # result["receiver_email"] = to_field if to_field else "Not Found"
        # result["receiver_name"] = "Not Found"
        # result["agency_name"] = "Not Found"
        # result["agency_id"] = "Not Found"
        # result["email_summary"] = "Not Found"
        # result["broker_email"] = result["sender_email"]
        # result["broker_name"] = "Not Found"
        # result["underwriter_email"] = result["receiver_email"]
        # result["underwriter_name"] = "Not Found"
        # result["broker_agency_name"] = "Not Found"
        # result["broker_agency_id"] = "Not Found"
        
        print(f"[EMAIL_EXTRACTOR] ✓ Email fields extracted (regex-based)")
        print(f"[EMAIL_EXTRACTOR]   Policy Number: {result.get('policy_number', 'N/A')}")
        print(f"[EMAIL_EXTRACTOR]   Subject: {result.get('subject', 'N/A')[:50]}...")
        print(f"[EMAIL_EXTRACTOR]   Document: {result.get('document_name', 'N/A')}")
        print(f"[EMAIL_EXTRACTOR]   Timestamp: {result.get('timestamp', 'N/A')}")
        
        return result
    
    def _empty_result(self) -> dict:
        """Return empty result structure with only required fields"""
        return {
            "policy_number": "Not Found",
            "subject": "Not Found",
            "document_name": "Not Found",
            "comments": "",
            "timestamp": datetime.now().isoformat()
        }
        
        # ===================================================================
        # COMMENTED OUT: Other fields not needed (kept for reference)
        # ===================================================================
        # "sender_email": "Not Found",
        # "sender_name": "Not Found",
        # "receiver_email": "Not Found",
        # "receiver_name": "Not Found",
        # "agency_name": "Not Found",
        # "agency_id": "Not Found",
        # "email_summary": "Not Found",
        # "broker_email": "Not Found",
        # "broker_name": "Not Found",
        # "underwriter_email": "Not Found",
        # "underwriter_name": "Not Found",
        # "broker_agency_name": "Not Found",
        # "broker_agency_id": "Not Found"


def extract_email_fields(email_metadata: dict, pdf_filename: str = None) -> dict:
    """
    Convenience function to extract email fields.
    
    Args:
        email_metadata: Email metadata dictionary
        pdf_filename: Optional PDF filename to use as document_name
    
    Returns:
        Dictionary with extracted fields
    """
    extractor = EmailFieldExtractor()
    return extractor.extract_fields(email_metadata, pdf_filename)


if __name__ == "__main__":
    # Test with sample data
    sample_email = {
        "from": "john.broker@abcinsurance.com",
        "toRecipients": ["sarah.underwriter@goldenbear.com"],
        "subject": "Submission for Policy ABC12345 - Commercial Property",
        "bodyPreview": "Dear Sarah, Please find attached the ACORD form for ABC Insurance Agency (ID: AG-9876). Policy number: ABC12345. This is for renewal. Best regards, John Smith",
        "receivedDateTime": "2026-02-10T10:30:00Z",
        "hasAttachments": True,
        "attachments": [
            {"name": "C1_JohnDoe.pdf"}
        ]
    }
    
    result = extract_email_fields(sample_email)
    print("\n" + "="*70)
    print("EXTRACTED FIELDS (REQUIRED ONLY):")
    print("="*70)
    print(json.dumps(result, indent=2))
