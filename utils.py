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
    Returns a dictionary with claim information.
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
    
    # Loss Description
    if not claim_data["loss_description"]:
        desc_match = re.search(r'Describe\s+the\s+type\s+or\s+nature\s+of\s+claim:\s*\*?\s*([^\n]+(?:\n[^\n]+)*?)(?:Injuries?|Witness?|\n\n)', full_text, re.IGNORECASE)
        if desc_match:
            claim_data["loss_description"] = desc_match.group(1).strip()
    
    # Insured Name (from First/Last Name)
    first_name_match = re.search(r'(?:Insured:|Reporting Party:).*?First\s+Name:\s*\*?\s*([^\n]+)', full_text, re.IGNORECASE | re.DOTALL)
    last_name_match = re.search(r'(?:Insured:|Reporting Party:).*?Last\s+Name:\s*\*?\s*([^\n]+)', full_text, re.IGNORECASE | re.DOTALL)
    
    if first_name_match and last_name_match:
        claim_data["insured_name"] = f"{first_name_match.group(1).strip()} {last_name_match.group(1).strip()}"
        claim_data["reporting_party_name"] = claim_data["insured_name"]
    
    # Email
    email_match = re.search(r'Email:\s*\*?\s*([^\s\n]+@[^\s\n]+)', full_text, re.IGNORECASE)
    if email_match:
        claim_data["reporting_party_email"] = email_match.group(1).strip()
    
    # Phone
    phone_match = re.search(r'Phone:\s*\*?\s*(\([0-9]+\)\s*[0-9\-]+)', full_text, re.IGNORECASE)
    if phone_match:
        claim_data["reporting_party_phone"] = phone_match.group(1).strip()
    
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
