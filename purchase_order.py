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


def get_purchase_orders_from_tally():
    url = "TALLY_URL"
    xml_request = """
<ENVELOPE>
    <HEADER>
        <TALLYREQUEST>Export Data</TALLYREQUEST>
    </HEADER>
    <BODY>
        <EXPORTDATA>
            <REQUESTDESC>
                <REPORTNAME>Voucher Register</REPORTNAME>
                <STATICVARIABLES>
                    <VOUCHERTYPENAME>Purchase Order</VOUCHERTYPENAME>
                </STATICVARIABLES>
            </REQUESTDESC>
        </EXPORTDATA>
    </BODY>
</ENVELOPE>
    """
    headers = {"Content-Type": "text/xml"}
    try:
        response = requests.post(url, data=xml_request, headers=headers, timeout=10)
        if response.status_code == 200:
            raw_xml = response.text
            cleaned_xml = normalize_and_clean_xml(raw_xml)

            if cleaned_xml:
                root = ET.fromstring(cleaned_xml)
                purchase_orders = []

                for voucher in root.findall(".//VOUCHER"):
                   
                    party_ledger_tag = voucher.find(".//PARTYLEDGERNAME")
                    party_ledger = (
                        party_ledger_tag.text.strip()
                        if party_ledger_tag is not None and party_ledger_tag.text
                        else "Unknown Supplier"
                    )
                    print(f"\nProcessing Voucher for Supplier: {party_ledger}")
                   
                    voucher_number_tag = voucher.find(".//VOUCHERNUMBER")
                    voucher_no = voucher_number_tag.text.strip()

                    date_tag = voucher.find(".//DATE")
                    date = date_tag.text.strip()
                    if date:
                       date = datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")

                    due_date_tag = voucher.find(".//ORDERDUEDATE")
                    due_date = due_date_tag.text.strip()
                    if due_date:
                        due_date = datetime.strptime(due_date, "%d-%b-%y").strftime("%Y-%m-%d")

                    
                    po_data = {
                        "custom_ref_no": voucher_no,
                        "transaction_date":date,
                        "schedule_date":due_date,
                        "party_ledger": party_ledger, 
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
                    
                        po_data["items"].append({"item_name": item_name,"rate":Rate,"qty":quantity})
                    
                    if po_data["items"]:
                        purchase_orders.append(po_data)
                    else:
                        print(f" - No valid items found for voucher '{party_ledger}'")

                return purchase_orders
            else:
                print("Failed to clean and parse XML from Tally.")
        else:
            print(f"Failed to connect to Tally. Status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Tally: {e}")
    return []


def add_purchase_order_to_erpnext(purchase_order):
    erpnext_endpoint = "ERP_URL/api/resource/Purchase Order"
    headers = {
        "Authorization": "token API KEY:API SECRET",
        "Content-Type": "application/json",
    }

    data = {
        "custom_ref_no":purchase_order.get("custom_ref_no"),
        "supplier": purchase_order.get("party_ledger"),
        "transaction_date":purchase_order.get("transaction_date"),
        "docstatus": 1,
        "set_warehouse":"Sahaj Solar - SSL",
        "items": [
            {
                "item_code": item["item_name"],
                "custom_content": "Set",
                "schedule_date": purchase_order.get("schedule_date"),
                "qty": item["qty"],
                "rate": item["rate"]
            }
            for item in purchase_order.get("items", [])
        ],
    }

    try:
        response = requests.post(erpnext_endpoint, headers=headers, json=data)
        response.raise_for_status()
        print(f"Successfully added Purchase Order '{purchase_order.get('party_ledger')}' to ERPNext.")
    except requests.exceptions.HTTPError as err:
        print(f"Failed to add Purchase Order '{purchase_order.get('party_ledger')}' to ERPNext: {err}")
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
        print(f"Error occurred while adding Purchase Order '{purchase_order.get('party_ledger')}' to ERPNext: {err}")


def sync_purchase_orders():
    print("Fetching Purchase Orders from Tally Prime...")
    purchase_orders = get_purchase_orders_from_tally()

    if not purchase_orders:
        print("No purchase orders to sync.")
        return

    print(f"\nFound {len(purchase_orders)} Purchase Order(s) to sync.\n")

    for idx, purchase_order in enumerate(purchase_orders, start=1):
        print(f"Syncing Purchase Order {idx}...")
        add_purchase_order_to_erpnext(purchase_order)


if __name__ == "__main__":
    sync_purchase_orders()