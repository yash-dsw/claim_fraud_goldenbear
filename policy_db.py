"""
Policy database - stores pre-loaded ACORD policy information.
"""

import json
import os
from utils import extract_acord_fields


class PolicyDatabase:
    """Manages pre-loaded insurance policies."""
    
    def __init__(self):
        self.policies = {}
        self._load_policies()
    
    def _load_policies(self):
        """Load all ACORD policy files from the policies directory."""
        # Define the policy files to load
        policy_files = [
            "acord_jetwire.pdf",
            "acord_mudo.pdf",
            "acord_quickbites.pdf"
        ]
        
        print("Loading policy database...")
        for policy_file in policy_files:
            if os.path.exists(policy_file):
                try:
                    policy_data = extract_acord_fields(policy_file)
                    policy_number = policy_data.get("policy_number", "")
                    
                    if policy_number:
                        self.policies[policy_number] = {
                            "policy_data": policy_data,
                            "source_file": policy_file
                        }
                        print(f"  ✓ Loaded policy {policy_number} from {policy_file}")
                    else:
                        print(f"  ⚠ Warning: No policy number found in {policy_file}")
                except Exception as e:
                    print(f"  ✗ Error loading {policy_file}: {e}")
            else:
                print(f"  ⚠ Warning: Policy file not found: {policy_file}")
        
        print(f"✓ Policy database loaded with {len(self.policies)} policies\n")
    
    def get_policy(self, policy_number):
        """
        Retrieve a policy by its policy number.
        
        Args:
            policy_number: The policy number to look up
        
        Returns:
            Dictionary with policy_data and source_file, or None if not found
        """
        return self.policies.get(policy_number)
    
    def list_policies(self):
        """Return a list of all policy numbers in the database."""
        return list(self.policies.keys())
    
    def get_policy_count(self):
        """Return the total number of policies in the database."""
        return len(self.policies)
    
    def save_to_file(self, filename="policy_database.json"):
        """Save the policy database to a JSON file."""
        data = {
            policy_num: {
                "policy_data": info["policy_data"],
                "source_file": info["source_file"]
            }
            for policy_num, info in self.policies.items()
        }
        
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"✓ Policy database saved to {filename}")
    
    def load_from_file(self, filename="policy_database.json"):
        """Load the policy database from a JSON file."""
        if not os.path.exists(filename):
            return False
        
        with open(filename, 'r') as f:
            data = json.load(f)
        
        self.policies = data
        print(f"✓ Policy database loaded from {filename} ({len(self.policies)} policies)")
        return True
