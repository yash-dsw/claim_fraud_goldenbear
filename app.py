"""
Main application for Claims Fraud Detection System.

This system combines rule-based and AI agent-based approaches
to detect potential fraud in insurance claims.
"""

import os
import json
import time
from datetime import datetime
import argparse
import sys
import signal
from dotenv import load_dotenv

from utils import extract_claim_fields
from rules import RuleBasedDetector
from agent import AgentDetector, MockAgentDetector
from policy_db import PolicyDatabase
from onedrive_client_app import OneDriveClientApp
from email_sender import EmailSender, load_email_metadata, get_recipient_email


class FraudDetectionSystem:
    """Main orchestrator for the fraud detection system."""
    
    def __init__(self, use_ai=True):
        """
        Initialize the fraud detection system.
        
        Args:
            use_ai: Whether to use AI agent (requires API key)
        """
        load_dotenv()  # Load environment variables
        
        self.rule_detector = RuleBasedDetector()
        self.policy_db = PolicyDatabase()  # Load policy database
        
        # Initialize AI agent if requested and API key available
        api_key = os.getenv("OPENROUTER_API_KEY")
        if use_ai and api_key:
            print("✓ AI Agent enabled (OpenRouter - Llama 3.3 70B)")
            self.agent = AgentDetector(api_key)
            self.use_ai = True
        else:
            if use_ai:
                print("⚠ No API key found, using mock AI agent")
            self.agent = MockAgentDetector()
            self.use_ai = False
        
        # Initialize OneDrive client and Email sender if enabled
        self.onedrive_client = None
        self.onedrive_output_folder = None
        self.onedrive_processed_folder = None
        self.email_sender = None
        if os.getenv("ONEDRIVE_ENABLED", "0") == "1":
            tenant_id = os.getenv("ONEDRIVE_TENANT_ID")
            client_id = os.getenv("ONEDRIVE_CLIENT_ID")
            client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")
            user_email = os.getenv("ONEDRIVE_USER_EMAIL")
            input_folder = os.getenv("ONEDRIVE_FOLDER_NAME", "Input_attachments")
            self.onedrive_output_folder = os.getenv("ONEDRIVE_OUTPUT_FOLDER", "Output_attachments")
            self.onedrive_processed_folder = os.getenv("ONEDRIVE_PROCESSED_INPUTS", "Processed_inputs")
            
            if all([tenant_id, client_id, client_secret, user_email]):
                self.onedrive_client = OneDriveClientApp(
                    tenant_id, client_id, client_secret, user_email, input_folder
                )
                print(f"✓ OneDrive upload enabled (folder: {self.onedrive_output_folder})")
                
                # Initialize email sender (shares credentials with OneDrive)
                self.email_sender = EmailSender(
                    tenant_id, client_id, client_secret, user_email
                )
                print(f"✓ Email notifications enabled (sender: {user_email})")
    
    def analyze_claim(self, claim_pdf_path):
        """
        Analyze a claim for potential fraud.
        
        Args:
            claim_pdf_path: Path to the claim form PDF
        
        Returns:
            Dictionary containing the complete fraud analysis
        """
        print("\n" + "="*70)
        print("CLAIMS FRAUD DETECTION SYSTEM")
        print("="*70)
        
        # Step 1: Extract claim data
        print("\n[1/4] Extracting claim data...")
        claim_data = extract_claim_fields(claim_pdf_path)
        print(f"✓ Extracted {len([v for v in claim_data.values() if v and v != ''])} claim fields")
        
        # Step 2: Match policy from database
        print("\n[2/4] Matching policy from database...")
        claim_policy_number = claim_data.get("policy_number", "")
        
        if not claim_policy_number:
            print("✗ Error: No policy number found in claim form")
            return {
                "error": "No policy number found in claim form",
                "claim_data": claim_data
            }
        
        print(f"  Policy number from claim: {claim_policy_number}")
        
        policy_info = self.policy_db.get_policy(claim_policy_number)
        
        if not policy_info:
            print(f"✗ Error: Policy {claim_policy_number} not found in database")
            print(f"  Available policies: {', '.join(self.policy_db.list_policies())}")
            return {
                "error": f"Policy {claim_policy_number} not found in database",
                "claim_data": claim_data,
                "available_policies": self.policy_db.list_policies()
            }
        
        policy_data = policy_info["policy_data"]
        acord_file = policy_info["source_file"]
        print(f"✓ Policy matched: {acord_file}")
        print(f"  Insured: {policy_data.get('named_insured', 'N/A')}")
        
        # Step 3: Run rule-based detection
        print("\n[3/4] Running rule-based fraud detection...")
        rule_flags = self.rule_detector.detect(policy_data, claim_data)
        risk_score, risk_level = self.rule_detector.get_overall_risk_score()
        print(f"✓ Detected {len(rule_flags)} fraud indicators")
        print(f"✓ Risk Score: {risk_score} ({risk_level})")
        
        # Step 4: Generate summary using AI (optional)
        print("\n[4/4] Generating executive summary...")
        summary_result = self.agent.summarize_findings(
            policy_data, claim_data, rule_flags, risk_level, risk_score
        )
        
        if summary_result["success"]:
            print("✓ Summary generated")
        else:
            print(f"⚠ Summary error: {summary_result.get('error', 'Unknown error')}")
        
        summary = summary_result["summary"]
        final_verdict = risk_level  # Use rule-based verdict directly
        
        # Compile results
        results = {
            "metadata": {
                "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "acord_file": acord_file,
                "claim_file": os.path.basename(claim_pdf_path),
                "policy_number": claim_policy_number,
                "summary_model": summary_result.get("model_used", "N/A")
            },
            "policy_data": policy_data,
            "claim_data": claim_data,
            "fraud_detection": {
                "flags": rule_flags,
                "risk_score": risk_score,
                "risk_level": risk_level,
                "flags_count": len(rule_flags)
            },
            "executive_summary": summary
        }
        
        return results
    
    def generate_report(self, results, output_format="console"):
        """
        Generate a human-readable fraud detection report.
        
        Args:
            results: The analysis results dictionary
            output_format: 'console', 'json', or 'html'
        """
        if output_format == "console":
            self._print_console_report(results)
        elif output_format == "json":
            return json.dumps(results, indent=2)
        elif output_format == "html":
            return self._generate_html_report(results)
    
    def _print_console_report(self, results):
        """Print a formatted report to console."""
        print("\n" + "="*70)
        print("FRAUD DETECTION REPORT")
        print("="*70)
        
        # Metadata
        meta = results["metadata"]
        policy = results["policy_data"]
        print(f"\nClaim File: {meta['claim_file']}")
        print(f"Policy Number: {meta['policy_number']}")
        print(f"Named Insured: {policy.get('named_insured', 'N/A')}")
        print(f"Analysis Date: {meta['analysis_date']}")
        
        # Final Verdict (at the top)
        print("\n" + "-"*70)
        print("FRAUD DETECTION VERDICT")
        print("-"*70)
        print(f"Fraud Risk: {results['fraud_detection']['risk_level']}")
        print(f"Fraud Indicators: {results['fraud_detection']['flags_count']}")
        print(f"Risk Score: {results['fraud_detection']['risk_score']}")
        
        # Summary
        print("\n" + "-"*70)
        print("SUMMARY")
        print("-"*70)
        print(results["executive_summary"])
        
        # Fraud Detection Results
        print("\n" + "-"*70)
        print("FRAUD INDICATORS (Rule-Based Detection)")
        print("-"*70)
        detection = results["fraud_detection"]
        print(f"Fraud Risk: {detection['risk_level']}")
        print(f"Risk Score: {detection['risk_score']}")
        print(f"Total Flags: {detection['flags_count']}")
        
        if detection['flags']:
            print("\nDetected Flags:")
            for i, flag in enumerate(detection['flags'], 1):
                print(f"\n  {i}. [{flag['risk_level']}] {flag['description']}")
                if flag.get('details'):
                    print(f"     Details: {flag['details']}")
        else:
            print("\n✓ No fraud indicators detected")
        
        # Policy Information
        print("\n" + "-"*70)
        print("POLICY INFORMATION")
        print("-"*70)
        policy = results["policy_data"]
        print(f"Named Insured: {policy.get('named_insured', 'N/A')}")
        print(f"Policy Number: {policy.get('policy_number', 'N/A')}")
        print(f"Effective Date: {policy.get('effective_date', 'N/A')}")
        print(f"Producer: {policy.get('producer_name', 'N/A')}")
        print(f"Years in Business: {policy.get('years_in_business', 'N/A')}")
        
        # Claim Information
        print("\n" + "-"*70)
        print("CLAIM INFORMATION")
        print("-"*70)
        claim = results["claim_data"]
        print(f"Policy Number: {claim.get('policy_number', 'N/A')}")
        print(f"Claim Number: {claim.get('claim_number', 'N/A')}")
        print(f"Date of Loss: {claim.get('date_of_loss', 'N/A')}")
        print(f"Claim Type: {claim.get('claim_type', 'N/A')}")
        
        print("\n" + "="*70)
        print("END OF REPORT")
        print("="*70 + "\n")
    
    def _format_markdown_to_html(self, text):
        """Convert basic markdown formatting to HTML."""
        import re
        
        # Replace **text** with <strong>text</strong>
        text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
        
        # Replace ### Heading with <h3>Heading</h3>
        text = re.sub(r'^### (.+)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^## (.+)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
        text = re.sub(r'^# (.+)$', r'<h1>\1</h1>', text, flags=re.MULTILINE)
        
        # Replace - bullet points with <li> items
        lines = text.split('\n')
        formatted_lines = []
        in_list = False
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('- '):
                if not in_list:
                    formatted_lines.append('<ul>')
                    in_list = True
                formatted_lines.append(f'<li>{stripped[2:]}</li>')
            else:
                if in_list:
                    formatted_lines.append('</ul>')
                    in_list = False
                formatted_lines.append(line)
        
        if in_list:
            formatted_lines.append('</ul>')
        
        text = '\n'.join(formatted_lines)
        
        # Replace newlines with <br> for paragraphs
        text = text.replace('\n\n', '</p><p>')
        
        return text
    
    def _generate_pdf_from_html(self, html_content, pdf_path):
        """
        Generate a PDF from HTML content using Playwright.
        This renders the HTML exactly like browser's Ctrl+P print-to-PDF.
        
        Args:
            html_content: The HTML string to convert
            pdf_path: Path where the PDF should be saved
            
        Returns:
            True if successful, False otherwise
        """
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as p:
                # Launch headless Chromium
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                
                # Load the HTML content
                page.set_content(html_content, wait_until='networkidle')
                
                # Generate PDF with settings that match browser's Ctrl+P
                page.pdf(
                    path=pdf_path,
                    format='A4',
                    print_background=True,  # Include background colors/images
                    margin={
                        'top': '10mm',
                        'bottom': '10mm',
                        'left': '10mm',
                        'right': '10mm'
                    }
                )
                
                browser.close()
                return True
                
        except Exception as e:
            print(f"⚠ Error generating PDF: {str(e)}")
            return False
    
    def _generate_html_report(self, results):
        """Generate an HTML report."""
        # Format executive summary
        executive_summary_html = self._format_markdown_to_html(results['executive_summary'])
        
        # Determine background color based on risk level
        risk_level = results['fraud_detection']['risk_level']
        if risk_level == 'LOW':
            bg_color = '#d4edda'  # Light green
            border_color = '#28a745'  # Green
        elif risk_level == 'MODERATE':
            bg_color = '#fff3cd'  # Light yellow
            border_color = '#ffc107'  # Yellow
        elif risk_level == 'HIGH':
            bg_color = '#f8d7da'  # Light red
            border_color = '#dc3545'  # Red
        else:  # CRITICAL
            bg_color = '#f5c6cb'  # Darker red
            border_color = '#c82333'  # Dark red
        
        # Simple HTML template
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Fraud Detection Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background-color: #f5f5f5; line-height: 1.6; }}
        .container {{ max-width: 1200px; margin: 0 auto; background-color: white; padding: 30px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; border-bottom: 2px solid #ecf0f1; padding-bottom: 5px; }}
        h3 {{ color: #5a6c7d; margin-top: 20px; }}
        .summary {{ background-color: #ecf0f1; padding: 20px; border-left: 4px solid #3498db; margin: 20px 0; }}
        .risk-high {{ color: #e74c3c; font-weight: bold; }}
        .risk-moderate {{ color: #f39c12; font-weight: bold; }}
        .risk-low {{ color: #27ae60; font-weight: bold; }}
        .risk-critical {{ color: #c0392b; font-weight: bold; }}
        .flag {{ margin: 10px 0; padding: 15px; background-color: #fff3cd; border-left: 4px solid #ffc107; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #3498db; color: white; }}
        .metadata {{ font-size: 0.9em; color: #7f8c8d; margin-bottom: 20px; }}
        .ai-analysis {{ background-color: #f8f9fa; padding: 20px; border-radius: 5px; margin: 20px 0; }}
        .ai-analysis ul {{ margin: 10px 0; padding-left: 25px; }}
        .ai-analysis li {{ margin: 8px 0; }}
        .ai-analysis p {{ margin: 15px 0; }}
        strong {{ color: #2c3e50; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Claims Fraud Detection Report</h1>
        
        <div class="metadata">
            <p><strong>Claim File:</strong> {results['metadata']['claim_file']}</p>
            <p><strong>Policy Number:</strong> {results['metadata']['policy_number']}</p>
            <p><strong>Named Insured:</strong> {results['policy_data'].get('named_insured', 'N/A')}</p>
            <p><strong>Analysis Date:</strong> {results['metadata']['analysis_date']}</p>
        </div>
        
        <h2>Fraud Detection Verdict</h2>
        <div style="background-color: {bg_color}; padding: 20px; border-left: 4px solid {border_color}; margin: 20px 0;">
            <p style="font-size: 1.3em; margin: 10px 0;"><strong>Fraud Risk:</strong> <span class="risk-{results['fraud_detection']['risk_level'].lower()}">{results['fraud_detection']['risk_level']}</span></p>
            <p style="margin: 5px 0;"><strong>Fraud Indicators:</strong> {results['fraud_detection']['flags_count']}</p>
            <p style="margin: 5px 0;"><strong>Risk Score:</strong> {results['fraud_detection']['risk_score']}</p>
        </div>
        
        <h2>Summary</h2>
        <div class="summary">
            <div class="ai-analysis">{executive_summary_html}</div>
        </div>
        
        <h2>Fraud Indicators (Rule-Based Detection)</h2>
"""
        
        for flag in results['fraud_detection']['flags']:
            html += f"""
        <div class="flag">
            <strong>[{flag['risk_level']}]</strong> {flag['description']}<br>
            {f"<em>{flag['details']}</em>" if flag.get('details') else ''}
        </div>
"""
        
        html += f"""
        
        <h2>Policy Information</h2>
        <table>
            <tr><th>Field</th><th>Value</th></tr>
            <tr><td>Named Insured</td><td>{results['policy_data'].get('named_insured', 'N/A')}</td></tr>
            <tr><td>Policy Number</td><td>{results['policy_data'].get('policy_number', 'N/A')}</td></tr>
            <tr><td>Effective Date</td><td>{results['policy_data'].get('effective_date', 'N/A')}</td></tr>
            <tr><td>Years in Business</td><td>{results['policy_data'].get('years_in_business', 'N/A')}</td></tr>
        </table>
        
        <h2>Claim Information</h2>
        <table>
            <tr><th>Field</th><th>Value</th></tr>
            <tr><td>Date of Loss</td><td>{results['claim_data'].get('date_of_loss', 'N/A')}</td></tr>
            <tr><td>Claim Type</td><td>{results['claim_data'].get('claim_type', 'N/A')}</td></tr>
        </table>
        
    </div>
</body>
</html>
"""
        return html
    
    def save_results(self, results, output_dir="output", email_metadata=None, input_pdf_path=None):
        """Save results to files and optionally send email.
        
        Args:
            results: Analysis results dictionary
            output_dir: Directory to save output files
            email_metadata: Optional dict from companion JSON for sending email
                          - Must have 'toRecipients' field with valid email address
                          - Example: {"toRecipients": "user@example.com", "subject": "...", ...}
                          - If missing or invalid, email will not be sent (with warning)
            input_pdf_path: Optional path to the original claim PDF (for email attachment)
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate output filename based on input PDF name
        if input_pdf_path:
            base_name = os.path.splitext(os.path.basename(input_pdf_path))[0]
            output_base_name = f"{base_name}_report"
        else:
            # Fallback to timestamp if no input path provided
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_base_name = f"fraud_report_{timestamp}"
        
        # Save JSON
        json_path = os.path.join(output_dir, f"{output_base_name}.json")
        with open(json_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"✓ JSON report saved: {json_path}")
        
        # Save HTML
        html_path = os.path.join(output_dir, f"{output_base_name}.html")
        html_content = self._generate_html_report(results)
        with open(html_path, 'w') as f:
            f.write(html_content)
        print(f"✓ HTML report saved: {html_path}")
        
        # Save PDF (rendered from HTML using Playwright - looks exactly like browser's Ctrl+P)
        pdf_path = os.path.join(output_dir, f"{output_base_name}.pdf")
        if self._generate_pdf_from_html(html_content, pdf_path):
            print(f"✓ PDF report saved: {pdf_path}")
        else:
            pdf_path = None
            print("⚠ PDF generation failed, continuing without PDF")
        
        # Upload HTML and PDF to OneDrive if enabled
        report_web_url = None
        output_folder_url = None
        
        if self.onedrive_client:
            print("\n📤 Uploading reports to OneDrive...")
            
            # Upload HTML
            upload_result = self.onedrive_client.upload_file(html_path, self.onedrive_output_folder)
            if upload_result:
                print(f"✓ HTML report uploaded to OneDrive: {upload_result['name']}")
                if upload_result.get('web_url'):
                    print(f"  View online: {upload_result['web_url']}")
            else:
                print("⚠ Failed to upload HTML report to OneDrive")
            
            # Upload PDF if generated
            if pdf_path:
                upload_result = self.onedrive_client.upload_file(pdf_path, self.onedrive_output_folder)
                if upload_result:
                    print(f"✓ PDF report uploaded to OneDrive: {upload_result['name']}")
                    if upload_result.get('web_url'):
                        report_web_url = upload_result['web_url']  # Use PDF URL for the report link
                        print(f"  View online: {upload_result['web_url']}")
                else:
                    print("⚠ Failed to upload PDF report to OneDrive")
            
            # Get the output folder URL
            try:
                folder_info = self.onedrive_client.get_folder_info(self.onedrive_output_folder)
                if folder_info and folder_info.get('web_url'):
                    output_folder_url = folder_info['web_url']
            except:
                pass  # Folder URL is optional
        
        # Send email with HTML report if email metadata is available
        if self.email_sender:
            if email_metadata:
                recipient = get_recipient_email(email_metadata)
                if recipient:
                    print(f"\n📧 Sending fraud report email to: {recipient}")
                    if self.email_sender.send_fraud_report_email(
                        recipient, email_metadata, html_content,
                        input_pdf_path=input_pdf_path,
                        output_pdf_path=pdf_path,
                        report_web_url=report_web_url,
                        output_folder_url=output_folder_url
                    ):
                        print(f"✓ Email sent successfully to {recipient}")
                    else:
                        print(f"⚠ Failed to send email to {recipient}")
                else:
                    print("⚠ No recipient email found in companion JSON")
                    print(f"   Email metadata present but 'toRecipients' is empty or missing")
            else:
                print("⚠ No email metadata available (companion JSON not found or invalid)")
        
        return json_path, html_path, pdf_path


def run_single_pass(claim_file_arg=None):
    """Run a single pass of file processing."""
    import sys
    
    load_dotenv()  # Load environment variables
    
    # Check if OneDrive is enabled
    onedrive_enabled = os.getenv("ONEDRIVE_ENABLED", "0") == "1"
    
    if onedrive_enabled:
        print("\n" + "="*70)
        print("ONEDRIVE FILE FETCHING")
        print("="*70)
        
        tenant_id = os.getenv("ONEDRIVE_TENANT_ID")
        client_id = os.getenv("ONEDRIVE_CLIENT_ID")
        client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")
        user_email = os.getenv("ONEDRIVE_USER_EMAIL")
        folder_name = os.getenv("ONEDRIVE_FOLDER_NAME", "Input_attachments")
        
        # Require app credentials (no delegated/interactive mode supported)
        if client_secret and user_email:
            print(f"📁 Connecting to OneDrive (automated mode)...")
            print(f"   User: {user_email}")
            print(f"   Folder: {folder_name}")
            onedrive = OneDriveClientApp(tenant_id, client_id, client_secret, user_email, folder_name)
        else:
            print("✗ Error: ONEDRIVE_CLIENT_SECRET and ONEDRIVE_USER_EMAIL are required when ONEDRIVE_ENABLED=1")
            return 1
        
        # List and filter files from OneDrive
        print(f"\n📁 Listing files in OneDrive folder '{folder_name}'...")
        try:
            all_files = onedrive.list_files()
        except Exception as e:
            print(f"✗ Error listing files: {e}")
            return 1

        # Helper function to categorize files
        def is_target_file(filename):
            """Check if file matches C*.pdf or C*.pdf.json pattern."""
            name_upper = filename.upper()
            name_lower = filename.lower()
            
            # Check if it starts with C followed by a digit
            if not (name_upper.startswith('C') and len(filename) > 1 and filename[1].isdigit()):
                return False, None
            
            # Check if it's a PDF or PDF.json file
            if name_lower.endswith('.pdf'):
                return True, 'pdf'
            elif name_lower.endswith('.pdf.json'):
                return True, 'json'
            
            return False, None
        
        # Filter for C1, C2, etc. (PDFs and companion JSON files)
        pdf_files = []
        json_files = []
        for f in all_files:
            is_target, file_type = is_target_file(f['name'])
            if is_target:
                if file_type == 'pdf':
                    pdf_files.append(f)
                elif file_type == 'json':
                    json_files.append(f)
        
        if not pdf_files:
            print("\n⚠ No matching PDF files (starting with C1, C2...) found in OneDrive folder")
            return 0
            
        downloaded_files = []
        print(f"   Found {len(pdf_files)} PDF files and {len(json_files)} companion JSON files")
        
        # Download new files
        local_dir = "input"
        os.makedirs(local_dir, exist_ok=True)
        
        # First, download companion JSON files (just save, don't add to processing list)
        for file_info in json_files:
            local_path = os.path.join(local_dir, file_info['name'])
            
            if os.path.exists(local_path):
                print(f"\n⚠ Skipping existing JSON: {file_info['name']}")
                continue
                
            print(f"\n📥 Downloading companion JSON: {file_info['name']}")
            try:
                path = onedrive.download_file(file_info, local_dir=local_dir)
                if path:
                    print(f"   ✓ JSON saved to: {path}")
            except Exception as e:
                print(f"✗ Error downloading {file_info['name']}: {e}")
        
        # Download PDF files for processing
        for file_info in pdf_files:
            local_path = os.path.join(local_dir, file_info['name'])
            
            # Match behavior: only process new files
            if os.path.exists(local_path):
                print(f"\n⚠ Skipping existing file: {file_info['name']}")
                continue
                
            print(f"\n📥 Downloading: {file_info['name']}")
            try:
                path = onedrive.download_file(file_info, local_dir=local_dir)
                if path:
                    downloaded_files.append(path)
                    print(f"   ✓ Saved to: {path}")
            except Exception as e:
                print(f"✗ Error downloading {file_info['name']}: {e}")
        
        if not downloaded_files:
            print("\n⚠ No new files to process")
            return 0
            
        print(f"\n✓ Downloaded {len(downloaded_files)} new file(s) from OneDrive")
    
    # Determine which files to process
    if onedrive_enabled and downloaded_files:
        # Process all downloaded files
        claim_files = downloaded_files
    else:
        # Check command-line arguments for local file
        if not claim_file_arg:
            print("\nUsage: python app.py <claim_pdf>")
            print("\nExample:")
            print("  python app.py C1_JohnDoe_Jetwire.pdf")
            print("\nOr enable OneDrive in .env file:")
            print("  ONEDRIVE_ENABLED=1")
            print("\nThe system will automatically match the claim with the policy in the database.")
            return 1
        
        claim_pdf = claim_file_arg
        
        # Check if file exists
        if not os.path.exists(claim_pdf):
            print(f"Error: Claim file not found: {claim_pdf}")
            return 1
        
        claim_files = [claim_pdf]
    
    # Initialize fraud detection system
    fraud_system = FraudDetectionSystem(use_ai=True)
    
    # Process each file
    for i, claim_file in enumerate(claim_files, 1):
        if len(claim_files) > 1:
            print(f"\n{'='*70}")
            print(f"PROCESSING FILE {i}/{len(claim_files)}: {os.path.basename(claim_file)}")
            print(f"{'='*70}")
        
        # Analyze the claim
        results = fraud_system.analyze_claim(claim_file)
        
        # Check for errors
        if "error" in results:
            print(f"\n✗ Analysis failed: {results['error']}")
            continue
        
        # Generate and display report
        fraud_system.generate_report(results, output_format="console")
        
        # Load email metadata from companion JSON if it exists
        json_path = claim_file + ".json"
        email_metadata = load_email_metadata(json_path)
        
        # Save results and send email if metadata available
        fraud_system.save_results(results, email_metadata=email_metadata, input_pdf_path=claim_file)
        
        # Delete processed files from input folder
        try:
            # Delete PDF
            os.remove(claim_file)
            print(f"   ✓ Deleted local PDF: {os.path.basename(claim_file)}")
            
            # Delete companion JSON if exists
            if os.path.exists(json_path):
                os.remove(json_path)
                print(f"   ✓ Deleted local JSON: {os.path.basename(json_path)}")
        except Exception as del_error:
            print(f"   ⚠ Warning: Failed to delete local files: {del_error}")
        
        print(f"\n✓ Analysis complete for {os.path.basename(claim_file)}!")
    
    print(f"\n{'='*70}")
    print(f"✓ All files processed! ({len(claim_files)} total)")
    print(f"{'='*70}\n")
    
    return 0


def watch_mode():
    """
    Continuously monitor OneDrive SharePoint folder for new files
    and process them automatically.
    """
    load_dotenv()
    
    # OneDrive configuration
    tenant_id = os.getenv("ONEDRIVE_TENANT_ID")
    client_id = os.getenv("ONEDRIVE_CLIENT_ID")
    client_secret = os.getenv("ONEDRIVE_CLIENT_SECRET")
    user_email = os.getenv("ONEDRIVE_USER_EMAIL")
    folder_name = os.getenv("ONEDRIVE_FOLDER_NAME", "Input_attachments")
    
    if not all([tenant_id, client_id, client_secret, user_email]):
        print("✗ Error: Missing OneDrive credentials")
        print("  Required: ONEDRIVE_TENANT_ID, ONEDRIVE_CLIENT_ID, ONEDRIVE_CLIENT_SECRET, ONEDRIVE_USER_EMAIL")
        return 1
    
    # Local folder for processed files
    processed_folder = "input"
    os.makedirs(processed_folder, exist_ok=True)
    
    # Initialize OneDrive client and fraud detection system
    onedrive = OneDriveClientApp(tenant_id, client_id, client_secret, user_email, folder_name)
    fraud_system = FraudDetectionSystem(use_ai=True)
    
    print("\n" + "="*70)
    print("ONEDRIVE MONITORING SERVICE STARTED")
    print("="*70)
    print(f"Monitoring OneDrive: {user_email}/{folder_name}")
    print(f"Processed files saved to: {os.path.abspath(processed_folder)}")
    print("Press Ctrl+C to stop")
    print("="*70 + "\n")
    
    # Track processed files by name (both PDF and JSON)
    processed_files = set()
    
    # Initial scan - mark existing files in input folder as processed
    if os.path.exists(processed_folder):
        for filename in os.listdir(processed_folder):
            if filename.lower().endswith('.pdf') or filename.lower().endswith('.pdf.json'):
                processed_files.add(filename)
    
    # Check if running in background/non-interactive mode
    is_interactive = sys.stdout.isatty()
    
    try:
        iteration = 0
        while True:
            try:
                iteration += 1
                
                # List files from OneDrive
                onedrive_files = onedrive.list_files()
                
                # Check for RESET_CACHE.txt
                reset_file = next((f for f in onedrive_files if f['name'] == 'RESET_CACHE.txt'), None)
                if reset_file:
                    print("\n" + "="*70)
                    print("🧹 RESET TRIGGERED: checking for RESET_CACHE.txt")
                    
                    # Clear local input folder
                    print(f"Clearing local folder: {processed_folder}...")
                    for filename in os.listdir(processed_folder):
                        file_path = os.path.join(processed_folder, filename)
                        try:
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                        except Exception as e:
                            print(f"  ✗ Could not delete {filename}: {e}")
                    
                    # Reset processed files set
                    processed_files.clear()
                    print("✓ Local cache cleared")
                    
                    # Delete RESET_CACHE.txt from OneDrive
                    print("Deleting RESET_CACHE.txt from OneDrive...")
                    try:
                        onedrive.delete_file(reset_file['id'])
                        print("✓ Remote reset file deleted")
                    except Exception as e:
                        print(f"✗ Failed to delete remote reset file: {e}")
                    
                    print("="*70 + "\n")
                    
                    # Start fresh check immediately
                    continue
                
                # Filter PDF and JSON files
                # Only process files starting with 'C' followed by a number (e.g., C1, C2...)
                # Also pick up companion JSON files (e.g., C1_test.pdf.json)
                
                def is_target_file(filename):
                    """Check if file matches C*.pdf or C*.pdf.json pattern."""
                    name_upper = filename.upper()
                    name_lower = filename.lower()
                    
                    # Check if it starts with C followed by a digit
                    if not (name_upper.startswith('C') and len(filename) > 1 and filename[1].isdigit()):
                        return False, None
                    
                    # Check if it's a PDF or PDF.json file
                    if name_lower.endswith('.pdf'):
                        return True, 'pdf'
                    elif name_lower.endswith('.pdf.json'):
                        return True, 'json'
                    
                    return False, None
                
                # Categorize files
                target_files = []
                for f in onedrive_files:
                    is_target, file_type = is_target_file(f['name'])
                    if is_target:
                        f['_file_type'] = file_type  # Add metadata for later use
                        target_files.append(f)
                
                # Separate into PDF files (for processing) and all target files (for tracking)
                pdf_files = [f for f in target_files if f['_file_type'] == 'pdf']
                
                # Separate PDF files from JSON files
                new_pdf_files = [f for f in target_files if f['_file_type'] == 'pdf']
                new_json_files = [f for f in target_files if f['_file_type'] == 'json']
                
                # Match PDF-JSON pairs: only process PDFs that have companion JSON files
                pdf_json_pairs = []
                for pdf_file in new_pdf_files:
                    pdf_name = pdf_file['name']
                    json_name = pdf_name + ".json"
                    
                    # Check if companion JSON exists in files
                    json_file = next((f for f in new_json_files if f['name'] == json_name), None)
                    
                    if json_file:
                        pdf_json_pairs.append({
                            'pdf': pdf_file,
                            'json': json_file,
                            'pdf_name': pdf_name,
                            'json_name': json_name
                        })
                    else:
                        print(f"\n⚠ Skipping {pdf_name} - waiting for companion JSON ({json_name})")
                
                # Show status every check
                status_msg = f"[{datetime.now().strftime('%H:%M:%S')}] Check #{iteration}: {len(pdf_files)} PDFs, {len(target_files)} total files, {len(pdf_json_pairs)} pairs ready"
                
                if is_interactive:
                    print(status_msg, end='\r')
                elif iteration == 1 or iteration % 60 == 0 or pdf_json_pairs:
                     # Log less frequently in background mode (every ~10 mins) or when activity occurs
                    print(status_msg)
                
                if pdf_json_pairs:
                    print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Found {len(pdf_json_pairs)} PDF-JSON pair(s) ready to process")
                    for pair in pdf_json_pairs:
                        print(f"  - {pair['pdf_name']} + {pair['json_name']}")
                
                # Process PDF-JSON pairs together
                for pair in pdf_json_pairs:
                    pdf_file_info = pair['pdf']
                    json_file_info = pair['json']
                    pdf_filename = pair['pdf_name']
                    json_filename = pair['json_name']
                    
                    temp_pdf_path = None
                    
                    print(f"\n{'='*70}")
                    print(f"📦 Processing pair: {pdf_filename} + {json_filename}")
                    print(f"{'='*70}")
                    
                    try:
                        # Download both files simultaneously to input folder before processing
                        print(f"\n📥 Downloading files to input folder...")
                        
                        # Download JSON if not already downloaded
                        json_path = os.path.join(processed_folder, json_filename)
                        if json_file_info:  # JSON is new, need to download
                            print(f"   Downloading: {json_filename}")
                            json_path = onedrive.download_file(json_file_info, local_dir=processed_folder)
                            print(f"   ✓ JSON saved: {json_path}")
                        else:
                            print(f"   ✓ Using existing JSON: {json_filename}")
                        
                        # Download PDF directly to input folder
                        pdf_path = os.path.join(processed_folder, pdf_filename)
                        print(f"   Downloading: {pdf_filename}")
                        pdf_path = onedrive.download_file(pdf_file_info, local_dir=processed_folder)
                        print(f"   ✓ PDF saved: {pdf_path}")
                        
                        # Load email metadata before processing
                        print(f"\n📧 Loading email metadata from: {json_path}")
                        email_metadata = load_email_metadata(json_path)
                        
                        # Process the PDF
                        print(f"\n🔍 Processing claim: {pdf_filename}")
                        results = fraud_system.analyze_claim(pdf_path)
                        
                        if "error" in results:
                            print(f"\n✗ Analysis failed: {results['error']}")
                        else:
                            # Generate report and send email
                            fraud_system.generate_report(results, output_format="console")
                            fraud_system.save_results(results, email_metadata=email_metadata, input_pdf_path=pdf_path)
                            print(f"\n✓ Analysis complete for {pdf_filename}!")
                        
                        # Delete processed local files from input folder
                        try:
                            # Delete PDF
                            os.remove(pdf_path)
                            print(f"   ✓ Deleted local PDF: {pdf_filename}")
                            
                            # Delete JSON
                            if os.path.exists(json_path):
                                os.remove(json_path)
                                print(f"   ✓ Deleted local JSON: {json_filename}")
                        except Exception as del_error:
                            print(f"   ⚠ Warning: Failed to delete local files: {del_error}")
                        
                        # Move both PDF and JSON to processed folder on OneDrive
                        processed_folder_name = fraud_system.onedrive_processed_folder
                        print(f"\n📋 Moving files to {processed_folder_name} on OneDrive...")
                        try:
                            # Move PDF file
                            if onedrive.move_file(pdf_file_info['id'], processed_folder_name):
                                print(f"   ✓ Moved PDF to {processed_folder_name}: {pdf_filename}")
                            
                            # Move companion JSON file if it exists
                            if json_file_info:
                                if onedrive.move_file(json_file_info['id'], processed_folder_name):
                                    print(f"   ✓ Moved JSON to {processed_folder_name}: {json_filename}")
                        except Exception as move_error:
                            print(f"   ⚠ Warning: Failed to move files on OneDrive: {move_error}")
                        
                    except Exception as e:
                        print(f"✗ Error processing pair {pdf_filename}: {str(e)}")
                
            except Exception as e:
                print(f"\n✗ Error checking OneDrive: {str(e)}")
                print("   Will retry in 10 seconds...")
            
            # Wait before next check (adjust polling interval as needed)
            time.sleep(10)  # Check every 10 seconds
            
    except KeyboardInterrupt:
        print("\n\n" + "="*70)
        print("ONEDRIVE MONITORING SERVICE STOPPED")
        print("="*70)
        
        # Clear input directory
        print("Clearing input directory...")
        try:
            if os.path.exists(processed_folder):
                for filename in os.listdir(processed_folder):
                    file_path = os.path.join(processed_folder, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.remove(file_path)
                    except Exception as e:
                        print(f"  ✗ Could not delete {filename}: {e}")
                print("✓ Input directory cleared")
        except Exception as e:
            print(f"✗ Error clearing input directory: {e}")
        
        print("="*70)
        return 0


if __name__ == "__main__":
    def main():
        """Main entry point"""
        
        # Parse command line arguments
        parser = argparse.ArgumentParser(description='Claims Fraud Detection System')
        parser.add_argument('--port', type=int, help='Port number (ignored, for compatibility)')
        parser.add_argument('--host', type=str, help='Host address (ignored, for compatibility)')
        parser.add_argument('claim_file', nargs='?', help='Specific claim file to process (optional)')
        
        # Parse args
        args = parser.parse_args()
        
        # Force output to be unbuffered for nohup
        sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', buffering=1)
        sys.stderr = os.fdopen(sys.stderr.fileno(), 'w', buffering=1)
        
        print(f"Starting Claims Fraud Detection System at {datetime.now()}")
        print(f"Python unbuffered output enabled for logging")
        sys.stdout.flush()
        
        # Determine strict nohup/background mode - if port/host args are present or no args, assume watching
        
        try:
            # If a specific file is provided, run once
            if args.claim_file:
                 sys.exit(run_single_pass(args.claim_file))
            else:
                # Default to watch mode (especially for nohup which typically has no file args)
                watch_mode()
            
        except Exception as e:
            print(f"\n✗ Fatal error: {str(e)}")
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            sys.exit(1)

    main()
