import requests
import xml.etree.ElementTree as ET
import re

TALLY_API_URL = "YOUR_TALLY_URL" 

def clean_unwanted_characters(xml_data):
    fixed_xml = re.sub(r'(\s)([a-zA-Z0-9_-]+)=([a-zA-Z0-9_-]+)', r'\1"\2"=\3', xml_data)
    cleaned_data = re.sub(r'[^a-zA-Z0-9\s<>\-=/":]', '', fixed_xml)
    return cleaned_data


def clean_xml(xml_data):
    cleaned_xml = clean_unwanted_characters(xml_data)
    try:
        root = ET.fromstring(cleaned_xml)
        return ET.tostring(root, encoding="unicode")
    except ET.ParseError as e:
        print("Error parsing XML:", e)
        return None


def fetch_tally_data():
    payload = """<ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>SundryDebtorsLedgers</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
            </STATICVARIABLES>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="SundryDebtorsLedgers" ISMODIFY="No" ISFIXED="No" ISINITIALIZE="No" ISOPTION="No" ISINTERNAL="No">
                        <TYPE>Ledger</TYPE>
                        <NATIVEMETHOD>*</NATIVEMETHOD>
                        <FILTER>IsSundryDebtors</FILTER>
                    </COLLECTION>
                    <SYSTEM TYPE="Formulae" NAME="IsSundryDebtors">
                        $Parent = "Sundry Debtors"
                    </SYSTEM>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>
"""

    headers = {"Content-Type": "application/xml"}
    response = requests.post(TALLY_API_URL, data=payload, headers=headers)

    if response.status_code == 200:
        return response.text
    else:
        print(f"Failed to fetch data from Tally. Status code: {response.status_code}")
        return None


def get_customers_from_tally():
    raw_xml = fetch_tally_data()

    cleaned_xml = clean_xml(raw_xml)

    if cleaned_xml:
        try:
            root = ET.fromstring(cleaned_xml)

            customers = []
            for ledger in root.findall(".//LEDGER"):
                customer_name = ledger.find(".//NAME")
                if customer_name is None or not customer_name.text.strip(): 
                    continue
                customer_name = customer_name.text.strip()
                
                pan_no = ledger.find(".//INCOMETAXNUMBER").text if ledger.find(".//INCOMETAXNUMBER") is not None else " "
                
                gst_registration ="Unregistered"
                gst_element = ledger.find(".//LEDGSTREGDETAILSLIST/GSTREGISTRATIONTYPE")
                if gst_element is not None:
                    gst_registration = gst_element.text
                
                if gst_registration == "Regular":
                    gst_registration = "Registered Regular"
                if gst_registration == "Composition":
                    gst_registration = "Registered Composition"
                if gst_registration == "Unkown":
                    gst_registration = " "
                if gst_registration == "Unregistered/Consumer":
                    gst_registration == "Unregistered"

                gstin = None
                gstin_element = ledger.find(".//LEDGSTREGDETAILSLIST/GSTIN")
                if gstin_element is not None:
                    gstin = gstin_element.text

                state = None
                state_element = ledger.find(".//LEDMAILINGDETAILSLIST/STATE")
                if state_element is not None:
                    state = state_element.text

                
                addresses = []
                for address_element in ledger.findall(".//LEDMAILINGDETAILSLIST//ADDRESSLIST/ADDRESS"):
                    if address_element.text:
                        addresses.append(address_element.text.strip())
                primary_address = ", ".join(addresses) if addresses else "Not Available"

                pincode = " "
                pincode_element = ledger.find(".//LEDMAILINGDETAILSLIST/PINCODE")
                if pincode_element is not None:
                    pincode = pincode_element.text

                customers.append({
                    'customer_name': customer_name,
                    'pan': pan_no,
                    'gstin': gstin,
                    "gst": gst_registration,
                    'state': state,
                    'address': primary_address,  
                    'pincode': pincode
                })

            if customers:
                return customers
            else:
                print("No customers found in the response.")
        except ET.ParseError as e:
            print(f"Error parsing cleaned XML: {e}")
    else:
        print("Failed to clean the XML response.")
    return []


def is_customer_present(customer_name):
    """Check if a customer exists in ERPNext using the custom API."""
    try:
        response = requests.get(
            f"CUSTOM_API TO CHECK THE EXISTANCE OF CUSTOMER IN ERP",
            params={"customer_name": customer_name}
        )
        if response.status_code == 200:
            result = response.json()
            return result.get("message", False) 
        else:
            print(f"Failed to check if customer exists. Status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"Error checking customer existence: {e}")
        return False


def add_customer_to_erpnext(customer):
    """Add a customer to ERPNext only if they don't already exist."""
    if is_customer_present(customer.get('customer_name')):
        print(f"Customer {customer['customer_name']} already exists in ERPNext. Skipping...")
        return

    erpnext_endpoint = "YOUR_ERP_URL/api/resource/Customer"
    headers = {
        "Authorization": "token API KEY:API SECRET",
        "Content-Type": "application/json"
    }

    data = {
        "doctype": "Customer",
        "customer_name": customer.get('customer_name', 'Unnamed Customer'),
        "custom_state": customer.get('state', 'Not Available'),
        "custom_zip": customer.get('pincode', 'Not Available'),
        "gst_category": customer.get('gst', 'Unregistered'),
        "gstin": customer.get('gstin', ' '),
        "pan": customer.get('pan', ' '),
        "primary_address": customer.get('address', 'Not Available')
    }

    try:
        response = requests.post(erpnext_endpoint, headers=headers, json=data)
        response.raise_for_status()
        print(f"Successfully added customer {customer['customer_name']} to ERPNext.")
    except requests.exceptions.HTTPError as err:
        print(f"Failed to add customer {customer['customer_name']} to ERPNext: {err}")
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
        print(f"Error occurred while adding customer {customer['customer_name']} to ERPNext: {err}")


def sync_customers():
    customers = get_customers_from_tally()

    if not customers:
        print("No new customers to sync.")
        return

    for customer in customers:
        if 'customer_name' in customer:
            add_customer_to_erpnext(customer)
        else:
            print(f"Customer data missing 'customer_name': {customer}")


if __name__ == "__main__":
    sync_customers()
