"""
Flask API Server for Claims Fraud Detection
Splits the workflow into two parts:
1. Watcher detects files, extracts details, stores in session
2. Frontend confirms email fields, triggers processing via API
"""

import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for frontend communication

# Configuration
CONFIG = {
    "INPUT_FOLDER": "./input",
    "OUTPUT_FOLDER": "./output",
    "SESSION_TIMEOUT_MINUTES": 30,
    "TENANT_ID": os.getenv("ONEDRIVE_TENANT_ID"),
    "CLIENT_ID": os.getenv("ONEDRIVE_CLIENT_ID"),
    "CLIENT_SECRET": os.getenv("ONEDRIVE_CLIENT_SECRET"),
    "USER_EMAIL": os.getenv("ONEDRIVE_USER_EMAIL"),
    "ONEDRIVE_INPUT_FOLDER": os.getenv("ONEDRIVE_FOLDER_NAME", "Input_attachments"),
    "ONEDRIVE_OUTPUT_FOLDER": os.getenv("ONEDRIVE_OUTPUT_FOLDER", "Output_attachments"),
}

# Create folders
os.makedirs(CONFIG['INPUT_FOLDER'], exist_ok=True)
os.makedirs(CONFIG['OUTPUT_FOLDER'], exist_ok=True)

# In-memory session storage (shared with watcher)
sessions = {}


class SessionData:
    """Store session data for a claims fraud processing request"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = datetime.now()
        self.pdf_path = None
        self.json_path = None
        self.claim_data = None  # Extracted claim fields
        self.email_metadata = None  # From companion JSON
        self.email_fields = None  # LLM-extracted email fields (sender, receiver, etc.)
        self.confirmed_email_fields = None  # Confirmed by frontend
        self.processing_complete = False
        self.results = None  # Fraud analysis results
        self.output_pdf_path = None
        self.output_pdf_url = None
        self.form_pdf_path = None  # Form PDF from frontend
        self.form_pdf_url = None  # OneDrive URL for form PDF
        # OneDrive file IDs for cleanup
        self.onedrive_pdf_id = None
        self.onedrive_json_id = None
        self.claims_folder_path = None
    
    def is_expired(self) -> bool:
        """Check if session has expired"""
        timeout = timedelta(minutes=CONFIG['SESSION_TIMEOUT_MINUTES'])
        return datetime.now() - self.created_at > timeout
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat(),
            'has_pdf': self.pdf_path is not None,
            'has_claim_data': self.claim_data is not None,
            'has_email_metadata': self.email_metadata is not None,
            'has_email_fields': self.email_fields is not None,
            'has_confirmed_fields': self.confirmed_email_fields is not None,
            'processing_complete': self.processing_complete,
        }


def cleanup_expired_sessions():
    """Remove expired sessions"""
    expired = [sid for sid, session in sessions.items() if session.is_expired()]
    for sid in expired:
        sessions.pop(sid, None)


# Error handlers to ensure all responses are JSON
@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors with JSON response"""
    return jsonify({
        'error': 'Not Found',
        'message': 'The requested resource was not found',
        'status': 404
    }), 404


@app.errorhandler(405)
def method_not_allowed(error):
    """Handle 405 Method Not Allowed with JSON response"""
    return jsonify({
        'error': 'Method Not Allowed',
        'message': 'The method is not allowed for the requested URL',
        'status': 405
    }), 405


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors with JSON response"""
    return jsonify({
        'error': 'Internal Server Error',
        'message': 'An internal server error occurred',
        'status': 500
    }), 500


@app.errorhandler(Exception)
def handle_exception(error):
    """Handle all uncaught exceptions with JSON response"""
    return jsonify({
        'error': 'Internal Server Error',
        'message': str(error),
        'status': 500
    }), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'claims-fraud-api',
        'timestamp': datetime.now().isoformat(),
        'active_sessions': len(sessions)
    })


@app.route('/api/pending', methods=['GET'])
def get_pending_files():
    """
    Get list of files detected by watcher that are pending frontend processing
    Frontend uses this to see what files need processing
    
    Returns 200 only when files are available, 404 otherwise
    """
    cleanup_expired_sessions()
    
    pending_list = []
    for session_id, session in sessions.items():
        # Session is pending if it has claim_data but not yet processed
        if session.claim_data and not session.processing_complete:
            pending_list.append({
                'filename': os.path.basename(session.pdf_path) if session.pdf_path else None,
                'claim_data': session.claim_data,
                'email_metadata': session.email_metadata,
                'email_fields': session.email_fields,  # Include extracted email fields
                'detected_at': session.created_at.isoformat(),
                'has_email_metadata': session.email_metadata is not None,
                'has_email_fields': session.email_fields is not None,
                'has_confirmed_fields': session.confirmed_email_fields is not None,
                '_session_id': session_id
            })
    
    if len(pending_list) == 0:
        return jsonify({
            'success': False,
            'message': 'No pending files found. Waiting for watcher to detect files.'
        }), 404
    
    return jsonify({
        'success': True,
        'count': len(pending_list),
        'files': pending_list
    }), 200


@app.route('/api/pending/latest', methods=['GET'])
def get_latest_pending_file():
    """
    Get the most recent file detected by watcher
    Returns just one file with extracted data
    """
    cleanup_expired_sessions()
    
    # Find most recent pending session
    latest_session = None
    latest_time = None
    
    for session_id, session in sessions.items():
        if session.claim_data and not session.processing_complete:
            if latest_time is None or session.created_at > latest_time:
                latest_session = session
                latest_time = session.created_at
    
    if not latest_session:
        return jsonify({
            'success': False,
            'message': 'No pending files found'
        }), 404
    
    return jsonify({
        'success': True,
        'filename': os.path.basename(latest_session.pdf_path) if latest_session.pdf_path else None,
        'claim_data': latest_session.claim_data,
        'email_metadata': latest_session.email_metadata,
        'detected_at': latest_session.created_at.isoformat(),
        'has_email_metadata': latest_session.email_metadata is not None
    }), 200


@app.route('/api/email-fields', methods=['POST'])
def confirm_email_fields():
    """
    POST endpoint to confirm/update email fields from frontend
    
    Expects JSON:
    {
        "filename": "C1_test.pdf",  // Required to identify which file
        "email_fields": {
            "broker_email": "...",
            "broker_name": "...",
            "policy_number": "...",
            ...
        },
        "form_pdf": "base64_encoded_pdf"  // Optional form PDF from frontend
    }
    
    OR by session_id:
    {
        "session_id": "...",
        "email_fields": { ... },
        "form_pdf": "base64_encoded_pdf"
    }
    
    Returns:
    - success: Boolean
    - confirmed_email_fields: The confirmed data
    - policy_number_changed: Boolean indicating if policy number was updated
    """
    cleanup_expired_sessions()
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Get email fields from request
        email_fields = data.get('email_fields', {})
        form_pdf_base64 = data.get('form_pdf')  # Optional base64 PDF from frontend
        
        # Find session by filename or session_id
        session = None
        session_id = data.get('session_id')
        filename = data.get('filename')
        
        if session_id:
            session = sessions.get(session_id)
        elif filename:
            for sid, sess in sessions.items():
                if sess.pdf_path and os.path.basename(sess.pdf_path) == filename:
                    session = sess
                    session_id = sid
                    break
        else:
            return jsonify({'error': 'Either filename or session_id is required'}), 400
        
        if not session:
            if filename:
                return jsonify({'error': f'No session found for filename: {filename}'}), 404
            else:
                return jsonify({'error': 'Session not found or expired'}), 404
        
        # Compare policy numbers
        policy_number_changed = False
        new_policy_number = email_fields.get('policy_number')
        
        # Get original policy number from extracted email fields or claim data
        original_policy_number = None
        if session.email_fields:
            original_policy_number = session.email_fields.get('policy_number')
        elif session.claim_data:
            original_policy_number = session.claim_data.get('policy_number')
        
        if original_policy_number and new_policy_number:
            if original_policy_number != new_policy_number:
                policy_number_changed = True
                print(f"[EMAIL_FIELDS] Policy number changed:")
                print(f"[EMAIL_FIELDS]   Original: {original_policy_number}")
                print(f"[EMAIL_FIELDS]   New: {new_policy_number}")
        
        # Store confirmed email fields (with potentially updated policy number)
        session.confirmed_email_fields = email_fields
        
        # Handle form PDF upload to OneDrive if provided
        form_pdf_uploaded = False
        if form_pdf_base64:
            try:
                import base64
                from onedrive_client_app import OneDriveClientApp
                
                # Decode base64 PDF
                pdf_bytes = base64.b64decode(form_pdf_base64)
                
                # Save form PDF locally first
                form_pdf_filename = f"form_{os.path.basename(session.pdf_path).replace('.pdf', '')}.pdf"
                form_pdf_path = os.path.join(CONFIG['OUTPUT_FOLDER'], form_pdf_filename)
                
                with open(form_pdf_path, 'wb') as f:
                    f.write(pdf_bytes)
                
                print(f"[EMAIL_FIELDS] ✓ Form PDF saved locally: {form_pdf_path}")
                print(f"[EMAIL_FIELDS]   Will be uploaded to claims folder during processing")
                
                # Store path in session for later upload to claims folder
                session.form_pdf_path = form_pdf_path
                form_pdf_uploaded = True  # Indicates form PDF was received and saved
                    
            except Exception as e:
                print(f"[EMAIL_FIELDS] ⚠ Failed to process form PDF: {str(e)}")
                import traceback
                traceback.print_exc()
        
        print(f"\n{'='*70}")
        print(f"EMAIL FIELDS CONFIRMED - Session: {session_id}")
        print(f"{'='*70}")
        print(f"  Filename: {os.path.basename(session.pdf_path)}")
        print(f"  Policy: {email_fields.get('policy_number', 'N/A')}")
        if policy_number_changed:
            print(f"  ⚠ Policy number was updated by user")
        if form_pdf_uploaded:
            print(f"  ✓ Form PDF uploaded to OneDrive")
        print(f"  Broker: {email_fields.get('broker_name', 'N/A')}")
        print(f"{'='*70}\n")
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'confirmed_email_fields': email_fields,
            'policy_number_changed': policy_number_changed,
            'form_pdf_uploaded': form_pdf_uploaded,
            'message': 'Email fields confirmed successfully. Call POST /api/process to continue.'
        }), 200
    
    except Exception as e:
        print(f"✗ Email fields confirmation error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/process', methods=['POST'])
def process_claim():
    """
    PART 2: Process claim after frontend confirms email fields
    
    This triggers the fraud analysis and report generation.
    
    Expects JSON:
    {
        "filename": "C1_test.pdf"  // Required to identify which file
    }
    
    OR:
    {
        "session_id": "..."
    }
    
    Returns:
    - success: Boolean
    - results: Fraud analysis results
    - report_path: Path to generated report
    """
    cleanup_expired_sessions()
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Find session
        session = None
        session_id = data.get('session_id')
        filename = data.get('filename')
        
        if session_id:
            session = sessions.get(session_id)
        elif filename:
            for sid, sess in sessions.items():
                if sess.pdf_path and os.path.basename(sess.pdf_path) == filename:
                    if sess.claim_data:
                        session = sess
                        session_id = sid
                        break
        else:
            return jsonify({'error': 'Either filename or session_id is required'}), 400
        
        if not session:
            if filename:
                return jsonify({'error': f'No session found for filename: {filename}'}), 404
            else:
                return jsonify({'error': 'Session not found or expired'}), 404
        
        if not session.claim_data:
            return jsonify({'error': 'No extracted data found in session'}), 400
        
        if session.processing_complete:
            return jsonify({
                'success': True,
                'message': 'Already processed',
                'results': session.results,
                'output_pdf_url': session.output_pdf_url
            }), 200
        
        print(f"\n{'='*70}")
        print(f"PROCESSING REQUEST - Session: {session_id}")
        print(f"{'='*70}")
        
        # Import fraud detection system
        from app import FraudDetectionSystem
        from email_sender import load_email_metadata, get_recipient_email
        from onedrive_client_app import OneDriveClientApp
        
        # Initialize fraud system
        fraud_system = FraudDetectionSystem(use_ai=True)
        
        # Process the claim
        print(f"\n🔍 Processing claim: {os.path.basename(session.pdf_path)}")
        results = fraud_system.analyze_claim(session.pdf_path)
        
        if "error" in results:
            return jsonify({
                'success': False,
                'error': results['error']
            }), 500
        
        # Get policy number BEFORE storing results - priority order:
        # 1. Confirmed email fields (user might have corrected it)
        # 2. Extracted email fields (from LLM)
        # 3. Claim data (from PDF extraction)
        policy_number = None
        if session.confirmed_email_fields and session.confirmed_email_fields.get('policy_number'):
            policy_number = session.confirmed_email_fields.get('policy_number')
            print(f"[POLICY] Using confirmed policy number: {policy_number}")
        elif session.email_fields and session.email_fields.get('policy_number'):
            policy_number = session.email_fields.get('policy_number')
            print(f"[POLICY] Using extracted policy number: {policy_number}")
        elif session.email_metadata:
            # Fallback: Extract from email metadata using agent
            subject = session.email_metadata.get("subject", "")
            body = session.email_metadata.get("bodyPreview", "") or session.email_metadata.get("body", "")
            policy_number = fraud_system.agent.extract_policy_number(subject, body)
            print(f"[POLICY] Extracted policy number from email: {policy_number}")
        
        # Update results with confirmed policy number BEFORE storing in session
        if policy_number and 'claim_data' in results:
            results['claim_data']['policy_number'] = policy_number
            print(f"[POLICY] ✓ Updated results with confirmed policy number: {policy_number}")
        
        # Now store the updated results in session
        session.results = results
        
        # Generate console report
        fraud_system.generate_report(results, output_format="console")
        
        # Determine claims folder path
        claims_folder_path = None
            
        if policy_number:
            claim_subfolder_name = f"CN_{policy_number}"
            claims_fraud_folder = fraud_system.onedrive_claims_fraud_folder
            
            # Create subfolder
            if fraud_system.onedrive_client:
                folder_id, claims_folder_path = fraud_system.onedrive_client.create_subfolder(
                    claims_fraud_folder, claim_subfolder_name
                )
                session.claims_folder_path = claims_folder_path
                print(f"[FOLDER] Claims folder: {claims_folder_path}")
        
        # Save results and send email with confirmed policy number
        output_paths = fraud_system.save_results(
            results,
            email_metadata=session.email_metadata,
            input_pdf_path=session.pdf_path,
            claims_folder_path=claims_folder_path,
            confirmed_policy_number=policy_number  # Pass the confirmed/updated policy number
        )
        
        # Capture output PDF information
        # save_results returns: (json_path, html_path, pdf_path)
        if output_paths and isinstance(output_paths, tuple) and len(output_paths) >= 3:
            json_path, html_path, pdf_path = output_paths
            session.output_pdf_path = pdf_path
            
            # Get OneDrive file URL for the PDF
            if pdf_path and fraud_system.onedrive_client and claims_folder_path:
                try:
                    pdf_filename = os.path.basename(pdf_path)
                    # Get the actual file URL from OneDrive
                    file_path = f"{claims_folder_path}/{pdf_filename}"
                    file_info = fraud_system.onedrive_client.get_file_info(file_path)
                    
                    if file_info and file_info.get('webUrl'):
                        session.output_pdf_url = file_info['webUrl']
                        print(f"[OUTPUT] ✓ PDF file URL: {session.output_pdf_url}")
                        print(f"[OUTPUT]   File: {pdf_filename}")
                    else:
                        print(f"[OUTPUT] ⚠ Could not get file URL, trying alternative method...")
                        # Fallback: construct direct link
                        folder_info = fraud_system.onedrive_client.get_subfolder_info(claims_folder_path)
                        if folder_info and folder_info.get('web_url'):
                            # Append filename to folder URL
                            folder_url = folder_info['web_url']
                            session.output_pdf_url = f"{folder_url}/{pdf_filename}"
                            print(f"[OUTPUT] ✓ Constructed file URL: {session.output_pdf_url}")
                except Exception as e:
                    print(f"[OUTPUT] ⚠ Error getting file URL: {e}")
                    import traceback
                    traceback.print_exc()
            
            if session.output_pdf_path:
                print(f"[OUTPUT] ✓ Report PDF saved: {session.output_pdf_path}")
        
        session.processing_complete = True
        
        # Upload form PDF to claims folder if available
        if session.form_pdf_path and fraud_system.onedrive_client and claims_folder_path:
            try:
                print(f"\n[FORM_PDF] Uploading form PDF to claims folder as 'form_response.pdf'...")
                # Upload with custom name 'form_response.pdf'
                upload_url = f"https://graph.microsoft.com/v1.0/users/{fraud_system.onedrive_client.user_email}/drive/root:/{claims_folder_path}/form_response.pdf:/content"
                
                with open(session.form_pdf_path, 'rb') as f:
                    file_content = f.read()
                
                headers = fraud_system.onedrive_client._get_headers()
                headers["Content-Type"] = "application/octet-stream"
                
                import requests
                response = requests.put(upload_url, headers=headers, data=file_content)
                response.raise_for_status()
                
                result = response.json()
                if result.get('webUrl'):
                    session.form_pdf_url = result.get('webUrl')
                    print(f"[FORM_PDF] ✓ Form PDF uploaded to {claims_folder_path} as 'form_response.pdf'")
                    print(f"[FORM_PDF]   URL: {session.form_pdf_url}")
                else:
                    print(f"[FORM_PDF] ⚠ Form PDF uploaded but no URL returned")
            except Exception as e:
                print(f"[FORM_PDF] ⚠ Error uploading form PDF: {e}")
        
        # Move files on OneDrive
        if fraud_system.onedrive_client:
            onedrive = fraud_system.onedrive_client
            
            if claims_folder_path and session.onedrive_pdf_id:
                try:
                    onedrive.move_file_to_path(session.onedrive_pdf_id, claims_folder_path)
                    print(f"   ✓ Moved PDF to {claims_folder_path}")
                except Exception as e:
                    print(f"   ⚠ Failed to move PDF: {e}")
            
            if session.onedrive_json_id:
                try:
                    onedrive.delete_file(session.onedrive_json_id)
                    print(f"   ✓ Deleted JSON from OneDrive")
                except Exception as e:
                    print(f"   ⚠ Failed to delete JSON: {e}")
        
        # Clean up local files
        try:
            if session.pdf_path and os.path.exists(session.pdf_path):
                os.remove(session.pdf_path)
            if session.json_path and os.path.exists(session.json_path):
                import shutil
                processed_dir = "processed_input"
                os.makedirs(processed_dir, exist_ok=True)
                shutil.move(session.json_path, os.path.join(processed_dir, os.path.basename(session.json_path)))
        except Exception as e:
            print(f"   ⚠ Failed to clean up local files: {e}")
        
        print(f"\n✓ Processing complete for {os.path.basename(session.pdf_path)}")
        print(f"{'='*70}\n")
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'results': {
                'risk_level': results.get('fraud_detection', {}).get('risk_level', 'Unknown'),
                'risk_score': results.get('fraud_detection', {}).get('risk_score', 0),
                'flags_count': results.get('fraud_detection', {}).get('flags_count', 0)
            },
            'claims_folder': claims_folder_path,
            'message': 'Claim processed and report generated'
        }), 200
    
    except Exception as e:
        print(f"✗ Processing error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/output-pdf', methods=['GET'])
def get_output_pdf():
    """
    Get the OneDrive URL to the most recently generated output PDF
    
    Query Parameters:
        session_id (optional): Get PDF URL for specific session
        filename (optional): Get PDF URL by filename
    
    Returns:
        200: PDF URL found
        404: No PDF generated or uploaded yet
    """
    cleanup_expired_sessions()
    
    session_id = request.args.get('session_id')
    filename = request.args.get('filename')
    
    # If session_id provided, return that specific session's output PDF URL
    if session_id:
        session = sessions.get(session_id)
        if not session:
            return jsonify({
                'success': False,
                'error': 'Session not found'
            }), 404
        
        # Check if processing is complete
        if not session.processing_complete:
            return jsonify({
                'success': False,
                'error': 'Processing not yet complete',
                'processing_complete': False
            }), 404
        
        # Only return if OneDrive URL is available
        if session.output_pdf_url:
            return jsonify({
                'success': True,
                'pdf_url': session.output_pdf_url,
                'filename': os.path.basename(session.output_pdf_path) if session.output_pdf_path else None,
                'session_id': session_id,
                'created_at': session.created_at.isoformat(),
                'claims_folder': session.claims_folder_path
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': 'No output PDF URL available yet',
                'processing_complete': session.processing_complete
            }), 404
    
    # If filename provided, find by filename
    if filename:
        for sid, session in sessions.items():
            if session.pdf_path and os.path.basename(session.pdf_path) == filename:
                if session.output_pdf_url:
                    return jsonify({
                        'success': True,
                        'pdf_url': session.output_pdf_url,
                        'filename': os.path.basename(session.output_pdf_path) if session.output_pdf_path else None,
                        'session_id': sid,
                        'created_at': session.created_at.isoformat(),
                        'claims_folder': session.claims_folder_path
                    }), 200
                else:
                    return jsonify({
                        'success': False,
                        'error': 'No output PDF uploaded yet for this file'
                    }), 404
        
        return jsonify({
            'success': False,
            'error': f'No session found for filename: {filename}'
        }), 404
    
    # Otherwise, find the most recently uploaded PDF across all sessions
    latest_session = None
    latest_time = None
    
    for sid, session in sessions.items():
        if session.output_pdf_url:
            if latest_time is None or session.created_at > latest_time:
                latest_session = session
                latest_time = session.created_at
    
    if not latest_session:
        return jsonify({
            'success': False,
            'message': 'No output PDF uploaded in any active session'
        }), 404
    
    return jsonify({
        'success': True,
        'pdf_url': latest_session.output_pdf_url,
        'filename': os.path.basename(latest_session.output_pdf_path) if latest_session.output_pdf_path else None,
        'session_id': latest_session.session_id,
        'created_at': latest_session.created_at.isoformat(),
        'claims_folder': latest_session.claims_folder_path
    }), 200


@app.route('/api/sessions', methods=['GET'])
def list_sessions():
    """List all active sessions (for debugging)"""
    cleanup_expired_sessions()
    return jsonify({
        'count': len(sessions),
        'sessions': [session.to_dict() for session in sessions.values()]
    })


@app.route('/api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id: str):
    """Delete a specific session"""
    if session_id in sessions:
        sessions.pop(session_id)
        return jsonify({'success': True, 'message': 'Session deleted'})
    return jsonify({'error': 'Session not found'}), 404


if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 5000))
    print(f"\n{'='*70}")
    print(f"CLAIMS FRAUD API SERVER")
    print(f"{'='*70}")
    print(f"Starting on port {port}...")
    print(f"Endpoints:")
    print(f"  GET  /health                    - Health check")
    print(f"  GET  /claims-api/pending        - List pending files")
    print(f"  GET  /claims-api/pending/latest - Get latest pending file")
    print(f"  POST /claims-api/email-fields   - Confirm email fields")
    print(f"  POST /claims-api/process        - Process claim")
    print(f"  GET  /claims-api/output-pdf     - Get output PDF URL")
    print(f"{'='*70}\n")
    
    app.run(host='0.0.0.0', port=port, debug=False)
