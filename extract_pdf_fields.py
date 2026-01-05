import json
import pandas as pd
from pypdf import PdfReader

def extract_pdf_form_fields(pdf_path):
    """Extract fields from ACORD Commercial Insurance PDF form."""
    reader = PdfReader(pdf_path)
    fields = reader.get_fields()
    
    if not fields:
        print("No form fields found in PDF")
        return {}
    
    # Initialize output dictionary
    extracted_data = {
        "Named Insured": "",
        "Mailing Address": "",
        "City": "",
        "State": "",
        "NAICS Code": "",
        "Legal Entity Type": "",
        "FEIN": "",
        "Years in Business": "",
        "Prior Carrier": "",
        "Loss History - Count": "",
        "Loss History - Total Amount": "",
        "Loss History": [],
        "Business Description": "",
        "Premises #": "",
        "Bldg #": "",
        "Street Address": "",
        "Subject of Insurance": "",
        "Coverage Limit": "",
        "Construction Type": "",
        "Year Built": "",
        "Total Area (Sq Ft)": "",
        "# of Stories": "",
        "Sprinklered %": "",
        "Building Improvements - Wiring": "",
        "Building Improvements - Roofing": "",
        "Building Improvements - Plumbing": "",
        "Burglar Alarm Type": "",
        "Fire Protection Class": "",
        "Distance to Fire Hydrant": "",
        "Distance to Fire Station": ""
    }
    
    # Extract specific fields based on actual PDF structure
    if fields:
        # Named Insured
        if 'F[0].P1[0].NamedInsured_FullName_A[0]' in fields:
            extracted_data["Named Insured"] = fields['F[0].P1[0].NamedInsured_FullName_A[0]'].get('/V', '')
        
        # Mailing Address (from Premises Information - street only)
        addr_parts = []
        if 'F[0].P2[0].CommercialStructure_PhysicalAddress_LineOne_A[0]' in fields:
            line1 = fields['F[0].P2[0].CommercialStructure_PhysicalAddress_LineOne_A[0]'].get('/V', '')
            if line1:
                addr_parts.append(line1)
        if 'F[0].P2[0].CommercialStructure_PhysicalAddress_LineTwo_A[0]' in fields:
            line2 = fields['F[0].P2[0].CommercialStructure_PhysicalAddress_LineTwo_A[0]'].get('/V', '')
            if line2:
                addr_parts.append(line2)
        if 'CommercialStructure_PhysicalAddress_LineOne_A' in fields:
            line1 = fields['CommercialStructure_PhysicalAddress_LineOne_A'].get('/V', '')
            if line1 and line1 not in addr_parts:
                addr_parts.append(line1)
        extracted_data["Mailing Address"] = ", ".join(addr_parts)
        
        # City
        if 'F[0].P2[0].CommercialStructure_PhysicalAddress_CityName_A[0]' in fields:
            extracted_data["City"] = fields['F[0].P2[0].CommercialStructure_PhysicalAddress_CityName_A[0]'].get('/V', '')
        
        # State
        if 'F[0].P2[0].CommercialStructure_PhysicalAddress_StateOrProvinceCode_A[0]' in fields:
            extracted_data["State"] = fields['F[0].P2[0].CommercialStructure_PhysicalAddress_StateOrProvinceCode_A[0]'].get('/V', '')
        
        # NAICS Code
        if 'F[0].P1[0].NamedInsured_NAICSCode_A[0]' in fields:
            extracted_data["NAICS Code"] = fields['F[0].P1[0].NamedInsured_NAICSCode_A[0]'].get('/V', '')
        
        # Legal Entity Type
        entity_types = []
        entity_fields = {
            'Corporation': 'F[0].P1[0].NamedInsured_LegalEntity_CorporationIndicator_A[0]',
            'Individual': 'F[0].P1[0].NamedInsured_LegalEntity_IndividualIndicator_A[0]',
            'Joint Venture': 'F[0].P1[0].NamedInsured_LegalEntity_JointVentureIndicator_A[0]',
            'LLC': 'F[0].P1[0].NamedInsured_LegalEntity_LimitedLiabilityCorporationIndicator_A[0]',
            'Partnership': 'F[0].P1[0].NamedInsured_LegalEntity_PartnershipIndicator_A[0]',
            'Trust': 'F[0].P1[0].NamedInsured_LegalEntity_TrustIndicator_A[0]'
        }
        for name, field in entity_fields.items():
            if field in fields and fields[field].get('/V', '') and fields[field].get('/V', '') != ' ':
                entity_types.append(name)
        extracted_data["Legal Entity Type"] = ", ".join(entity_types)
        
        # FEIN
        if 'F[0].P1[0].NamedInsured_TaxIdentifier_A[0]' in fields:
            extracted_data["FEIN"] = fields['F[0].P1[0].NamedInsured_TaxIdentifier_A[0]'].get('/V', '')
        
        # Years in Business
        if 'F[0].P2[0].NamedInsured_BusinessStartDate_A[0]' in fields:
            start_date = fields['F[0].P2[0].NamedInsured_BusinessStartDate_A[0]'].get('/V', '')
            if start_date:
                try:
                    from datetime import datetime
                    date_obj = datetime.strptime(start_date, '%m/%d/%Y')
                    extracted_data["Years in Business"] = str(datetime.now().year - date_obj.year)
                except:
                    extracted_data["Years in Business"] = start_date
        
        # Prior Carrier
        if 'F[0].P3[0].PriorCoverage_Property_InsurerFullName_A[0]' in fields:
            extracted_data["Prior Carrier"] = fields['F[0].P3[0].PriorCoverage_Property_InsurerFullName_A[0]'].get('/V', '')
        
        # Loss History - Extract as array of objects (one for each row)
        loss_history_entries = []
        for key in ['A', 'B', 'C', 'D', 'E', 'F']:
            loss_type_field = f'F[0].P4[0].LossHistory_OccurrenceDescription_{key}[0]'
            
            if loss_type_field in fields:
                loss_type = fields[loss_type_field].get('/V', '')
                
                if loss_type and loss_type.strip():
                    loss_entry = {
                        "Date of Occurrence": fields.get(f'F[0].P4[0].LossHistory_OccurrenceDate_{key}[0]', {}).get('/V', ''),
                        "Type": loss_type.strip(),
                        "Date of Claim": fields.get(f'F[0].P4[0].LossHistory_ClaimDate_{key}[0]', {}).get('/V', ''),
                        "Amount Paid": fields.get(f'F[0].P4[0].LossHistory_PaidAmount_{key}[0]', {}).get('/V', ''),
                        "Amount Reserved": fields.get(f'F[0].P4[0].LossHistory_ReservedAmount_{key}[0]', {}).get('/V', '')
                    }
                    loss_history_entries.append(loss_entry)
        
        extracted_data["Loss History - Count"] = str(len(loss_history_entries))
        extracted_data["Loss History"] = loss_history_entries
        
        # Loss History - Total Amount
        if 'F[0].P4[0].LossHistory_TotalAmount_A[0]' in fields:
            extracted_data["Loss History - Total Amount"] = fields['F[0].P4[0].LossHistory_TotalAmount_A[0]'].get('/V', '')
        
        # Business Description
        if 'F[0].P2[0].BuildingOccupancy_OperationsDescription_A[0]' in fields:
            extracted_data["Business Description"] = fields['F[0].P2[0].BuildingOccupancy_OperationsDescription_A[0]'].get('/V', '')
        if not extracted_data["Business Description"] and 'F[0].P2[0].BusinessInformation_FullTimeEmployeeCount_A[0]' in fields:
            extracted_data["Business Description"] = fields['F[0].P2[0].BusinessInformation_FullTimeEmployeeCount_A[0]'].get('/V', '')
        
        # Premises # and Bldg # (separate fields)
        if 'CommercialStructure_Location_ProducerIdentifier_A' in fields:
            extracted_data["Premises #"] = fields['CommercialStructure_Location_ProducerIdentifier_A'].get('/V', '')
        
        if 'CommercialStructure_Building_ProducerIdentifier_A' in fields:
            extracted_data["Bldg #"] = fields['CommercialStructure_Building_ProducerIdentifier_A'].get('/V', '')
        
        # Street Address
        street_parts = []
        for f in ['F[0].P2[0].CommercialStructure_PhysicalAddress_LineOne_A[0]', 'F[0].P2[0].CommercialStructure_PhysicalAddress_LineTwo_A[0]']:
            if f in fields and fields[f].get('/V', ''):
                street_parts.append(fields[f].get('/V', ''))
        extracted_data["Street Address"] = ", ".join(street_parts)
        
        # Subject of Insurance - search for relevant fields
        for field_name in fields.keys():
            if any(x in field_name for x in ['SubjectOfInsurance', 'CoverageDescription', 'InsuredProperty']):
                value = fields[field_name].get('/V', '')
                if value and value.strip():
                    extracted_data["Subject of Insurance"] = value
                    break
        
        # Coverage Limit - search for relevant fields
        if 'CommercialProperty_Spoilage_LimitAmount_A' in fields:
            extracted_data["Coverage Limit"] = fields['CommercialProperty_Spoilage_LimitAmount_A'].get('/V', '')
        if not extracted_data["Coverage Limit"]:
            for field_name in fields.keys():
                if 'Limit' in field_name and 'Amount' in field_name:
                    value = fields[field_name].get('/V', '')
                    if value and value.strip():
                        extracted_data["Coverage Limit"] = value
                        break
        
        # Construction Type
        if 'Construction_ConstructionCode_A' in fields:
            extracted_data["Construction Type"] = fields['Construction_ConstructionCode_A'].get('/V', '')
        elif 'F[0].P2[0].CommercialStructure_ConstructionCode_A[0]' in fields:
            extracted_data["Construction Type"] = fields['F[0].P2[0].CommercialStructure_ConstructionCode_A[0]'].get('/V', '')
        
        # Year Built
        if 'CommercialStructure_BuiltYear_A' in fields:
            extracted_data["Year Built"] = fields['CommercialStructure_BuiltYear_A'].get('/V', '')
        elif 'F[0].P2[0].CommercialStructure_BuiltYear_A[0]' in fields:
            extracted_data["Year Built"] = fields['F[0].P2[0].CommercialStructure_BuiltYear_A[0]'].get('/V', '')
        
        # Total Area
        if 'Construction_BuildingArea_A' in fields:
            extracted_data["Total Area (Sq Ft)"] = fields['Construction_BuildingArea_A'].get('/V', '')
        elif 'F[0].P2[0].BuildingOccupancy_OccupiedArea_A[0]' in fields:
            extracted_data["Total Area (Sq Ft)"] = fields['F[0].P2[0].BuildingOccupancy_OccupiedArea_A[0]'].get('/V', '')
        
        # Number of Stories
        if 'Construction_StoreyCount_A' in fields:
            extracted_data["# of Stories"] = fields['Construction_StoreyCount_A'].get('/V', '')
        elif 'F[0].P2[0].CommercialStructure_NumberOfStories_A[0]' in fields:
            extracted_data["# of Stories"] = fields['F[0].P2[0].CommercialStructure_NumberOfStories_A[0]'].get('/V', '')
        
        # Sprinklered %
        if 'BuildingFireProtection_Alarm_SprinklerPercent_A' in fields:
            extracted_data["Sprinklered %"] = fields['BuildingFireProtection_Alarm_SprinklerPercent_A'].get('/V', '')
        
        # Building Improvements
        if 'BuildingImprovement_WiringYear_A' in fields:
            extracted_data["Building Improvements - Wiring"] = fields['BuildingImprovement_WiringYear_A'].get('/V', '')
        
        if 'BuildingImprovement_RoofingYear_A' in fields:
            extracted_data["Building Improvements - Roofing"] = fields['BuildingImprovement_RoofingYear_A'].get('/V', '')
        
        if 'BuildingImprovement_PlumbingYear_A' in fields:
            extracted_data["Building Improvements - Plumbing"] = fields['BuildingImprovement_PlumbingYear_A'].get('/V', '')
        
        # Burglar Alarm Type
        if 'Alarm_Burglar_AlarmDescription_A' in fields:
            extracted_data["Burglar Alarm Type"] = fields['Alarm_Burglar_AlarmDescription_A'].get('/V', '')
        if not extracted_data["Burglar Alarm Type"]:
            for field_name in fields.keys():
                if 'BurglarAlarm' in field_name or 'SecurityAlarm' in field_name:
                    value = fields[field_name].get('/V', '')
                    if value:
                        extracted_data["Burglar Alarm Type"] = value
                        break
        
        # Fire Protection Class
        if 'BuildingFireProtection_Alarm_ProtectionDescription_A' in fields:
            extracted_data["Fire Protection Class"] = fields['BuildingFireProtection_Alarm_ProtectionDescription_A'].get('/V', '')
        elif 'F[0].P2[0].CommercialStructure_ProtectionClass_A[0]' in fields:
            extracted_data["Fire Protection Class"] = fields['F[0].P2[0].CommercialStructure_ProtectionClass_A[0]'].get('/V', '')
        
        # Distance to Fire Hydrant
        if 'BuildingFireProtection_HydrantDistanceFeetCount_A' in fields:
            extracted_data["Distance to Fire Hydrant"] = fields['BuildingFireProtection_HydrantDistanceFeetCount_A'].get('/V', '')
        
        # Distance to Fire Station
        if 'BuildingFireProtection_FireStationDistanceMileCount_A' in fields:
            extracted_data["Distance to Fire Station"] = fields['BuildingFireProtection_FireStationDistanceMileCount_A'].get('/V', '')
    
    return extracted_data

def main():
    pdf_path = "acord_full.pdf"
    output_json_path = "extracted_data.json"
    output_csv_path = "extracted_data.csv"
    
    try:
        print(f"Extracting data from: {pdf_path}")
        extracted_data = extract_pdf_form_fields(pdf_path)
        
        # Save to JSON file
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, indent=4, ensure_ascii=False)
        
        print(f"\n✓ Extraction complete!")
        print(f"✓ JSON saved to: {output_json_path}")
        
        # Convert to pandas DataFrame
        # For nested Loss History array, we'll keep it as JSON string in the DataFrame
        df_data = extracted_data.copy()
        df_data['Loss History'] = json.dumps(df_data['Loss History'])
        
        # Create DataFrame with single row
        df = pd.DataFrame([df_data])
        
        # Save to CSV
        df.to_csv(output_csv_path, index=False, encoding='utf-8')
        print(f"✓ CSV saved to: {output_csv_path}")
        
        print(f"\nExtracted {len([v for v in extracted_data.values() if v])} out of {len(extracted_data)} fields")
        
        # Display DataFrame info
        print(f"\nDataFrame shape: {df.shape}")
        print(f"Columns: {len(df.columns)}")
        
    except FileNotFoundError:
        print(f"Error: PDF file '{pdf_path}' not found!")
    except Exception as e:
        print(f"Error: {str(e)}")

if __name__ == "__main__":
    main()
