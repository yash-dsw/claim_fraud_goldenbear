"""
Test script to verify email sending functionality.
"""

import os
from dotenv import load_dotenv
from email_sender import EmailSender, load_email_metadata, get_recipient_email

def test_email():
    """Test email sending with the companion JSON file."""
    load_dotenv()
    
    # Get credentials from environment
    tenant_id = os.getenv("ONEDRIVE_TENANT_ID")
    client_id = os.getenv("ONEDRIVE_CLIENT_ID")
    client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")
    user_email = os.getenv("ONEDRIVE_USER_EMAIL")
    
    if not all([tenant_id, client_id, client_secret, user_email]):
        print("Error: Missing OneDrive/Graph credentials in .env")
        print("Required: ONEDRIVE_TENANT_ID, ONEDRIVE_CLIENT_ID, ONEDRIVE_CLIENT_SECRET, ONEDRIVE_USER_EMAIL")
        return
    
    print(f"Using sender email: {user_email}")
    
    # Initialize email sender
    email_sender = EmailSender(tenant_id, client_id, client_secret, user_email)
    print("Email sender initialized")
    
    # Load email metadata from companion JSON
    json_path = "input/C1_JohnDoe_Jetwire.pdf.json"
    email_metadata = load_email_metadata(json_path)
    
    if not email_metadata:
        print(f"Error: Could not load email metadata from {json_path}")
        return
    
    print(f"Email metadata loaded: {email_metadata}")
    
    # Get recipient
    recipient = get_recipient_email(email_metadata)
    if not recipient:
        print("Error: No recipient email found in JSON")
        return
    
    print(f"Recipient: {recipient}")
    
    # Create a sample HTML report for testing
    sample_html_report = """
    <div style="background-color: #fff3cd; padding: 20px; border-left: 4px solid #ffc107;">
        <h3>Test Fraud Detection Report</h3>
        <p><strong>Fraud Risk:</strong> <span style="color: #f39c12;">MODERATE</span></p>
        <p><strong>Risk Score:</strong> 55/100</p>
        <p><strong>Flags:</strong> 3 indicators detected</p>
        <ul>
            <li>Claim filed 29 days after policy start</li>
            <li>Recent policy modification</li>
            <li>High claim amount relative to coverage</li>
        </ul>
    </div>
    """
    
    print("\nSending test email...")
    
    # Send the email
    success = email_sender.send_fraud_report_email(recipient, email_metadata, sample_html_report)
    
    if success:
        print(f"\n[SUCCESS] Test email sent successfully to {recipient}")
    else:
        print(f"\n[FAILED] Failed to send test email")


if __name__ == "__main__":
    test_email()
