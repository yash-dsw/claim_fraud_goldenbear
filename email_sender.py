"""
Email sender module using Microsoft Graph API.
Sends fraud detection reports via email using the same app registration
as OneDrive.
"""

import os
import json
import requests
from datetime import datetime


class EmailSender:
    """Send emails using Microsoft Graph API with application permissions."""
    
    def __init__(self, tenant_id, client_id, client_secret, user_email):
        """
        Initialize email sender with app credentials.
        
        Args:
            tenant_id: Azure AD tenant ID
            client_id: Application (client) ID
            client_secret: Client secret
            user_email: Email of the user to send as (must have send permissions)
        """
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_email = user_email
        self.access_token = None
        self.token_expiry = None
    
    def _get_access_token(self):
        """Get access token using client credentials flow."""
        # Reuse existing token if not expired
        if self.access_token and self.token_expiry:
            if datetime.now().timestamp() < self.token_expiry - 60:  # 1 min buffer
                return self.access_token
        
        token_url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        
        token_data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        
        response = requests.post(token_url, data=token_data)
        
        if response.status_code != 200:
            raise Exception(f"Failed to get access token: {response.text}")
        
        token_info = response.json()
        self.access_token = token_info["access_token"]
        self.token_expiry = datetime.now().timestamp() + token_info.get("expires_in", 3600)
        
        return self.access_token
    
    def _get_headers(self):
        """Get headers with access token."""
        token = self._get_access_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    
    def send_email_from_user(self, sender_email, to_email, subject, html_body):
        """
        Send an email from a specific user via Microsoft Graph API.
        
        Args:
            sender_email: Email address to send FROM
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML content of the email
            
        Returns:
            True if successful, False otherwise
        """
        url = f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail"
        
        email_payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": html_body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email
                        }
                    }
                ]
            },
            "saveToSentItems": True
        }
        
        try:
            response = requests.post(url, headers=self._get_headers(), json=email_payload)
            
            if response.status_code == 202:
                return True
            else:
                print(f"[ERROR] Failed to send email: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"[ERROR] Error sending email: {str(e)}")
            return False
    
    def send_email(self, to_email, subject, html_body, from_name=None):
        """
        Send an email via Microsoft Graph API using default service account.
        
        Args:
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML content of the email
            from_name: Optional display name for sender
            
        Returns:
            True if successful, False otherwise
        """
        url = f"https://graph.microsoft.com/v1.0/users/{self.user_email}/sendMail"
        
        email_payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": html_body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email
                        }
                    }
                ]
            },
            "saveToSentItems": True
        }
        
        try:
            response = requests.post(url, headers=self._get_headers(), json=email_payload)
            
            if response.status_code == 202:
                return True
            else:
                print(f"[ERROR] Failed to send email: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"[ERROR] Error sending email: {str(e)}")
            return False
    
    def _encode_file_attachment(self, file_path):
        """
        Encode a file as base64 for Microsoft Graph API attachment.
        
        Args:
            file_path: Path to the file to attach
            
        Returns:
            Dictionary with attachment data for Graph API, or None if error
        """
        import base64
        
        try:
            if not os.path.exists(file_path):
                print(f"[WARNING] Attachment file not found: {file_path}")
                return None
            
            with open(file_path, 'rb') as f:
                file_content = f.read()
            
            file_name = os.path.basename(file_path)
            content_bytes = base64.b64encode(file_content).decode('utf-8')
            
            # Determine content type based on extension
            ext = os.path.splitext(file_name)[1].lower()
            content_type_map = {
                '.pdf': 'application/pdf',
                '.html': 'text/html',
                '.json': 'application/json',
                '.txt': 'text/plain'
            }
            content_type = content_type_map.get(ext, 'application/octet-stream')
            
            return {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": file_name,
                "contentType": content_type,
                "contentBytes": content_bytes
            }
        except Exception as e:
            print(f"[ERROR] Error encoding attachment {file_path}: {str(e)}")
            return None
    
    def send_fraud_report_email(self, to_email, email_metadata, html_report, input_pdf_path=None, output_pdf_path=None):
        """
        Send a fraud detection report email using the provided template.
        Email will be sent FROM the toRecipients address TO the same toRecipients address.
        
        Args:
            to_email: Recipient email address (also used as sender)
            email_metadata: Dictionary with email metadata (from JSON file):
                - from: Original sender email (new format)
                - subject: Original email subject
                - receivedDateTime: When the original email was received (ISO or readable format)
                - bodyPreview: Preview of the original email body
                - toRecipients: Original recipient(s) - used as both sender and receiver
            html_report: The generated HTML fraud report content
            input_pdf_path: Optional path to the original claim PDF to attach
            output_pdf_path: Optional path to the generated fraud report PDF to attach
            
        Returns:
            True if successful, False otherwise
        """
        # Extract metadata
        from_email = email_metadata.get("from", "Unknown Sender")  # Original sender
        received_dt = parse_email_date(email_metadata.get("receivedDateTime", ""))
        body_preview = email_metadata.get("bodyPreview", "")
        original_subject = email_metadata.get("subject", "Claim Analysis")
        
        # Truncate body preview to 250 characters if longer
        if len(body_preview) > 250:
            body_preview = body_preview[:250]
        
        # Build the email body using the template
        email_body = f'''
<div style="font-family:Segoe UI, Arial, sans-serif; background-color:#f5f7fa; padding:24px;">

<!-- Card Container -->
<div style="max-width:800px; margin:0 auto; background:#ffffff; border-radius:6px; box-shadow:0 2px 6px rgba(0,0,0,0.08); padding:28px;">

<!-- Intro Section -->
<p style="font-size:14.5px; color:#333333; line-height:1.6;">
This email was received from
<strong>{from_email}</strong>
on <strong>{received_dt}</strong>
</p>

<p style="font-size:14.5px; color:#333333; line-height:1.6;">
Based on the content of the email:
</p>

<!-- Message Preview Box -->
<div style="background:#f1f4f9; border-left:4px solid #2f80ed; padding:14px 16px; margin:12px 0 20px 0; font-size:13.5px; color:#444;">
"{body_preview} …"
</div>

<p style="font-size:14.5px; color:#333333; line-height:1.6;">
Along with the attached information, the request has been reviewed and the corresponding analysis has been generated accordingly.
</p>

<p style="font-size:14.5px; color:#333333; line-height:1.6; margin-bottom:24px;">
Please find the processed result and attachments below.
</p>

<!-- Report Output Section -->
<h2 style="font-size:20px; color:#1f3b64; margin-bottom:10px;">
Analysis Summary
</h2>

<div style="font-size:13.8px; color:#2b2b2b; line-height:1.6;">
{html_report}
</div>

<!-- Footer -->


</div>
</div>
'''
        
        # Subject line for the email
        subject = f"Re: {original_subject} - Fraud Analysis Report" if original_subject else "Fraud Analysis Report"
        
        # Build attachments list
        attachments = []
        if input_pdf_path:
            attachment = self._encode_file_attachment(input_pdf_path)
            if attachment:
                attachments.append(attachment)
                print(f"  📎 Attaching input PDF: {os.path.basename(input_pdf_path)}")
        
        if output_pdf_path:
            attachment = self._encode_file_attachment(output_pdf_path)
            if attachment:
                attachments.append(attachment)
                print(f"  📎 Attaching output PDF: {os.path.basename(output_pdf_path)}")
        
        # Send email FROM toRecipients TO toRecipients (same address) with attachments
        return self.send_email_with_attachments(to_email, to_email, subject, email_body, attachments)
    
    def send_email_with_attachments(self, sender_email, to_email, subject, html_body, attachments=None):
        """
        Send an email with attachments from a specific user via Microsoft Graph API.
        
        Args:
            sender_email: Email address to send FROM
            to_email: Recipient email address
            subject: Email subject
            html_body: HTML content of the email
            attachments: List of attachment dictionaries for Graph API
            
        Returns:
            True if successful, False otherwise
        """
        url = f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail"
        
        email_payload = {
            "message": {
                "subject": subject,
                "body": {
                    "contentType": "HTML",
                    "content": html_body
                },
                "toRecipients": [
                    {
                        "emailAddress": {
                            "address": to_email
                        }
                    }
                ]
            },
            "saveToSentItems": True
        }
        
        # Add attachments if provided
        if attachments:
            email_payload["message"]["attachments"] = attachments
        
        try:
            response = requests.post(url, headers=self._get_headers(), json=email_payload)
            
            if response.status_code == 202:
                return True
            else:
                print(f"[ERROR] Failed to send email: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            print(f"[ERROR] Error sending email: {str(e)}")
            return False


def parse_email_date(date_str):
    """
    Parse email date from either ISO 8601 or readable format.
    
    Args:
        date_str: Date string in ISO format (2026-01-07T07:08:18.000Z) or readable (January 07, 2026)
        
    Returns:
        Formatted date string
    """
    if not date_str:
        return "Unknown Date"
    
    try:
        # Try ISO 8601 format first
        if 'T' in date_str and ('Z' in date_str or '+' in date_str or date_str.count(':') >= 2):
            from datetime import datetime
            # Handle Z suffix or timezone
            if date_str.endswith('Z'):
                date_str = date_str[:-1] + '+00:00'
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime("%B %d, %Y at %I:%M %p UTC")
        else:
            # Already in readable format
            return date_str
    except:
        # Fallback to original string
        return date_str


def load_email_metadata(json_path):
    """
    Load email metadata from a companion JSON file.
    
    Args:
        json_path: Path to the .pdf.json file
        
    Returns:
        Dictionary with email metadata or empty dict if not found
    """
    try:
        if os.path.exists(json_path):
            with open(json_path, 'rb') as f:
                raw_bytes = f.read()
            
            # Decode to string
            content = raw_bytes.decode('utf-8', errors='replace')
            
            # Sanitize content - replace control characters that break JSON parsing
            # The issue is that raw newlines appear INSIDE JSON string values
            # We need to escape them before parsing
            import re
            
            # Replace all newline variants with escaped version
            # This works because JSON string values shouldn't have literal newlines
            content = content.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
            
            # Also handle any other control characters (ASCII 0-31 except tab and space)
            content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', content)
            
            metadata = json.loads(content)
            print(f"[DEBUG] Loaded email metadata from: {json_path}")
            print(f"[DEBUG]   from: {metadata.get('from', 'N/A')}")
            print(f"[DEBUG]   toRecipients: {metadata.get('toRecipients', 'MISSING')}")
            print(f"[DEBUG]   subject: {metadata.get('subject', 'N/A')}")
            return metadata
        else:
            print(f"[DEBUG] No companion JSON found at: {json_path}")
            return {}
    except Exception as e:
        print(f"[ERROR] Error loading email metadata from {json_path}: {str(e)}")
        return {}


def get_recipient_email(email_metadata):
    """
    Extract the recipient email address from email metadata.
    
    Args:
        email_metadata: Dictionary loaded from companion JSON
        
    Returns:
        Email address string or None
    """
    # If no metadata provided, return None
    if not email_metadata:
        return None
        
    to_recipients = email_metadata.get("toRecipients", "")
    
    # Handle if it's a string (single email)
    if isinstance(to_recipients, str):
        email = to_recipients.strip() if to_recipients else ""
        # Validate it looks like an email
        if email and '@' in email:
            return email
        return None
    
    # Handle if it's a list of emails
    if isinstance(to_recipients, list) and len(to_recipients) > 0:
        first_email = to_recipients[0]
        if isinstance(first_email, str):
            email = first_email.strip()
            if email and '@' in email:
                return email
    
    return None
