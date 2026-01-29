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
    
    def download_email_as_eml(self, message_id, output_path=None, user_email=None):
        """
        Download an email message as EML file using Microsoft Graph API.
        Uses Internet Message ID which is universal across all mailboxes.
        
        Args:
            message_id: The Internet Message ID from the email metadata JSON (internetMessageId field)
            output_path: Optional path to save the EML file. If not provided, 
                        will save to 'input/{sanitized_message_id}.eml'
            user_email: Email of the mailbox to access (defaults to self.user_email)
            
        Returns:
            Path to the saved EML file if successful, None otherwise
        """
        
        try:
            mailbox = user_email or self.user_email
            
            # Microsoft Graph API endpoint using Internet Message ID filter
            # Internet Message ID doesn't need URL encoding
            url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages?$filter=internetMessageId eq '{message_id}'"
            
            headers = self._get_headers()
            
            # First, get the message metadata to find the actual message
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                messages = response.json().get('value', [])
                
                if not messages:
                    print(f"[ERROR] No message found with Internet Message ID: {message_id}")
                    return None
                
                # Get the first message's ID
                graph_message_id = messages[0]['id']
                
                # Now download the actual EML using the Graph message ID
                eml_url = f"https://graph.microsoft.com/v1.0/users/{mailbox}/messages/{graph_message_id}/$value"
                headers_eml = self._get_headers()
                headers_eml.pop('Content-Type', None)
                
                eml_response = requests.get(eml_url, headers=headers_eml)
                
                if eml_response.status_code == 200:
                    # Determine output path
                    if not output_path:
                        os.makedirs("input", exist_ok=True)
                        # Sanitize message_id for filename
                        safe_filename = message_id.replace('<', '').replace('>', '').replace('@', '_')
                        output_path = os.path.join("input", f"{safe_filename}.eml")
                    
                    # Save the EML file
                    with open(output_path, 'wb') as f:
                        f.write(eml_response.content)
                    
                    print(f"✓ Downloaded EML file: {output_path}")
                    return output_path
                else:
                    print(f"[ERROR] Failed to download EML: {eml_response.status_code} - {eml_response.text}")
                    return None
            else:
                print(f"[ERROR] Failed to find message: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"[ERROR] Error downloading email as EML: {str(e)}")
            return None
    
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
    
    def send_fraud_report_email(self, to_email, email_metadata, html_report, input_pdf_path=None, output_pdf_path=None, report_web_url=None, output_folder_url=None):
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
            report_web_url: Optional OneDrive web URL to the generated report
            output_folder_url: Optional OneDrive web URL to the output folder
            
        Returns:
            True if successful, False otherwise
        """
        # Extract metadata
        from_email = email_metadata.get("from", "Unknown Sender")  # Original sender
        received_dt = parse_email_date(email_metadata.get("receivedDateTime", ""))
        
        # Get body preview - check for bodyPreview first, then fall back to body
        body_preview = email_metadata.get("bodyPreview", "")
        if not body_preview:
            # If bodyPreview not found, use body and truncate it
            body_preview = email_metadata.get("body", "")
        
        original_subject = email_metadata.get("subject", "Claim Analysis")
        
        # Truncate body preview to 250 characters if longer
        if len(body_preview) > 250:
            body_preview = body_preview[:250]
        
        # Build quick access links section
        quick_links_html = ""
        if report_web_url or output_folder_url:
            quick_links_html = '<div style="background:#e8f4fd; border:1px solid #2f80ed; border-radius:6px; padding:16px; margin-bottom:24px;">'
            quick_links_html += '<div style="display:flex; flex-direction:row; flex-wrap:wrap;">'
            
            if report_web_url:
                quick_links_html += f'''
                <div style="display:flex; align-items:center; margin-right:40px;">
                    <span style="color:#333; font-size:14px; margin-right:8px;">📄</span>
                    <a href="{report_web_url}" style="color:#2f80ed; text-decoration:none; font-size:14px; font-weight:500;" target="_blank">
                        View Report Online
                    </a>
                </div>
                '''
            
            if output_folder_url:
                quick_links_html += f'''
                <div style="display:flex; align-items:center;">
                    <span style="color:#333; font-size:14px; margin-right:8px;">📁</span>
                    <a href="{output_folder_url}" style="color:#2f80ed; text-decoration:none; font-size:14px; font-weight:500;" target="_blank">
                        Open Outputs Folder
                    </a>
                </div>
                '''
            
            quick_links_html += '</div></div>'
        
        # Build the email body using the template
        email_body = f'''
<div style="font-family:Segoe UI, Arial, sans-serif; background-color:#f5f7fa; padding:24px;">

<!-- Card Container -->
<div style="max-width:800px; margin:0 auto; background:#ffffff; border-radius:6px; box-shadow:0 2px 6px rgba(0,0,0,0.08); padding:28px;">

{quick_links_html}

<!-- Intro Section -->
<p style="font-size:14.5px; color:#333333; line-height:1.6;">
This email was received from
<strong>{from_email}</strong>
on <strong>{received_dt}</strong>
with the body preview:
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
        subject = f"{original_subject} - Fraud Analysis Report" if original_subject else "Fraud Analysis Report"
        
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
    Handles malformed JSON with embedded newlines and unescaped quotes in string values.
    
    Args:
        json_path: Path to the .pdf.json file
        
    Returns:
        Dictionary with email metadata or empty dict if not found
    """
    import re
    
    if not os.path.exists(json_path):
        print(f"[DEBUG] No companion JSON found at: {json_path}")
        return {}
    
    try:
        with open(json_path, 'rb') as f:
            raw_bytes = f.read()
        
        # Decode to string
        content = raw_bytes.decode('utf-8', errors='replace')
        
        # Try standard JSON parse first
        try:
            metadata = json.loads(content)
            print(f"[DEBUG] Loaded email metadata (standard JSON) from: {json_path}")
        except json.JSONDecodeError:
            # Fallback: Extract fields directly using regex
            # This handles malformed JSON with unescaped quotes and newlines
            print(f"[DEBUG] Standard JSON parse failed, extracting fields directly...")
            metadata = _extract_email_fields(content)
        
        if metadata:
            print(f"[DEBUG] Loaded email metadata from: {json_path}")
            print(f"[DEBUG]   Keys in JSON: {list(metadata.keys())}")
            print(f"[DEBUG]   id: {metadata.get('id', 'MISSING')}")
            print(f"[DEBUG]   from: {metadata.get('from', 'N/A')}")
            print(f"[DEBUG]   toRecipients: {metadata.get('toRecipients', 'MISSING')}")
            print(f"[DEBUG]   subject: {metadata.get('subject', 'N/A')}")
            print(f"[DEBUG]   receivedDateTime: {metadata.get('receivedDateTime', 'MISSING')}")
            body_preview = metadata.get('bodyPreview', '') or metadata.get('body', '')
            print(f"[DEBUG]   body/bodyPreview length: {len(body_preview)}")
        
        return metadata
        
    except Exception as e:
        print(f"[ERROR] Error loading email metadata from {json_path}: {str(e)}")
        return {}


def _extract_email_fields(content):
    """
    Extract email metadata fields directly from malformed JSON content.
    Handles unescaped quotes and newlines inside string values.
    
    Args:
        content: Raw JSON-like string content
        
    Returns:
        Dictionary with extracted fields
    """
    import re
    
    metadata = {}
    
    # Simple fields (values don't contain quotes or newlines)
    simple_fields = ['id', 'internetMessageId', 'from', 'toRecipients', 'subject', 'receivedDateTime']
    
    for field in simple_fields:
        # Match "field": "value" or "field":"value" 
        # Value ends at the next unescaped quote followed by comma, newline, or }
        pattern = rf'"{field}"\s*:\s*"([^"]*)"'
        match = re.search(pattern, content)
        if match:
            metadata[field] = match.group(1).strip()
    
    # Complex fields that may contain quotes and newlines (body, bodyPreview)
    # These are typically the last field or contain multi-line content
    
    # Try to extract bodyPreview first
    body_preview_match = re.search(r'"bodyPreview"\s*:\s*"(.*?)"(?=\s*[,}]|\s*"[a-zA-Z])', content, re.DOTALL)
    if body_preview_match:
        metadata['bodyPreview'] = body_preview_match.group(1).strip()
    
    # Extract body field - this is trickier because it may have unescaped quotes
    # Strategy: find "body": " and then find the last " before } at the end
    body_start = re.search(r'"body"\s*:\s*"', content)
    if body_start:
        start_pos = body_start.end()
        # Find the closing } of the JSON object
        # The body value ends at the last " before the final }
        remaining = content[start_pos:]
        
        # Work backwards from the end to find where body value ends
        # Look for pattern: "  followed by optional whitespace and }
        end_match = re.search(r'"\s*\n?\s*}$', remaining.rstrip())
        if end_match:
            body_content = remaining[:end_match.start()]
            # Clean up the body content
            body_content = body_content.strip()
            metadata['body'] = body_content
            
            # Also use as bodyPreview if not already set
            if 'bodyPreview' not in metadata:
                # Truncate for preview
                metadata['bodyPreview'] = body_content[:500] if len(body_content) > 500 else body_content
    
    return metadata


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


def get_message_id_from_metadata(email_metadata):
    """
    Extract the Internet Message ID from email metadata.
    
    Args:
        email_metadata: Dictionary loaded from companion JSON
        
    Returns:
        Internet Message ID string or None
    """
    if not email_metadata:
        return None
    
    # Use 'internetMessageId' field which is universal across mailboxes
    message_id = email_metadata.get("internetMessageId", "")
    
    if message_id and isinstance(message_id, str):
        return message_id.strip()
    
    return None


def download_eml_from_json(json_path, email_sender, output_dir="input"):
    """
    Download EML file based on metadata from a companion JSON file.
    Uses the receiver's email (toRecipients) from the JSON for fetching.
    
    Args:
        json_path: Path to the .pdf.json file containing email metadata
        email_sender: EmailSender instance (already authenticated)
        output_dir: Directory to save the EML file
        
    Returns:
        Path to downloaded EML file or None if failed
    """
    # Load email metadata
    metadata = load_email_metadata(json_path)
    
    if not metadata:
        print(f"[ERROR] Could not load email metadata from {json_path}")
        return None
    
    # Extract message ID
    message_id = get_message_id_from_metadata(metadata)
    
    if not message_id:
        print(f"[ERROR] No message ID found in metadata")
        return None
    
    # Extract receiver's email (toRecipients) from metadata
    receiver_email = get_recipient_email(metadata)
    
    if not receiver_email:
        print(f"[ERROR] No receiver email (toRecipients) found in metadata")
        return None
    
    # Generate EML filename based on JSON filename
    json_basename = os.path.basename(json_path)
    # Remove .pdf.json extension and add .eml
    eml_filename = json_basename.replace('.pdf.json', '.eml')
    eml_path = os.path.join(output_dir, eml_filename)
    
    # Download the EML file using receiver's email
    print(f"📧 Downloading EML for message ID: {message_id}")
    print(f"   Using receiver's mailbox: {receiver_email}")
    result = email_sender.download_email_as_eml(message_id, eml_path, user_email=receiver_email)
    
    return result
