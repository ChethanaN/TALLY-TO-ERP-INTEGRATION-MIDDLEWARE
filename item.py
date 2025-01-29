import requests
import xml.etree.ElementTree as ET
import re


def clean_unwanted_characters(xml_data):
    fixed_xml = re.sub(r'(\s)([a-zA-Z0-9_-]+)\s*=\s*([a-zA-Z0-9_-]+)', r'\1"\2"="\3"', xml_data)
    cleaned_data = re.sub(r'[^a-zA-Z0-9\s<>\-="/:.]', '', fixed_xml)
    return cleaned_data


def modify_rate_and_quantity(xml_data):
    xml_data = re.sub(r'(<RATE[^>]*>)([\d\.]+)(/no)(</RATE>)', r'\1\2\4', xml_data)
    xml_data = re.sub(r'(<OPENINGBALANCE[^>]*>)\s*([\d\.]+)\s*no(</OPENINGBALANCE>)', r'\1\2\3', xml_data)
    return xml_data


def preserve_numeric_format(xml_data):
    numeric_pattern = re.compile(r'\d+\.\d+(/[a-zA-Z]*)?')

    def replace_invalid_chars(match):
        return match.group(0)

    cleaned_data = numeric_pattern.sub(replace_invalid_chars, xml_data)
    return cleaned_data


def clean_xml(xml_data):
    cleaned_xml = clean_unwanted_characters(xml_data)
    cleaned_xml = modify_rate_and_quantity(cleaned_xml)
    cleaned_xml = preserve_numeric_format(cleaned_xml)

    try:
        root = ET.fromstring(cleaned_xml)
        return ET.tostring(root, encoding="unicode")
    except ET.ParseError as e:
        print("Error parsing XML:", e)
        return None


def get_stock_items_from_tally():
    url = "TALLY_URL"
    xml_request = """
    <ENVELOPE>
    <HEADER>
        <VERSION>1</VERSION>
        <TALLYREQUEST>Export</TALLYREQUEST>
        <TYPE>Collection</TYPE>
        <ID>StockItems</ID>
    </HEADER>
    <BODY>
        <DESC>
            <STATICVARIABLES>
                <SVEXPORTFORMAT>SysName:XML</SVEXPORTFORMAT>
            </STATICVARIABLES>
            <TDL>
                <TDLMESSAGE>
                    <COLLECTION NAME="StockItems" ISMODIFY="No" ISFIXED="No" ISINITIALIZE="No" ISOPTION="No" ISINTERNAL="No">
                        <TYPE>StockItem</TYPE>
                        <NATIVEMETHOD>*</NATIVEMETHOD>
                    </COLLECTION>
                </TDLMESSAGE>
            </TDL>
        </DESC>
    </BODY>
</ENVELOPE>
    """

    headers = {"Content-Type": "text/xml"}

    try:
        response = requests.post(url, data=xml_request, headers=headers, timeout=10)

        if response.status_code == 200:
            raw_xml = response.text
            cleaned_xml = clean_xml(raw_xml)
            if cleaned_xml:
                root = ET.fromstring(cleaned_xml)
                items = []

                for stock_item in root.findall(".//STOCKITEM"):
                    item_name = stock_item.find(".//NAME")
                    if item_name is None or not item_name.text.strip(): 
                        continue
                    item_name = item_name.text.strip()

                    opening_balance = ""
                    for batch_allocation in stock_item.findall(".//BATCHALLOCATIONS.LIST"):
                        opening_balance = batch_allocation.find("OPENINGBALANCE")
                        if opening_balance is not None:
                            opening_balance = opening_balance.text

                    hsn_detail = stock_item.find(".//HSNDETAILS.LIST/HSNCODE")
                    hsn_code = hsn_detail.text if hsn_detail is not None and hsn_detail.text else "010121"

                    parent_group = stock_item.find(".//PARENT")
                    parent_group = parent_group.text if parent_group is not None else "Products"

                    items.append({
                        'item_name': item_name,
                        'hsn_codes': hsn_code,
                        'parent_group': parent_group,
                        'rate':opening_balance
                    })

                if items:
                    return items
                else:
                    print("No stock items found in the response.")
            else:
                print("Failed to clean the XML data.")
        else:
            print(f"Failed to connect to Tally. Status code: {response.status_code}")

    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Tally: {e}")

    return []


def add_item_to_erpnext(item):
    erpnext_endpoint = "ERP_URL/api/resource/Item"
    headers = {
        "Authorization": "token API KEY:API SECRET",
        "Content-Type": "application/json"
    }
    data = {
        "item_code": item.get('item_name', 'Unnamed Item'),
        "item_group": item.get('parent_group', 'Products'),
        "stock_uom": "Nos",
        "gst_hsn_code": item.get('hsn_codes', '010121'),
        "valuation_rate": item.get('rate', ' ')
    }

    try:
        response = requests.post(erpnext_endpoint, headers=headers, json=data)
        response.raise_for_status()
        print(f"Successfully added item {item['item_name']} to ERPNext.")
    except requests.exceptions.HTTPError as err:
        if response.status_code == 409:
            print(f"Item {item['item_name']} already exists, skipping....")
        else:
            print(f"Failed to add Item {item['item_name']} to ERPNext: {err}")
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
        print(f"Error occurred while adding Item {item['item_name']} to ERPNext: {err}")


def sync_stock_items():
    items = get_stock_items_from_tally()

    if not items:
        print("No new stock items to sync.")
        return

    for item in items:
        if 'item_name' in item:
            add_item_to_erpnext(item)
        else:
            print(f"Item data missing 'item_name': {item}")


if __name__ == "__main__":
    sync_stock_items()
