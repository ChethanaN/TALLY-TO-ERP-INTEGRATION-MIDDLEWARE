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
        <ID>SundryCreditorsLedgers</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>
            </STATICVARIABLES>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="SundryCreditorsLedgers" ISMODIFY="No" ISFIXED="No" ISINITIALIZE="No" ISOPTION="No" ISINTERNAL="No">
                        <TYPE>Ledger</TYPE>
                        <NATIVEMETHOD>*</NATIVEMETHOD>
                        <FILTER>IsSundryCreditors</FILTER>
                    </COLLECTION>
                    <SYSTEM TYPE="Formulae" NAME="IsSundryCreditors">
                        $Parent = "Sundry Creditors"
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


def get_suppliers_from_tally():
    raw_xml = fetch_tally_data()


    cleaned_xml = clean_xml(raw_xml)

    if cleaned_xml:
        try:
            root = ET.fromstring(cleaned_xml)

            suppliers = []
            for ledger in root.findall(".//LEDGER"):
                supplier_name = ledger.find(".//NAME")
                if supplier_name is None or not supplier_name.text.strip(): 
                    continue
                supplier_name = supplier_name.text.strip()
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


                suppliers.append({
                    'supplier_name': supplier_name,
                    'pan':pan_no,
                    'gstin': gstin,
                    "gst":gst_registration,
                    'state':state,
                    'address':primary_address,
                    'pincode':pincode
                })

            if suppliers:
                return suppliers
            else:
                print("No customers found in the response.")
        except ET.ParseError as e:
            print(f"Error parsing cleaned XML: {e}")
    else:
        print("Failed to clean the XML response.")
    return []

def add_supplier_to_erpnext(supplier):
    erp_endpoint = "ERP_URL/api/resource/Supplier"
    headers = {
        "Authorization": "token API KEY:API SECRET", 
        "Content-Type": "application/json"
    }

    data = {
        "doctype": "Supplier",
        "supplier_name":supplier.get('supplier_name', 'Unnamed Supplier'),
        "custom_state":supplier.get('state','Not Available'),
        "custom_zip":supplier.get('pincode',' '),
        "gst_category":supplier.get('gst','Unregistered'),
        "gstin":supplier.get('gstin', ' '),
        "pan":supplier.get('pan',' '),
        "primary_address":supplier.get('address','Not Available')
    }
    try:
        response = requests.post(erp_endpoint, headers=headers, json=data)
        response.raise_for_status()
        print(f"Successfully added supplier {supplier['supplier_name']} to ERPNext.")
    except requests.exceptions.HTTPError as err:
        if response.status_code == 409:
            print(f"Supplier {supplier['supplier_name']} already exists, skipping....")
        else:
            print(f"Failed to add supplier {supplier['supplier_name']} to ERPNext: {err}")
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
        print(f"Error occurred while adding Supplier {supplier['supplier_name']} to ERPNext: {err}")

def sync_suppliers():
    suppliers = get_suppliers_from_tally()

    if not suppliers:
        print("No new suppliers to sync.")
        return

    for supplier in suppliers:
        if 'supplier_name' in supplier:
            add_supplier_to_erpnext(supplier)
        else:
            print(f"Supplier data missing 'supplier_name': {supplier}")


if __name__ == "__main__":
    sync_suppliers()
