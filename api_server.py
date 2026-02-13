"""
Flask API Server for Claims Fraud Detection
Workflow:
1. Watcher detects files, extracts claim data, runs fraud detection, stores session
2. Frontend extracts email fields and directly calls /process endpoint with fields
3. Backend generates and saves reports using frontend-provided policy number
"""

import os
import json
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Enable CORS with explicit permissions for ngrok and local development
CORS(app, resources={
    r"/claims-api/*": {
        "origins": "*",
        "allow_headers": ["Content-Type", "Authorization", "ngrok-skip-browser-warning", "Accept"],
        "methods": ["GET", "POST", "OPTIONS", "PUT", "DELETE"]
    },
    r"/*": {
        "origins": "*",
        "allow_headers": ["*"]
    }
})

@app.route('/debug-cors', methods=['GET'])
def debug_cors():
    """Endpoint to verify CORS headers from browser"""
    return jsonify({
        'status': 'ok',
        'message': 'If you see this, the GET request worked. Check response headers.',
        'headers_received': dict(request.headers)
    })

# ============================================================================
# DATABASE CONFIGURATION
# ============================================================================

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),
    'database': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASS')
}


@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()


def test_db_connection():
    """Test database connection"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False


# ============================================================================
# CONFIGURATION
# ============================================================================
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

# Store frontend data that arrives before watcher completes (keyed by filename)
pending_frontend_data = {}


class SessionData:
    """Store session data for a claims fraud processing request"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = datetime.now()
        self.pdf_path = None
        self.json_path = None
        self.claim_data = None  # Extracted claim fields
        self.email_metadata = None  # From companion JSON
        self.email_fields = None  # Email fields are now extracted by frontend (not backend)
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
        self.claims_folder_url = None  # OneDrive URL for claims folder
    
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


# Remove expired sessions
def cleanup_expired_sessions():
    """Remove expired sessions and old pending frontend data"""
    # Clean up expired sessions
    expired = [sid for sid, session in sessions.items() if session.is_expired()]
    for sid in expired:
        sessions.pop(sid, None)
    
    # Clean up old pending frontend data (older than 30 minutes)
    timeout = timedelta(minutes=CONFIG['SESSION_TIMEOUT_MINUTES'])
    expired_pending = []
    for filename, data in pending_frontend_data.items():
        if 'received_at' in data:
            received_time = datetime.fromisoformat(data['received_at'])
            if datetime.now() - received_time > timeout:
                expired_pending.append(filename)
    
    for filename in expired_pending:
        pending_frontend_data.pop(filename, None)


# ============================================================================
# DATABASE OPERATIONS - CLAIMS
# ============================================================================

def generate_unique_claim_id():
    """
    Generate a unique 7-digit random claim ID.
    Checks database to ensure no collision.
    
    Returns:
        String of 7-digit claim ID
    """
    import random
    max_attempts = 100
    
    for _ in range(max_attempts):
        # Generate 7-digit random number
        claim_id = str(random.randint(1000000, 9999999))
        
        # Check if it exists in database
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM claims_db WHERE claim_id = %s", (claim_id,))
                    if not cur.fetchone():
                        return claim_id
        except Exception as e:
            print(f"[DB] Warning: Could not check claim_id uniqueness: {e}")
            return claim_id  # Return anyway if DB check fails
    
    # Fallback: use timestamp-based ID if all random attempts failed
    from datetime import datetime
    return datetime.now().strftime("%Y%m%d%H%M%S")[:7]


def insert_claim(claim_data):
    """
    Insert a new claim into claims_db
    
    Args:
        claim_data: Dictionary containing claim fields
    
    Returns:
        claim_id if successful, None otherwise
    """
    try:
        # If no claim_id provided or it's empty, generate a new one
        if not claim_data.get('claim_id') or claim_data.get('claim_id').strip() == '':
            claim_data['claim_id'] = generate_unique_claim_id()
            print(f"[DB] Generated new claim_id: {claim_data['claim_id']}")
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # First check if claim_id exists
                cur.execute("SELECT 1 FROM claims_db WHERE claim_id = %s", (claim_data.get('claim_id'),))
                if cur.fetchone():
                    # Claim ID exists, generate a new one
                    print(f"[DB] Claim ID {claim_data['claim_id']} already exists, generating new ID...")
                    claim_data['claim_id'] = generate_unique_claim_id()
                    print(f"[DB] New claim_id: {claim_data['claim_id']}")
                
                query = """
                    INSERT INTO claims_db (
                        claim_id, policy_id, claim_type, date_of_loss,
                        claim_description, reporting_first_name, reporting_last_name,
                        reporting_address, reporting_city, reporting_state,
                        reporting_zip, reporting_email, reporting_phone,
                        insured_same_as_reporter, insured_first_name, insured_last_name,
                        insured_address, insured_city, insured_state,
                        insured_zip, insured_email, insured_phone,
                        injuries_reported, witness_present, witness_first_name,
                        witness_last_name, police_report_filed, claim_status, folder_url
                    ) VALUES (
                        %(claim_id)s, %(policy_id)s, %(claim_type)s, %(date_of_loss)s,
                        %(claim_description)s, %(reporting_first_name)s, %(reporting_last_name)s,
                        %(reporting_address)s, %(reporting_city)s, %(reporting_state)s,
                        %(reporting_zip)s, %(reporting_email)s, %(reporting_phone)s,
                        %(insured_same_as_reporter)s, %(insured_first_name)s, %(insured_last_name)s,
                        %(insured_address)s, %(insured_city)s, %(insured_state)s,
                        %(insured_zip)s, %(insured_email)s, %(insured_phone)s,
                        %(injuries_reported)s, %(witness_present)s, %(witness_first_name)s,
                        %(witness_last_name)s, %(police_report_filed)s, %(claim_status)s, %(folder_url)s
                    )
                    RETURNING claim_id
                """
                
                # Parse and convert date_of_loss to PostgreSQL format
                date_of_loss_value = claim_data.get('date_of_loss')
                if date_of_loss_value and isinstance(date_of_loss_value, str):
                    try:
                        # Try MM/DD/YYYY format first (common US format)
                        from datetime import datetime
                        parsed_date = datetime.strptime(date_of_loss_value, '%m/%d/%Y')
                        date_of_loss_value = parsed_date.strftime('%Y-%m-%d')
                    except ValueError:
                        try:
                            # Try YYYY-MM-DD format
                            parsed_date = datetime.strptime(date_of_loss_value, '%Y-%m-%d')
                            date_of_loss_value = parsed_date.strftime('%Y-%m-%d')
                        except ValueError:
                            # If still fails, set to None
                            print(f"[DB] Warning: Could not parse date '{date_of_loss_value}', setting to NULL")
                            date_of_loss_value = None
                
                # Prepare data with defaults - ensure claim_description is included
                prepared_data = {
                    'claim_id': claim_data.get('claim_id'),
                    'policy_id': claim_data.get('policy_id'),
                    'claim_type': claim_data.get('claim_type'),
                    'date_of_loss': date_of_loss_value,
                    'claim_description': claim_data.get('claim_description', ''),  # Ensure it's not None
                    'reporting_first_name': claim_data.get('reporting_first_name'),
                    'reporting_last_name': claim_data.get('reporting_last_name'),
                    'reporting_address': claim_data.get('reporting_address'),
                    'reporting_city': claim_data.get('reporting_city'),
                    'reporting_state': claim_data.get('reporting_state'),
                    'reporting_zip': claim_data.get('reporting_zip'),
                    'reporting_email': claim_data.get('reporting_email'),
                    'reporting_phone': claim_data.get('reporting_phone'),
                    'insured_same_as_reporter': claim_data.get('insured_same_as_reporter', False),
                    'insured_first_name': claim_data.get('insured_first_name'),
                    'insured_last_name': claim_data.get('insured_last_name'),
                    'insured_address': claim_data.get('insured_address'),
                    'insured_city': claim_data.get('insured_city'),
                    'insured_state': claim_data.get('insured_state'),
                    'insured_zip': claim_data.get('insured_zip'),
                    'insured_email': claim_data.get('insured_email'),
                    'insured_phone': claim_data.get('insured_phone'),
                    'injuries_reported': claim_data.get('injuries_reported', False),
                    'witness_present': claim_data.get('witness_present', False),
                    'witness_first_name': claim_data.get('witness_first_name'),
                    'witness_last_name': claim_data.get('witness_last_name'),
                    'police_report_filed': claim_data.get('police_report_filed', False),
                    'claim_status': claim_data.get('claim_status', 'Submitted'),
                    'folder_url': claim_data.get('folder_url', None)
                }
                
                cur.execute(query, prepared_data)
                result = cur.fetchone()
                return result[0] if result else None
                
    except Exception as e:
        print(f"❌ Error inserting claim: {e}")
        raise e


def get_all_claims():
    """Retrieve all claims with basic info"""
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT 
                        c.claim_id,
                        c.policy_id,
                        c.claim_type,
                        c.date_of_loss,
                        c.claim_description,
                        c.claim_status,
                        c.claim_submitted_at,
                        COALESCE(c.reporting_first_name || ' ' || c.reporting_last_name, '') as reporting_name,
                        COALESCE(c.insured_first_name || ' ' || c.insured_last_name, '') as insured_name,
                        p.sum_insured,
                        p.policy_type
                    FROM claims_db c
                    LEFT JOIN policy_db p ON c.policy_id = p.policy_id
                    ORDER BY c.claim_submitted_at DESC
                """
                
                cur.execute(query)
                claims = cur.fetchall()
                
                # Convert to list of dicts and handle dates
                result = []
                for claim in claims:
                    claim_dict = dict(claim)
                    if claim_dict.get('date_of_loss'):
                        claim_dict['date_of_loss'] = claim_dict['date_of_loss'].strftime('%Y-%m-%d')
                    if claim_dict.get('claim_submitted_at'):
                        claim_dict['claim_submitted_at'] = claim_dict['claim_submitted_at'].strftime('%Y-%m-%d %H:%M:%S')
                    result.append(claim_dict)
                
                return result
                
    except Exception as e:
        print(f"❌ Error fetching claims: {e}")
        raise e


def get_claim_by_id(claim_id):
    """Retrieve detailed claim information by claim_id"""
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT * FROM claims_db
                    WHERE claim_id = %s
                """
                
                cur.execute(query, (claim_id,))
                claim = cur.fetchone()
                
                if claim:
                    claim_dict = dict(claim)
                    # Convert date objects to strings
                    for key, value in claim_dict.items():
                        if isinstance(value, datetime):
                            claim_dict[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                        elif hasattr(value, 'strftime'):  # date object
                            claim_dict[key] = value.strftime('%Y-%m-%d')
                    return claim_dict
                return None
                
    except Exception as e:
        print(f"❌ Error fetching claim: {e}")
        raise e


# ============================================================================
# DATABASE OPERATIONS - POLICIES
# ============================================================================

def get_policy_by_id(policy_id):
    """Retrieve policy information by policy_id"""
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                query = """
                    SELECT * FROM policy_db
                    WHERE policy_id = %s
                """
                
                cur.execute(query, (policy_id,))
                policy = cur.fetchone()
                
                if policy:
                    policy_dict = dict(policy)
                    # Convert date objects to strings
                    for key, value in policy_dict.items():
                        if isinstance(value, datetime):
                            policy_dict[key] = value.strftime('%Y-%m-%d %H:%M:%S')
                        elif hasattr(value, 'strftime'):  # date object
                            policy_dict[key] = value.strftime('%Y-%m-%d')
                    return policy_dict
                return None
                
    except Exception as e:
        print(f"❌ Error fetching policy: {e}")
        raise e


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
    db_status = test_db_connection()
    return jsonify({
        'status': 'healthy' if db_status else 'degraded',
        'database': 'connected' if db_status else 'disconnected',
        'service': 'claims-fraud-api',
        'timestamp': datetime.now().isoformat(),
        'active_sessions': len(sessions)
    })


@app.route('/claims-api/pending', methods=['GET'])
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
            # Extract only required email fields
            email_fields_filtered = {}
            if session.email_fields:
                # ONLY include required fields: Policy Number, Subject, Document Name, Comments, Timestamp
                email_fields_filtered = {
                    "policy_number": session.email_fields.get("policy_number", "Not Found"),
                    "subject": session.email_fields.get("subject", "Not Found"),
                    "document_name": session.email_fields.get("document_name", "Not Found"),
                    "comments": session.email_fields.get("comments", ""),
                    "timestamp": session.email_fields.get("timestamp", "")
                }
                
                # ===================================================================
                # COMMENTED OUT: Other fields not sent to frontend
                # ===================================================================
                # "sender_email": session.email_fields.get("sender_email", "Not Found"),
                # "sender_name": session.email_fields.get("sender_name", "Not Found"),
                # "receiver_email": session.email_fields.get("receiver_email", "Not Found"),
                # "receiver_name": session.email_fields.get("receiver_name", "Not Found"),
                # "agency_name": session.email_fields.get("agency_name", "Not Found"),
                # "agency_id": session.email_fields.get("agency_id", "Not Found"),
                # "email_summary": session.email_fields.get("email_summary", "Not Found"),
                # "broker_email": session.email_fields.get("broker_email", "Not Found"),
                # "broker_name": session.email_fields.get("broker_name", "Not Found"),
                # "underwriter_email": session.email_fields.get("underwriter_email", "Not Found"),
                # "underwriter_name": session.email_fields.get("underwriter_name", "Not Found"),
                # "broker_agency_name": session.email_fields.get("broker_agency_name", "Not Found"),
                # "broker_agency_id": session.email_fields.get("broker_agency_id", "Not Found")
            
            pending_list.append({
                'filename': os.path.basename(session.pdf_path) if session.pdf_path else None,
                'claim_data': session.claim_data,
                'email_metadata': session.email_metadata,
                'email_fields': email_fields_filtered,  # Only required fields
                'detected_at': session.created_at.isoformat(),
                'has_email_metadata': session.email_metadata is not None,
                'has_email_fields': session.email_fields is not None,
                'has_confirmed_fields': session.confirmed_email_fields is not None,
                'fraud_analysis_complete': session.results is not None,  # Fraud detection status
                'risk_info': {
                    'risk_level': session.results.get('fraud_detection', {}).get('risk_level', 'Unknown'),
                    'flags_count': session.results.get('fraud_detection', {}).get('flags_count', 0)
                } if session.results else None,
                '_session_id': session_id
            })
    
    if len(pending_list) == 0:
        print(f"[/pending] DEBUG: No pending files, returning empty list")
        return jsonify({
            'success': True,
            'count': 0,
            'files': [],
            'message': 'No pending files found. Waiting for watcher to detect files.'
        }), 200
    
    # DEBUG: Print the response being sent
    print(f"\n[/pending] DEBUG: Sending response with {len(pending_list)} file(s)")
    for idx, item in enumerate(pending_list):
        print(f"[/pending] DEBUG: File {idx + 1}:")
        print(f"[/pending]   Filename: {item.get('filename')}")
        print(f"[/pending]   Email Fields: {json.dumps(item.get('email_fields', {}), indent=4)}")
        print(f"[/pending]   Session ID: {item.get('_session_id', 'N/A')[:8]}...")
    
    response_data = {
        'success': True,
        'count': len(pending_list),
        'files': pending_list
    }
    
    return jsonify(response_data), 200


@app.route('/claims-api/pending/latest', methods=['GET'])
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
            'success': True,
            'message': 'No pending files found',
            'filename': None
        }), 200
    
    return jsonify({
        'success': True,
        'filename': os.path.basename(latest_session.pdf_path) if latest_session.pdf_path else None,
        'claim_data': latest_session.claim_data,
        'email_metadata': latest_session.email_metadata,
        'detected_at': latest_session.created_at.isoformat(),
        'has_email_metadata': latest_session.email_metadata is not None
    }), 200


@app.route('/claims-api/email-fields', methods=['POST'])
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
            'message': 'Email fields confirmed successfully. Call POST /claims-api/process to continue.'
        }), 200
    
    except Exception as e:
        print(f"✗ Email fields confirmation error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/claims-api/process', methods=['POST'])
def process_claim():
    """
    Process claim and generate report with frontend-provided email fields.
    
    Frontend sends email fields directly (no need for /email-fields or /pending).
    
    Expects JSON:
    {
        "filename": "C1_test.pdf",  // Required to identify which file
        "email_fields": {           // Required: email fields from frontend
            "policy_number": "...",
            "subject": "...",
            "document_name": "...",
            "comments": "...",
            "timestamp": "..."
        },
        "form_pdf": "base64_encoded_pdf"  // Optional: form PDF from frontend
    }
    
    OR:
    {
        "session_id": "...",
        "email_fields": { ... },
        "form_pdf": "base64_encoded_pdf"
    }
    
    Returns:
    - success: Boolean
    - results: Fraud analysis results
    - claims_folder: Path to claims folder
    """
    cleanup_expired_sessions()
    
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        # Extract email fields and form PDF from request
        email_fields = data.get('email_fields', {})
        form_pdf_base64 = data.get('form_pdf')
        
        if not email_fields:
            return jsonify({'error': 'email_fields is required in request body'}), 400
        
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
            # Session doesn't exist yet - watcher hasn't finished processing
            # Store frontend data for when session is ready
            if filename:
                print(f"\n[PROCESS] No session found yet for {filename}")
                print(f"[PROCESS] Storing frontend data for later use...")
                
                pending_frontend_data[filename] = {
                    'email_fields': email_fields,
                    'form_pdf_base64': form_pdf_base64,
                    'received_at': datetime.now().isoformat(),
                    'processed': False
                }
                
                print(f"[PROCESS] ✓ Frontend data stored. Will process when watcher completes.")
                
                return jsonify({
                    'success': True,
                    'status': 'pending',
                    'message': 'Data received. Processing will complete when file detection finishes.',
                    'filename': filename
                }), 200
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
        
        # Store confirmed email fields from frontend
        session.confirmed_email_fields = email_fields
        policy_number = email_fields.get('policy_number')
        
        print(f"\n{'='*70}")
        print(f"PROCESSING REQUEST - Session: {session_id}")
        print(f"{'='*70}")
        print(f"Email fields received from frontend:")
        print(f"  Policy: {policy_number}")
        print(f"  Subject: {email_fields.get('subject', 'N/A')[:50]}...")
        print(f"  Document: {email_fields.get('document_name', 'N/A')}")
        
        # Handle form PDF upload if provided
        form_pdf_uploaded = False
        if form_pdf_base64:
            try:
                import base64
                
                # Decode base64 PDF
                pdf_bytes = base64.b64decode(form_pdf_base64)
                
                # Save form PDF locally first
                form_pdf_filename = f"form_{os.path.basename(session.pdf_path).replace('.pdf', '')}.pdf"
                form_pdf_path = os.path.join(CONFIG['OUTPUT_FOLDER'], form_pdf_filename)
                
                with open(form_pdf_path, 'wb') as f:
                    f.write(pdf_bytes)
                
                print(f"  ✓ Form PDF saved: {form_pdf_filename}")
                
                # Store path in session for later upload to claims folder
                session.form_pdf_path = form_pdf_path
                form_pdf_uploaded = True
                    
            except Exception as e:
                print(f"  ⚠ Failed to process form PDF: {str(e)}")
        
        # Import fraud detection system
        from app import FraudDetectionSystem
        from email_sender import load_email_metadata, get_recipient_email
        from onedrive_client_app import OneDriveClientApp
        
        # Initialize fraud system
        fraud_system = FraudDetectionSystem(use_ai=True)
        
        # Use stored fraud detection results (already analyzed by watcher)
        print(f"\n📋 Checking fraud analysis results...")
        
        if not session.results:
            # Watcher hasn't completed fraud analysis yet
            # Store frontend data in session for when analysis completes
            print(f"[PROCESS] Fraud analysis not ready yet. Storing frontend data...")
            session.confirmed_email_fields = email_fields
            
            return jsonify({
                'success': True,
                'status': 'pending_analysis',
                'message': 'Data received. Report will generate when fraud analysis completes.',
                'filename': filename
            }), 200
        
        print(f"   ✓ Fraud analysis complete")
        results = session.results
        print(f"   Risk Level: {results.get('fraud_detection', {}).get('risk_level', 'Unknown')}")
        print(f"   Flags: {results.get('fraud_detection', {}).get('flags_count', 0)}")
        
        # Use policy number from frontend (simple and direct)
        print(f"\n[POLICY] Using policy number from frontend: {policy_number}")
        
        # Update results with frontend policy number
        if policy_number and 'claim_data' in results:
            original_policy = results['claim_data'].get('policy_number', 'Unknown')
            if original_policy != policy_number:
                print(f"[POLICY] Policy number corrected: {original_policy} → {policy_number}")
            results['claim_data']['policy_number'] = policy_number
        
        # Store updated results
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
                    
                    # Store the folder URL for later use
                    folder_info = fraud_system.onedrive_client.get_subfolder_info(claims_folder_path)
                    if folder_info and folder_info.get('web_url'):
                        session.claims_folder_url = folder_info['web_url']
                        print(f"[OUTPUT] ✓ Folder URL stored: {session.claims_folder_url}")
                except Exception as e:
                    print(f"[OUTPUT] ⚠ Error getting file URL: {e}")
                    import traceback
                    traceback.print_exc()
            
            if session.output_pdf_path:
                print(f"[OUTPUT] ✓ Report PDF saved: {session.output_pdf_path}")
        
        session.processing_complete = True
        
        # Upload form PDF to claims folder if available - DISABLED
        # if session.form_pdf_path and fraud_system.onedrive_client and claims_folder_path:
        #     try:
        #         print(f"\n[FORM_PDF] Uploading form PDF to claims folder as 'form_response.pdf'...")
        #         # Upload with custom name 'form_response.pdf'
        #         upload_url = f"https://graph.microsoft.com/v1.0/users/{fraud_system.onedrive_client.user_email}/drive/root:/{claims_folder_path}/form_response.pdf:/content"
        #         
        #         with open(session.form_pdf_path, 'rb') as f:
        #             file_content = f.read()
        #         
        #         headers = fraud_system.onedrive_client._get_headers()
        #         headers["Content-Type"] = "application/octet-stream"
        #         
        #         import requests
        #         response = requests.put(upload_url, headers=headers, data=file_content)
        #         response.raise_for_status()
        #         
        #         result = response.json()
        #         if result.get('webUrl'):
        #             session.form_pdf_url = result.get('webUrl')
        #             print(f"[FORM_PDF] ✓ Form PDF uploaded to {claims_folder_path} as 'form_response.pdf'")
        #             print(f"[FORM_PDF]   URL: {session.form_pdf_url}")
        #         else:
        #             print(f"[FORM_PDF] ⚠ Form PDF uploaded but no URL returned")
        #     except Exception as e:
        #         print(f"[FORM_PDF] ⚠ Error uploading form PDF: {e}")
        
        # Move files on OneDrive
        if fraud_system.onedrive_client:
            onedrive = fraud_system.onedrive_client
            pdf_moved_successfully = False
            
            if claims_folder_path and session.onedrive_pdf_id:
                try:
                    # Store the file ID before moving
                    original_pdf_id = session.onedrive_pdf_id
                    
                    # Move the PDF to claims folder
                    onedrive.move_file_to_path(session.onedrive_pdf_id, claims_folder_path)
                    print(f"   ✓ Moved PDF to {claims_folder_path}")
                    pdf_moved_successfully = True
                    
                except Exception as e:
                    print(f"   ⚠ Failed to move PDF: {e}")
                    # If move failed, try to delete it from input_attachments to clean up
                    try:
                        onedrive.delete_file(session.onedrive_pdf_id)
                        print(f"   ✓ Deleted PDF from input_attachments folder")
                    except Exception as del_e:
                        print(f"   ⚠ Failed to delete PDF from input_attachments: {del_e}")
            
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
        
        # Helper function to convert date format from MM/DD/YYYY to YYYY-MM-DD
        def convert_date_format(date_str):
            """Convert MM/DD/YYYY to YYYY-MM-DD for PostgreSQL"""
            if not date_str:
                return None
            try:
                from datetime import datetime
                # Try parsing MM/DD/YYYY format
                date_obj = datetime.strptime(date_str, "%m/%d/%Y")
                return date_obj.strftime("%Y-%m-%d")
            except:
                try:
                    # Try parsing M/D/YYYY format (single digit month/day)
                    date_obj = datetime.strptime(date_str, "%m/%d/%Y")
                    return date_obj.strftime("%Y-%m-%d")
                except:
                    # Return as-is if parsing fails
                    return date_str
        
        # Save claim to database
        print(f"\n[DB] 💾 Saving claim to database...")
        
        # Get policy_number from confirmed fields (frontend) or results
        db_policy_id = policy_number
        if not db_policy_id:
            db_policy_id = results.get('claim_data', {}).get('policy_number', '')
        if not db_policy_id and session.confirmed_email_fields:
            db_policy_id = session.confirmed_email_fields.get('policy_number', '')
        
        # Handle "Same as Reporter" logic - copy insured data to reporting if reporting is empty
        insured_same_as_reporter = session.claim_data.get('insured_same_as_reporter', False)
        
        # Get reporting party fields (might be empty if insured_same_as_reporter is true)
        reporting_first_name = session.claim_data.get('first_name', '')
        reporting_last_name = session.claim_data.get('last_name', '')
        reporting_address = session.claim_data.get('address', '')
        reporting_city = session.claim_data.get('city', '')
        reporting_state = session.claim_data.get('state', '')
        reporting_zip = session.claim_data.get('zip_code', '')
        reporting_email = session.claim_data.get('email', '')
        reporting_phone = session.claim_data.get('phone_number', '')
        
        # If reporting fields are empty and insured_same_as_reporter is true, copy from insured fields
        if insured_same_as_reporter:
            if not reporting_first_name:
                reporting_first_name = session.claim_data.get('insured_first_name', '')
            if not reporting_last_name:
                reporting_last_name = session.claim_data.get('insured_last_name', '')
            if not reporting_address:
                reporting_address = session.claim_data.get('insured_address', '')
            if not reporting_city:
                reporting_city = session.claim_data.get('insured_city', '')
            if not reporting_state:
                reporting_state = session.claim_data.get('insured_state', '')
            if not reporting_zip:
                reporting_zip = session.claim_data.get('insured_zip', '')
            if not reporting_email:
                reporting_email = session.claim_data.get('insured_email', '')
            if not reporting_phone:
                reporting_phone = session.claim_data.get('insured_phone', '')
        
        claim_db_data = {
            'claim_id': session.claim_data.get('claim_number', ''),  # Use claim_number instead of claim_id
            'policy_id': db_policy_id,  # Use policy_number from frontend
            'claim_type': session.claim_data.get('claim_type', ''),
            'date_of_loss': convert_date_format(session.claim_data.get('date_of_loss')),
            'claim_description': session.claim_data.get('loss_description', ''),  # Use description from claim form
            'reporting_first_name': reporting_first_name,
            'reporting_last_name': reporting_last_name,
            'reporting_address': reporting_address,
            'reporting_city': reporting_city,
            'reporting_state': reporting_state,
            'reporting_zip': reporting_zip,
            'reporting_email': reporting_email,
            'reporting_phone': reporting_phone,
            'insured_same_as_reporter': insured_same_as_reporter,
            'insured_first_name': session.claim_data.get('insured_first_name', ''),
            'insured_last_name': session.claim_data.get('insured_last_name', ''),
            'insured_address': session.claim_data.get('insured_address', ''),
            'insured_city': session.claim_data.get('insured_city', ''),
            'insured_state': session.claim_data.get('insured_state', ''),
            'insured_zip': session.claim_data.get('insured_zip', ''),
            'insured_email': session.claim_data.get('insured_email', ''),
            'insured_phone': session.claim_data.get('insured_phone', ''),
            'injuries_reported': session.claim_data.get('injuries', '').lower() == 'yes' if session.claim_data.get('injuries') else False,
            'witness_present': session.claim_data.get('witness_present', False),
            'witness_first_name': session.claim_data.get('witness_first_name', ''),
            'witness_last_name': session.claim_data.get('witness_last_name', ''),
            'police_report_filed': session.claim_data.get('police_notified', False),
            'claim_status': 'Submitted',
            'folder_url': session.claims_folder_url if session.claims_folder_url else None
        }
        
        try:
            db_claim_id = insert_claim(claim_db_data)
            print(f"[DB] ✅ Claim saved to database: {db_claim_id}")
        except Exception as db_error:
            print(f"[DB] ⚠ Database save failed: {db_error}")

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


@app.route('/claims-api/output-pdf', methods=['GET'])
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
        
        # Return folder URL instead of PDF URL (opens subfolder in new tab)
        if session.claims_folder_url:
            return jsonify({
                'success': True,
                'pdf_url': session.claims_folder_url,  # Send folder URL instead of file URL
                'filename': os.path.basename(session.output_pdf_path) if session.output_pdf_path else None,
                'session_id': session_id,
                'created_at': session.created_at.isoformat(),
                'claims_folder': session.claims_folder_path
            }), 200
        elif session.output_pdf_url:
            # Fallback to PDF URL if folder URL not available
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
                # Return folder URL instead of PDF URL
                if session.claims_folder_url:
                    return jsonify({
                        'success': True,
                        'pdf_url': session.claims_folder_url,  # Send folder URL
                        'filename': os.path.basename(session.output_pdf_path) if session.output_pdf_path else None,
                        'session_id': sid,
                        'created_at': session.created_at.isoformat(),
                        'claims_folder': session.claims_folder_path
                    }), 200
                elif session.output_pdf_url:
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
        if session.claims_folder_url or session.output_pdf_url:
            if latest_time is None or session.created_at > latest_time:
                latest_session = session
                latest_time = session.created_at
    
    if not latest_session:
        return jsonify({
            'success': False,
            'message': 'No output PDF uploaded in any active session'
        }), 404
    
    # Return folder URL instead of PDF URL
    pdf_url = latest_session.claims_folder_url if latest_session.claims_folder_url else latest_session.output_pdf_url
    
    return jsonify({
        'success': True,
        'pdf_url': pdf_url,  # Send folder URL if available
        'filename': os.path.basename(latest_session.output_pdf_path) if latest_session.output_pdf_path else None,
        'session_id': latest_session.session_id,
        'created_at': latest_session.created_at.isoformat(),
        'claims_folder': latest_session.claims_folder_path
    }), 200


@app.route('/claims-api/sessions', methods=['GET'])
def list_sessions():
    """List all active sessions (for debugging)"""
    cleanup_expired_sessions()
    return jsonify({
        'count': len(sessions),
        'sessions': [session.to_dict() for session in sessions.values()]
    })


@app.route('/claims-api/sessions/<session_id>', methods=['DELETE'])
def delete_session(session_id: str):
    """Delete a specific session"""
    if session_id in sessions:
        sessions.pop(session_id)
        return jsonify({'success': True, 'message': f'Session {session_id} deleted'}), 200
    return jsonify({'success': False, 'message': 'Session not found'}), 404


# ============================================================================
# API ENDPOINTS - DATABASE QUERIES
# ============================================================================

@app.route('/api/claims', methods=['GET'])
def api_get_claims():
    """API endpoint to get all claims"""
    try:
        claims = get_all_claims()
        return jsonify({
            'success': True,
            'claims': claims,
            'count': len(claims)
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/claims/<claim_id>', methods=['GET'])
def api_get_claim_detail(claim_id):
    """API endpoint to get claim details with policy info"""
    try:
        claim = get_claim_by_id(claim_id)
        
        if not claim:
            return jsonify({
                'success': False,
                'error': 'Claim not found'
            }), 404
        
        # Get associated policy
        policy = None
        if claim.get('policy_id'):
            policy = get_policy_by_id(claim['policy_id'])
        
        return jsonify({
            'success': True,
            'claim': claim,
            'policy': policy
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/policies/<policy_id>', methods=['GET'])
def api_get_policy(policy_id):
    """API endpoint to get policy by ID"""
    try:
        policy = get_policy_by_id(policy_id)
        
        if not policy:
            return jsonify({
                'success': False,
                'error': 'Policy not found'
            }), 404
        
        return jsonify({
            'success': True,
            'policy': policy
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# ============================================================================
# SERVE HTML PAGES
# ============================================================================

@app.route('/claims')
def serve_claims_page():
    """Serve claims management page"""
    return send_from_directory('.', 'claims_mgmt.html')


@app.route('/claim/<claim_id>')
def serve_claim_detail_page(claim_id):
    """Serve claim detail page"""
    return send_from_directory('.', 'claim_detail.html')


@app.route('/logo-cropped.svg')
def serve_logo():
    """Serve logo file"""
    return send_from_directory('.', 'logo-cropped.svg', mimetype='image/svg+xml')


if __name__ == "__main__":
    # Test database connection on startup
    print("\n" + "="*70)
    print("TESTING DATABASE CONNECTION")
    print("="*70)
    if test_db_connection():
        print("✅ Database connection successful")
    else:
        print("❌ Database connection failed - check your .env configuration")
    print("="*70 + "\n")
    
    port = int(os.getenv("API_PORT", 5002))
    print(f"{'='*70}")
    print(f"CLAIMS FRAUD API SERVER")
    print(f"{'='*70}")
    print(f"Starting on port {port}...")
    print(f"Endpoints:")
    print(f"  GET  /health                   - Health check")
    print(f"  POST /claims-api/process       - Process claim (accepts email_fields)")
    print(f"  GET  /claims-api/pending       - List pending files (optional)")
    print(f"  GET  /claims-api/output-pdf    - Get output PDF URL")
    print(f"  GET  /api/claims               - Get all claims from DB")
    print(f"  GET  /claims                   - Serve claims page")
    print(f"{'='*70}\n")
    
    app.run(host='0.0.0.0', port=port, debug=False)
