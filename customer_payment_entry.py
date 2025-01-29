import requests
import xml.etree.ElementTree as ET
import re
import json
from datetime import datetime

def clean_unwanted_characters(xml_data):
    fixed_xml = re.sub(r'(\s)([a-zA-Z0-9_-]+)\s*=\s*([a-zA-Z0-9_-]+)', r'\1"\2"="\3"', xml_data)
    cleaned_data = re.sub(r'[^a-zA-Z0-9\s<>\-="/:.]', '', fixed_xml)
    return cleaned_data

def modify_rate_and_quantity(xml_data):
    xml_data = re.sub(r'(<RATE[^>]*>)([\d\.]+)(/no)(</RATE>)', r'\1\2\4', xml_data)
    xml_data = re.sub(r'(<ACTUALQTY[^>]*>\s*)([\d\.]+)\s*no(</ACTUALQTY>)', r'\1\2\3', xml_data)
    return xml_data

def preserve_numeric_format(xml_data):
    numeric_pattern = re.compile(r'\d+\.\d+(/[a-zA-Z]*)?')

    def replace_invalid_chars(match):
        return match.group(0)

    cleaned_data = numeric_pattern.sub(replace_invalid_chars, xml_data)
    return cleaned_data

def clean_name_field(name):
    return re.sub(r'^0+', '', name)

def clean_xml(xml_data):
    cleaned_xml = clean_unwanted_characters(xml_data)
    cleaned_xml = modify_rate_and_quantity(cleaned_xml)
    cleaned_xml = preserve_numeric_format(cleaned_xml)

    try:
        root = ET.fromstring(cleaned_xml)
        for name_element in root.findall(".//NAME"):
            if name_element.text:
                name_element.text = clean_name_field(name_element.text)

        return ET.tostring(root, encoding="unicode")
    except ET.ParseError as e:
        print("Error parsing XML:", e)
        return None
def get_purchase_invoice_id_by_ref_no(ref_no):
    url = f"ERP_URL/api/resource/Sales Invoice"
    
    headers = {
        "Authorization": "token API KEY:API SECRET"
    }
    
    params = {
        "filters": json.dumps([["custom_ref_no", "=", ref_no]]),
        "fields": json.dumps(["name"])  
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()  
        
        data = response.json()
        
        if data.get("data"):
            invoice_id = data["data"][0]["name"]
            return invoice_id
        else:
            return f"No Sales invoice found with ref_no: {ref_no}"
    
    except requests.exceptions.RequestException as e:
        return f"API request failed: {str(e)}"

def get_payment_vouchers_from_tally():
    url = "TALLY URL"
    xml_request = """
<ENVELOPE>
        <HEADER>
        <TALLYREQUEST>Export Data</TALLYREQUEST>
        </HEADER>
        <BODY>
        <EXPORTDATA>
        <REQUESTDESC>
        <STATICVARIABLES>
        <SVCURRENTCOMPANY>$etca_name</SVCURRENTCOMPANY>
        <SHOWCREATEDBY>YES</SHOWCREATEDBY>
        <SHOWPARTYNAME>YES</SHOWPARTYNAME>
        <VOUCHERTYPENAME>Receipt</VOUCHERTYPENAME>
        </STATICVARIABLES>
        <REPORTNAME>Voucher Register</REPORTNAME>
        </REQUESTDESC>
        </EXPORTDATA>
        </BODY>
        </ENVELOPE> 
"""
    headers = {"Content-Type": "application/xml"}

    try:
        response = requests.post(url, data=xml_request, headers=headers)
        if response.status_code == 200:
            raw_xml = response.text
            cleaned_xml = clean_xml(raw_xml)
            if cleaned_xml:
                root = ET.fromstring(cleaned_xml)
                payment_vouchers = []
                
                for voucher in root.findall(".//VOUCHER"):
                    party_name_tag = voucher.find(".//PARTYLEDGERNAME") 
                    
                    party_name = (
                        party_name_tag.text.strip()
                        if party_name_tag is not None and party_name_tag.text
                        else "Unknown Party"
                    )

                    voucher_number_tag = voucher.find(".//VOUCHERNUMBER")
                    voucher_no = voucher_number_tag.text.strip()

                    date_tag = voucher.find(".//DATE")
                    date = date_tag.text.strip()
                    if date:
                       date = datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")

                    pay_type = None
                    pay_type_element = voucher.find(".//BANKALLOCATIONS.LIST/TRANSACTIONTYPE")
                    if pay_type_element is not None:
                       pay_type = pay_type_element.text

                    amount_paid = None
                    amount_paid_element = voucher.find(".//BANKALLOCATIONS.LIST/AMOUNT")
                    if amount_paid_element is not None:
                        amount_paid = amount_paid_element.text

                    if amount_paid is not None:
                       amount_paid = str(amount_paid).replace("-", "")

                    print(f"\nProcessing Payment Voucher for Party: {party_name}")

                    payment_data = {
                        "vch_no":voucher_no,
                        "paid":amount_paid,
                        "party_name": party_name,
                        "date":date,
                        "pay_type":pay_type,
                        "reff":[]
                    }

                    reff_entries = voucher.findall(".//ALLLEDGERENTRIES.LIST")
                    if not reff_entries:
                       print("- Warning: NO ALLLEDGERENTRIES.LIST tag found")
                    else:
                       print(f"Found {len(reff_entries)} reff entries.")
                    for ref in reff_entries:
                        bill_allocations = ref.find(".//BILLALLOCATIONS.LIST")
                        if bill_allocations is None or not list(bill_allocations):  
                           print("- Warning: Empty or missing BILLALLOCATIONS.LIST, skipping...")
                           continue

                        reff_number = bill_allocations.find(".//NAME")
                        allocated_amount = bill_allocations.find(".//AMOUNT")

                        if reff_number is not None and reff_number.text and allocated_amount is not None and allocated_amount.text:
                           reff_no = reff_number.text.strip()
                           amount = allocated_amount.text.strip()
                           invoice_no = get_purchase_invoice_id_by_ref_no(reff_no)

                        payment_data["reff"].append(
                            {
                                "invoice_number":invoice_no,
                                "allocated_amount":amount
                            }
                        )
                    
                    if payment_data["reff"]:
                        payment_vouchers.append(payment_data)
                    else:
                        print(f" - No valid refferences found")

                return payment_vouchers
            else:
                print("Failed to clean and parse XML from Tally.")
        else:
            print(f"Failed to connect to Tally. Status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Tally: {e}")
    return []



def add_payment_entry_to_erpnext(payment_entry):
    erpnext_endpoint = "ERP_URL/api/resource/Payment Entry"
    headers = {
        "Authorization": "token 081cf178f1db3cc:9480a96f711ce0a",
        "Content-Type": "application/json",
    }

    data = {
        "__islocal": 1,
  "total_allocated_amount":payment_entry["paid"],
  "naming_series": "ACC-PAY-.YYYY.-",
  "custom_ref_no":f"RC{payment_entry["vch_no"]}",
  "target_exchange_rate": 1,
  "paid_to": "Cash - SSL",
  "base_paid_amount":float(payment_entry["paid"]),
  "paid_to_account_currency": "INR",
  "owner": "Administrator",
  "unallocated_amount": 0,
  "allocate_payment_amount": 1,
  "paid_amount":float(payment_entry["paid"]),
  "party_type": "Customer",
  "base_total_allocated_amount":float(payment_entry["paid"]),
  "party":payment_entry["party_name"],
  "base_received_amount":float(payment_entry["paid"]),
  "source_exchange_rate": 1,
  "doctype": "Payment Entry",
  "paid_from_account_balance": 0,
  "company": "Sahaj Solar Ltd",
  "deductions": [],
  "party_name":payment_entry["party_name"],
  "docstatus": 0,
  "paid_from_account_currency": "INR",
  "idx": 0,
  "difference_amount": 0,
  "received_amount":float(payment_entry["paid"]),
  "payment_type": "Receive",
  "posting_date":payment_entry["date"],
  "name": "New Payment Entry 1",
  "mode_of_payment":payment_entry["pay_type"],
  "__unsaved": 1,
        "references": [
    {
        "reference_doctype": "Sales Invoice",
        "reference_name": ref["invoice_number"],
        "allocated_amount": float(ref["allocated_amount"])
    }
    for ref in payment_entry.get("reff", [])
],
    }

    try:
       response = requests.post(erpnext_endpoint, headers=headers, json=data)
       response.raise_for_status()
       print(f"Successfully added Payment Entry for '{payment_entry['party_name']}' to ERPNext.")
    except requests.exceptions.HTTPError as err:
        print("HTTPError occurred:", err)  
    try:
        response_json = response.json()  
        if "_server_messages" in response_json:
            server_message = response_json["_server_messages"]
            print(f"Error Message: {server_message}")
        else:
            print("No server messages found in the response.")
    except ValueError:
        print("Response is not in JSON format.")
    except Exception as err:
       print(f"Error occurred while adding Payment Entry for '{payment_entry['party_name']}' to ERPNext: {err}")

def sync_payment_vouchers():
    print("Fetching Payment Vouchers from Tally Prime...")
    payment_vouchers = get_payment_vouchers_from_tally()

    if not payment_vouchers:
        print("No payment vouchers to sync.")
        return

    print(f"\nFound {len(payment_vouchers)} Payment Voucher(s) to sync.\n")

    for idx, payment_entry in enumerate(payment_vouchers, start=1):
        print(f"Syncing Payment Voucher {idx}...")
        add_payment_entry_to_erpnext(payment_entry)

if __name__ == "__main__":
    sync_payment_vouchers()




