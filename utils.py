"""
Utility functions for extracting data from PDF files.
"""

import json
from datetime import datetime
from pypdf import PdfReader


def is_pdf_valid(pdf_path):
    """
    Check if a PDF file is valid and has extractable content.
    Used at intake level to filter out empty or corrupted PDFs.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Tuple of (is_valid: bool, reason: str)
        - is_valid: True if PDF is valid and has content, False otherwise
        - reason: Description of why PDF is invalid (empty string if valid)
    """
    try:
        reader = PdfReader(pdf_path)
        
        # Check if PDF has any pages
        if not reader.pages or len(reader.pages) == 0:
            return False, "PDF has no pages"
        
        # Check if we can extract any text or form fields
        has_form_fields = reader.get_fields() is not None and len(reader.get_fields()) > 0
        
        # Try to extract text from pages
        has_text = False
        for page in reader.pages:
            text = page.extract_text()
            if text and text.strip():
                has_text = True
                break
        
        if not has_form_fields and not has_text:
            return False, "PDF is empty (no form fields and no extractable text)"
        
        return True, ""
        
    except Exception as e:
        return False, f"PDF is corrupted or unreadable: {str(e)}"


def extract_acord_fields(pdf_path):
    """
    Extract fields from ACORD Commercial Insurance PDF form.
    Returns a dictionary with policy information.
    """
    reader = PdfReader(pdf_path)
    fields = reader.get_fields()
    
    if not fields:
        print("No form fields found in ACORD PDF")
        return {}
    
    extracted_data = {
        "named_insured": "",
        "policy_number": "",
        "effective_date": "",
        "producer_name": "",
        "insurer_name": "",
        "naics_code": "",
        "business_start_date": "",
        "years_in_business": "",
        "prior_carrier": "",
        "loss_history": [],
        "loss_history_count": 0,
        "loss_history_total_amount": "",
        "business_description": "",
        "street_address": "",
        "city": "",
        "state": "",
        "construction_type": "",
        "year_built": "",
        "total_area_sqft": "",
        "num_stories": "",
        "sprinklered_percent": "",
        "wiring_year": "",
        "roofing_year": "",
        "plumbing_year": "",
        "burglar_alarm_type": "",
        "fire_protection_class": "",
        "distance_to_fire_hydrant": "",
        "distance_to_fire_station": "",
    }
    
    # Named Insured
    if 'F[0].P1[0].NamedInsured_FullName_A[0]' in fields:
        extracted_data["named_insured"] = fields['F[0].P1[0].NamedInsured_FullName_A[0]'].get('/V', '')
    
    # Policy Number
    if 'F[0].P1[0].Policy_PolicyNumberIdentifier_A[0]' in fields:
        extracted_data["policy_number"] = fields['F[0].P1[0].Policy_PolicyNumberIdentifier_A[0]'].get('/V', '')
    
    # Producer Name
    if 'F[0].P1[0].Producer_FullName_A[0]' in fields:
        extracted_data["producer_name"] = fields['F[0].P1[0].Producer_FullName_A[0]'].get('/V', '')
    
    # Insurer Name
    if 'F[0].P1[0].Insurer_FullName_A[0]' in fields:
        extracted_data["insurer_name"] = fields['F[0].P1[0].Insurer_FullName_A[0]'].get('/V', '')
    
    # Effective Date
    if 'F[0].P1[0].Policy_EffectiveDate_A[0]' in fields:
        extracted_data["effective_date"] = fields['F[0].P1[0].Policy_EffectiveDate_A[0]'].get('/V', '')
    
    # NAICS Code
    if 'F[0].P1[0].NamedInsured_NAICSCode_A[0]' in fields:
        extracted_data["naics_code"] = fields['F[0].P1[0].NamedInsured_NAICSCode_A[0]'].get('/V', '')
    
    # Business Start Date and Years in Business
    if 'F[0].P2[0].NamedInsured_BusinessStartDate_A[0]' in fields:
        start_date = fields['F[0].P2[0].NamedInsured_BusinessStartDate_A[0]'].get('/V', '')
        extracted_data["business_start_date"] = start_date
        if start_date:
            try:
                date_obj = datetime.strptime(start_date, '%m/%d/%Y')
                extracted_data["years_in_business"] = str(datetime.now().year - date_obj.year)
            except:
                pass
    
    # Prior Carrier
    if 'F[0].P3[0].PriorCoverage_Property_InsurerFullName_A[0]' in fields:
        extracted_data["prior_carrier"] = fields['F[0].P3[0].PriorCoverage_Property_InsurerFullName_A[0]'].get('/V', '')
    
    # Loss History
    loss_history_entries = []
    for key in ['A', 'B', 'C', 'D', 'E', 'F']:
        loss_type_field = f'F[0].P4[0].LossHistory_OccurrenceDescription_{key}[0]'
        if loss_type_field in fields:
            loss_type = fields[loss_type_field].get('/V', '')
            if loss_type and loss_type.strip():
                loss_entry = {
                    "date_of_occurrence": fields.get(f'F[0].P4[0].LossHistory_OccurrenceDate_{key}[0]', {}).get('/V', ''),
                    "type": loss_type.strip(),
                    "date_of_claim": fields.get(f'F[0].P4[0].LossHistory_ClaimDate_{key}[0]', {}).get('/V', ''),
                    "amount_paid": fields.get(f'F[0].P4[0].LossHistory_PaidAmount_{key}[0]', {}).get('/V', ''),
                    "amount_reserved": fields.get(f'F[0].P4[0].LossHistory_ReservedAmount_{key}[0]', {}).get('/V', '')
                }
                loss_history_entries.append(loss_entry)
    
    extracted_data["loss_history"] = loss_history_entries
    extracted_data["loss_history_count"] = len(loss_history_entries)
    
    # Loss History Total Amount
    if 'F[0].P4[0].LossHistory_TotalAmount_A[0]' in fields:
        extracted_data["loss_history_total_amount"] = fields['F[0].P4[0].LossHistory_TotalAmount_A[0]'].get('/V', '')
    
    # Business Description
    if 'F[0].P2[0].BuildingOccupancy_OperationsDescription_A[0]' in fields:
        extracted_data["business_description"] = fields['F[0].P2[0].BuildingOccupancy_OperationsDescription_A[0]'].get('/V', '')
    
    # Address Information
    street_parts = []
    if 'F[0].P2[0].CommercialStructure_PhysicalAddress_LineOne_A[0]' in fields:
        line1 = fields['F[0].P2[0].CommercialStructure_PhysicalAddress_LineOne_A[0]'].get('/V', '')
        if line1:
            street_parts.append(line1)
    if 'F[0].P2[0].CommercialStructure_PhysicalAddress_LineTwo_A[0]' in fields:
        line2 = fields['F[0].P2[0].CommercialStructure_PhysicalAddress_LineTwo_A[0]'].get('/V', '')
        if line2:
            street_parts.append(line2)
    extracted_data["street_address"] = ", ".join(street_parts)
    
    if 'F[0].P2[0].CommercialStructure_PhysicalAddress_CityName_A[0]' in fields:
        extracted_data["city"] = fields['F[0].P2[0].CommercialStructure_PhysicalAddress_CityName_A[0]'].get('/V', '')
    
    if 'F[0].P2[0].CommercialStructure_PhysicalAddress_StateOrProvinceCode_A[0]' in fields:
        extracted_data["state"] = fields['F[0].P2[0].CommercialStructure_PhysicalAddress_StateOrProvinceCode_A[0]'].get('/V', '')
    
    # Construction and Building Details
    if 'F[0].P2[0].CommercialStructure_ConstructionCode_A[0]' in fields:
        extracted_data["construction_type"] = fields['F[0].P2[0].CommercialStructure_ConstructionCode_A[0]'].get('/V', '')
    
    if 'F[0].P2[0].CommercialStructure_BuiltYear_A[0]' in fields:
        extracted_data["year_built"] = fields['F[0].P2[0].CommercialStructure_BuiltYear_A[0]'].get('/V', '')
    
    if 'F[0].P2[0].BuildingOccupancy_OccupiedArea_A[0]' in fields:
        extracted_data["total_area_sqft"] = fields['F[0].P2[0].BuildingOccupancy_OccupiedArea_A[0]'].get('/V', '')
    
    if 'F[0].P2[0].CommercialStructure_NumberOfStories_A[0]' in fields:
        extracted_data["num_stories"] = fields['F[0].P2[0].CommercialStructure_NumberOfStories_A[0]'].get('/V', '')
    
    # Fire Protection and Safety Features
    if 'BuildingFireProtection_Alarm_SprinklerPercent_A' in fields:
        extracted_data["sprinklered_percent"] = fields['BuildingFireProtection_Alarm_SprinklerPercent_A'].get('/V', '')
    
    if 'BuildingImprovement_WiringYear_A' in fields:
        extracted_data["wiring_year"] = fields['BuildingImprovement_WiringYear_A'].get('/V', '')
    
    if 'BuildingImprovement_RoofingYear_A' in fields:
        extracted_data["roofing_year"] = fields['BuildingImprovement_RoofingYear_A'].get('/V', '')
    
    if 'BuildingImprovement_PlumbingYear_A' in fields:
        extracted_data["plumbing_year"] = fields['BuildingImprovement_PlumbingYear_A'].get('/V', '')
    
    # Search for burglar alarm type
    for field_name in fields.keys():
        if 'BurglarAlarm' in field_name or 'SecurityAlarm' in field_name:
            value = fields[field_name].get('/V', '')
            if value:
                extracted_data["burglar_alarm_type"] = value
                break
    
    if 'F[0].P2[0].CommercialStructure_ProtectionClass_A[0]' in fields:
        extracted_data["fire_protection_class"] = fields['F[0].P2[0].CommercialStructure_ProtectionClass_A[0]'].get('/V', '')
    
    if 'BuildingFireProtection_HydrantDistanceFeetCount_A' in fields:
        extracted_data["distance_to_fire_hydrant"] = fields['BuildingFireProtection_HydrantDistanceFeetCount_A'].get('/V', '')
    
    if 'BuildingFireProtection_FireStationDistanceMileCount_A' in fields:
        extracted_data["distance_to_fire_station"] = fields['BuildingFireProtection_FireStationDistanceMileCount_A'].get('/V', '')
    
    return extracted_data


def extract_claim_fields(pdf_path):
    """
    Extract fields from a Claim Form PDF.
    Returns a dictionary with claim information including detailed reporter and insured information.
    """
    import re
    
    reader = PdfReader(pdf_path)
    
    # Try to extract form fields first
    fields = reader.get_fields()
    
    claim_data = {
        "claim_number": "",
        "policy_number": "",
        "insured_name": "",
        "date_of_loss": "",
        "date_reported": "",
        "claim_type": "",
        "loss_description": "",
        "estimated_loss_amount": "",
        "cause_of_loss": "",
        "location_of_loss": "",
        "witnesses": "",
        "injuries": "",
        "reporting_party_name": "",
        "reporting_party_email": "",
        "reporting_party_phone": "",
        # Reporter detailed fields
        "first_name": "",
        "last_name": "",
        "address": "",
        "city": "",
        "state": "",
        "zip_code": "",
        "email": "",
        "phone_number": "",
        # Insured party fields
        "insured_same_as_reporter": False,
        "insured_first_name": "",
        "insured_last_name": "",
        "insured_address": "",
        "insured_city": "",
        "insured_state": "",
        "insured_zip": "",
        "insured_email": "",
        "insured_phone": "",
        # Witness fields
        "witness_present": False,
        "witness_first_name": "",
        "witness_last_name": "",
        # Police report
        "police_notified": False,
        "full_text": ""
    }
    
    # If form fields exist, extract them
    if fields:
        # Try common field names
        field_mappings = {
            "claim_number": ["ClaimNumber", "Claim_Number", "claim_number", "ClaimNo"],
            "policy_number": ["PolicyNumber", "Policy_Number", "policy_number", "PolicyNo"],
            "insured_name": ["InsuredName", "Insured_Name", "insured_name", "NamedInsured"],
            "date_of_loss": ["DateOfLoss", "Date_Of_Loss", "date_of_loss", "LossDate"],
            "date_reported": ["DateReported", "Date_Reported", "date_reported", "ReportDate"],
            "claim_type": ["ClaimType", "Claim_Type", "claim_type", "TypeOfLoss"],
            "loss_description": ["LossDescription", "Loss_Description", "loss_description", "Description"],
            "estimated_loss_amount": ["EstimatedLoss", "Estimated_Loss", "estimated_loss", "LossAmount"],
            "cause_of_loss": ["CauseOfLoss", "Cause_Of_Loss", "cause_of_loss", "Cause"],
            "location_of_loss": ["LocationOfLoss", "Location_Of_Loss", "location_of_loss", "Location"],
        }
        
        for key, possible_names in field_mappings.items():
            for field_name in fields.keys():
                if any(name in field_name for name in possible_names):
                    value = fields[field_name].get('/V', '')
                    if value:
                        claim_data[key] = value
                        break
    
    # Extract all text from the PDF for fallback analysis
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text() + "\n"
    
    claim_data["full_text"] = full_text.strip()
    
    # Parse text for structured information
    # Policy Number
    if not claim_data["policy_number"]:
        policy_match = re.search(r'Policy\s+Number:\s*\*?\s*([A-Z0-9]+)', full_text, re.IGNORECASE)
        if policy_match:
            claim_data["policy_number"] = policy_match.group(1)
    
    # Date of Loss
    if not claim_data["date_of_loss"]:
        date_match = re.search(r'Date\s+of\s+Loss:\s*\*?\s*(\d{1,2}/\d{1,2}/\d{4})', full_text, re.IGNORECASE)
        if date_match:
            claim_data["date_of_loss"] = date_match.group(1)
    
    # Claim Type
    if not claim_data["claim_type"]:
        type_match = re.search(r'Type\s+of\s+Insurance\s+Claim:\s*\*?\s*([^\n]+)', full_text, re.IGNORECASE)
        if type_match:
            claim_data["claim_type"] = type_match.group(1).strip()
    
    # Loss Description - extract the complete description text, can span multiple lines
    if not claim_data["loss_description"]:
        # Try to find the description between the label and 'Injuries?' - supports multi-line text
        desc_match = re.search(r'Describe\s+the\s+type\s+or\s+nature\s+of\s+claim:\s*\*?\s*(.+?)\s*Injuries?\s*\?', full_text, re.IGNORECASE | re.DOTALL)
        if desc_match:
            claim_data["loss_description"] = desc_match.group(1).strip()
        else:
            # Fallback: try to get text until double newline or next section
            desc_match = re.search(r'Describe\s+the\s+type\s+or\s+nature\s+of\s+claim:\s*\*?\s*(.+?)(?:\n\n|Injuries|Witness|Police)', full_text, re.IGNORECASE | re.DOTALL)
            if desc_match:
                claim_data["loss_description"] = desc_match.group(1).strip()
    
    # Insured Name (from First/Last Name)
    first_name_match = re.search(r'(?:Insured:|Reporting Party:).*?First\s+Name:\s*\*?\s*([^\n]+)', full_text, re.IGNORECASE | re.DOTALL)
    last_name_match = re.search(r'(?:Insured:|Reporting Party:).*?Last\s+Name:\s*\*?\s*([^\n]+)', full_text, re.IGNORECASE | re.DOTALL)
    
    if first_name_match and last_name_match:
        claim_data["first_name"] = first_name_match.group(1).strip()
        claim_data["last_name"] = last_name_match.group(1).strip()
        claim_data["insured_name"] = f"{claim_data['first_name']} {claim_data['last_name']}"
        claim_data["reporting_party_name"] = claim_data["insured_name"]
    
    # Extract detailed reporter information
    address_match = re.search(r'Address:\s*\*?\s*([^\n]+)', full_text, re.IGNORECASE)
    if address_match:
        claim_data["address"] = address_match.group(1).strip()
    
    city_match = re.search(r'City:\s*\*?\s*([^\n]+)', full_text, re.IGNORECASE)
    if city_match:
        claim_data["city"] = city_match.group(1).strip()
    
    state_match = re.search(r'State:\s*\*?\s*([^\n]+)', full_text, re.IGNORECASE)
    if state_match:
        claim_data["state"] = state_match.group(1).strip()
    
    zip_match = re.search(r'(?:Zip|Postal\s+Code):\s*\*?\s*([0-9\-]+)', full_text, re.IGNORECASE)
    if zip_match:
        claim_data["zip_code"] = zip_match.group(1).strip()
    
    # Email
    email_match = re.search(r'Email:\s*\*?\s*([^\s\n]+@[^\s\n]+)', full_text, re.IGNORECASE)
    if email_match:
        claim_data["email"] = email_match.group(1).strip()
        claim_data["reporting_party_email"] = claim_data["email"]
    
    # Phone
    phone_match = re.search(r'Phone:\s*\*?\s*(\([0-9]+\)\s*[0-9\-]+|[0-9\-]+)', full_text, re.IGNORECASE)
    if phone_match:
        claim_data["phone_number"] = phone_match.group(1).strip()
        claim_data["reporting_party_phone"] = claim_data["phone_number"]
    
    # Check if insured is same as reporter
    same_as_reporter_match = re.search(r'Is\s+the\s+Insured\s+the\s+same\s+as\s+the\s+Reporting\s+Party\?\s*\*?\s*(Yes|No)', full_text, re.IGNORECASE)
    if same_as_reporter_match:
        claim_data["insured_same_as_reporter"] = same_as_reporter_match.group(1).strip().lower() == 'yes'
    
    # Extract insured party information if different from reporter
    insured_info_found = False
    if not claim_data["insured_same_as_reporter"]:
        # Look for insured section
        insured_section = re.search(r'Insured\s+Party\s+Information.*?(?:Witness|Police|Incident|$)', full_text, re.IGNORECASE | re.DOTALL)
        if insured_section:
            insured_text = insured_section.group(0)
            
            insured_first_match = re.search(r'First\s+Name:\s*\*?\s*([^\n]+)', insured_text, re.IGNORECASE)
            if insured_first_match:
                claim_data["insured_first_name"] = insured_first_match.group(1).strip()
                insured_info_found = True
            
            insured_last_match = re.search(r'Last\s+Name:\s*\*?\s*([^\n]+)', insured_text, re.IGNORECASE)
            if insured_last_match:
                claim_data["insured_last_name"] = insured_last_match.group(1).strip()
                insured_info_found = True
            
            insured_address_match = re.search(r'Address:\s*\*?\s*([^\n]+)', insured_text, re.IGNORECASE)
            if insured_address_match:
                claim_data["insured_address"] = insured_address_match.group(1).strip()
                insured_info_found = True
            
            insured_city_match = re.search(r'City:\s*\*?\s*([^\n]+)', insured_text, re.IGNORECASE)
            if insured_city_match:
                claim_data["insured_city"] = insured_city_match.group(1).strip()
                insured_info_found = True
            
            insured_state_match = re.search(r'State:\s*\*?\s*([^\n]+)', insured_text, re.IGNORECASE)
            if insured_state_match:
                claim_data["insured_state"] = insured_state_match.group(1).strip()
                insured_info_found = True
            
            insured_zip_match = re.search(r'(?:Zip|Postal\s+Code):\s*\*?\s*([0-9\-]+)', insured_text, re.IGNORECASE)
            if insured_zip_match:
                claim_data["insured_zip"] = insured_zip_match.group(1).strip()
                insured_info_found = True
            
            insured_email_match = re.search(r'Email:\s*\*?\s*([^\s\n]+@[^\s\n]+)', insured_text, re.IGNORECASE)
            if insured_email_match:
                claim_data["insured_email"] = insured_email_match.group(1).strip()
                insured_info_found = True
            
            insured_phone_match = re.search(r'Phone:\s*\*?\s*(\([0-9]+\)\s*[0-9\-]+|[0-9\-]+)', insured_text, re.IGNORECASE)
            if insured_phone_match:
                claim_data["insured_phone"] = insured_phone_match.group(1).strip()
                insured_info_found = True
    
    # If insured is same as reporter OR no separate insured info found, copy reporter information
    if claim_data["insured_same_as_reporter"] or not insured_info_found:
        claim_data["insured_first_name"] = claim_data["first_name"]
        claim_data["insured_last_name"] = claim_data["last_name"]
        claim_data["insured_address"] = claim_data["address"]
        claim_data["insured_city"] = claim_data["city"]
        claim_data["insured_state"] = claim_data["state"]
        claim_data["insured_zip"] = claim_data["zip_code"]
        claim_data["insured_email"] = claim_data["email"]
        claim_data["insured_phone"] = claim_data["phone_number"]
        # If we're copying, mark it as same
        if not insured_info_found:
            claim_data["insured_same_as_reporter"] = True
    
    # Witness information
    witness_match = re.search(r'(?:Was\s+there\s+a\s+)?Witness\?\s*\*?\s*(Yes|No)', full_text, re.IGNORECASE)
    if witness_match:
        claim_data["witness_present"] = witness_match.group(1).strip().lower() == 'yes'
        claim_data["witnesses"] = witness_match.group(1).strip()
    
    if claim_data["witness_present"]:
        witness_first_match = re.search(r'Witness.*?First\s+Name:\s*\*?\s*([^\n]+)', full_text, re.IGNORECASE | re.DOTALL)
        if witness_first_match:
            claim_data["witness_first_name"] = witness_first_match.group(1).strip()
        
        witness_last_match = re.search(r'Witness.*?Last\s+Name:\s*\*?\s*([^\n]+)', full_text, re.IGNORECASE | re.DOTALL)
        if witness_last_match:
            claim_data["witness_last_name"] = witness_last_match.group(1).strip()
    
    # Police notification
    police_match = re.search(r'(?:Was\s+)?Police\s+(?:Notified|Report\s+Filed)\?\s*\*?\s*(Yes|No)', full_text, re.IGNORECASE)
    if police_match:
        claim_data["police_notified"] = police_match.group(1).strip().lower() == 'yes'
    
    # Injuries
    injuries_match = re.search(r'Injuries\?\s*\*?\s*(Yes|No)', full_text, re.IGNORECASE)
    if injuries_match:
        claim_data["injuries"] = injuries_match.group(1).strip()
    
    # Witness
    witness_match = re.search(r'Witness\?\s*\*?\s*(Yes|No)', full_text, re.IGNORECASE)
    if witness_match:
        claim_data["witnesses"] = witness_match.group(1).strip()
    
    return claim_data


def calculate_days_between(date1_str, date2_str):
    """
    Calculate the number of days between two dates.
    Dates should be in MM/DD/YYYY format.
    Returns the number of days or None if dates are invalid.
    """
    try:
        date1 = datetime.strptime(date1_str, '%m/%d/%Y')
        date2 = datetime.strptime(date2_str, '%m/%d/%Y')
        return abs((date2 - date1).days)
    except:
        return None


def parse_amount(amount_str):
    """
    Parse a currency amount string to float.
    Handles formats like $1,234.56 or 1234.56
    """
    if not amount_str:
        return 0.0
    try:
        # Remove currency symbols and commas
        cleaned = amount_str.replace('$', '').replace(',', '').strip()
        return float(cleaned)
    except:
        return 0.0


def generate_unique_claim_id():
    """
    Generate a unique 7-digit random claim ID.
    Returns a string representation of a random number between 1000000 and 9999999.
    
    Returns:
        str: A 7-digit claim ID
    """
    import random
    claim_id = random.randint(1000000, 9999999)
    return str(claim_id)
