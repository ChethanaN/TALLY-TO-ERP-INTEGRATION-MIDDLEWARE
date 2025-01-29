import requests
import xml.etree.ElementTree as ET
import re
from datetime import datetime

def clean_unwanted_characters(xml_data):
    fixed_xml = re.sub(r'(\s)([a-zA-Z0-9_-]+)\s*=\s*([a-zA-Z0-9_-]+)', r'\1"\2"="\3"', xml_data)
    cleaned_data = re.sub(r'[^a-zA-Z0-9\s<>\-="/:.]', '', fixed_xml)
    return cleaned_data


def preserve_numeric_format(xml_data):
    numeric_pattern = re.compile(r'\d+\.\d+(/[a-zA-Z]*)?')
    def replace_invalid_chars(match):
        return match.group(0) 
    cleaned_data = numeric_pattern.sub(replace_invalid_chars, xml_data)
    return cleaned_data
    
def modify_rate_and_quantity(xml_data):
    xml_data = re.sub(r'(<RATE[^>]*>)([\d\.]+)(/no)(</RATE>)', r'\1\2\4', xml_data)
    xml_data = re.sub(r'(<ACTUALQTY[^>]*>\s*)([\d\.]+)\s*no(</ACTUALQTY>)', r'\1\2\3', xml_data)
    return xml_data

def normalize_and_clean_xml(xml_data):
    cleaned_xml = clean_unwanted_characters(xml_data)
    cleaned_xml = preserve_numeric_format(cleaned_xml)
    cleaned_xml = modify_rate_and_quantity(cleaned_xml)

    try:
        root = ET.fromstring(cleaned_xml)
        cleaned_string = ET.tostring(root, encoding="unicode", method="xml").replace("\n", "").replace("\r", "").strip()
        return cleaned_string
    except ET.ParseError as e:
        print("Error parsing XML:", e)
        return None

def get_purchase_invoices_from_tally():
    url = "TALLY_URL"
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
        <VOUCHERTYPENAME>Purchase</VOUCHERTYPENAME>
        </STATICVARIABLES>
        <REPORTNAME>Voucher Register</REPORTNAME>
        </REQUESTDESC>
        </EXPORTDATA>
        </BODY>
        </ENVELOPE>
    """
    headers = {"Content-Type": "text/xml"}
    try:
        response = requests.post(url, data=xml_request, headers=headers, timeout=20)
        if response.status_code == 200:
            raw_xml = response.text
            cleaned_xml = normalize_and_clean_xml(raw_xml)

            if cleaned_xml:
                root = ET.fromstring(cleaned_xml)
                purchase_invoices = []

                for voucher in root.findall(".//VOUCHER"):
                    supplier_tag = voucher.find(".//PARTYLEDGERNAME")
                    supplier_name = (
                        supplier_tag.text.strip()
                        if supplier_tag is not None and supplier_tag.text
                        else "Unknown Supplier"
                    )
                    voucher_number_tag = voucher.find(".//VOUCHERNUMBER")
                    voucher_no = voucher_number_tag.text.strip()
                    print(f"\nProcessing Purchase Invoice for Supplier: {supplier_name}")

                    date_tag = voucher.find(".//DATE")
                    date = date_tag.text.strip()
                    if date:
                       date = datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")


                    invoice_data = {
                        "custom_ref_no": voucher_no,
                        "supplier": supplier_name,
                        "posting_date":date,
                        "items": []
                        }

                    inventory_entries = voucher.findall(".//ALLINVENTORYENTRIES.LIST")
                    if not inventory_entries:
                        print(" - Warning: No ALLINVENTORYENTRIESLIST tag found.")
                    for entry in inventory_entries:
                        item_name_tag = entry.find(".//STOCKITEMNAME")
                        if item_name_tag is not None and item_name_tag.text:
                            item_name = item_name_tag.text.strip()
                        rate_tag = entry.find(".//RATE")
                        if rate_tag is not None and rate_tag.text:
                            Rate = rate_tag.text.strip()
                        quantity_tag = entry.find(".//ACTUALQTY")
                        if quantity_tag is not None and quantity_tag.text:
                            quantity = quantity_tag.text.strip()

                        invoice_data["items"].append({"item_code": item_name, "qty": quantity, "rate":Rate})    

                    if invoice_data["items"]:
                        purchase_invoices.append(invoice_data)
                    else:
                        print(f" - No valid items found for supplier '{supplier_name}'")

                return purchase_invoices
            else:
                print("Failed to clean and parse XML from Tally.")
        else:
            print(f"Failed to connect to Tally. Status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Tally: {e}")
    return []


def add_purchase_invoice_to_erpnext(purchase_invoice):
    erp_endpoint = f"ERP_URL/api/resource/Purchase Invoice"
    headers = {
        "Authorization": "token API KEY:API SECRET",
        "Content-Type": "application/json",
    }

    data = {
        "custom_ref_no":purchase_invoice.get("custom_ref_no"),
        "supplier":purchase_invoice.get("supplier"),
        "posting_date":purchase_invoice.get("posting_date"),
        "items": [
            {
                "item_code": item["item_code"],
                "qty": item["qty"],
                "rate": item["rate"],
            }
            for item in purchase_invoice.get("items", [])
        ],
    }


    try:
        response = requests.post(erp_endpoint, headers=headers, json=data)
        response.raise_for_status()

        invoice_name = response.json().get("data", {}).get("name")
        if not invoice_name:
            print(f"Failed to fetch the Sales Invoice name for customer '{purchase_invoice.get('customer')}'.")
            return

        submit_endpoint = f"{erp_endpoint}/{invoice_name}"
        submit_response = requests.put(
            submit_endpoint, 
            headers=headers, 
            json={"docstatus": 1}  
        )
        submit_response.raise_for_status()
        print(f"Successfully added and submitted Purchase Invoice for '{purchase_invoice.get('supplier')}' to ERPNext.")
    except requests.exceptions.HTTPError as err:
        print(f"Failed to add Purchase Invoice for '{purchase_invoice.get('supplier')}' to ERPNext: {err}")
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
        print(f"Error occurred while adding Purchase Invoice for '{purchase_invoice.get('supplier')}' to ERPNext: {err}")


def sync_purchase_invoices():
    print("Fetching Purchase Invoices from Tally Prime...")
    purchase_invoices = get_purchase_invoices_from_tally()

    if not purchase_invoices:
        print("No purchase invoices to sync.")
        return

    print(f"\nFound {len(purchase_invoices)} Purchase Invoice(s) to sync.\n")

    for idx, purchase_invoice in enumerate(purchase_invoices, start=1):
        print(f"Syncing Purchase Invoice {idx}...")
        add_purchase_invoice_to_erpnext(purchase_invoice)


if __name__ == "__main__":
    sync_purchase_invoices()




