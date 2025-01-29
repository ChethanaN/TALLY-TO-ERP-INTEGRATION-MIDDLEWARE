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


def get_sales_orders_from_tally():
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
        <VOUCHERTYPENAME>Sales Order</VOUCHERTYPENAME>
        </STATICVARIABLES>
        <REPORTNAME>Voucher Register</REPORTNAME>
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
                sales_orders = []

                for voucher in root.findall(".//VOUCHER"):
                    customer_tag = voucher.find(".//PARTYNAME")
                    customer_name = (
                        customer_tag.text.strip()
                        if customer_tag is not None and customer_tag.text
                        else "Unknown Customer"
                    )

                    voucher_number_tag = voucher.find(".//VOUCHERNUMBER")
                    voucher_no = voucher_number_tag.text.strip()
                    
                    date_tag = voucher.find(".//DATE")
                    date = date_tag.text.strip()
                    if date:
                       date = datetime.strptime(date, "%Y%m%d").strftime("%Y-%m-%d")

                    due_date_tag = voucher.find(".//ORDERDUEDATE")
                    delivery_date = due_date_tag.text.strip()
                    if delivery_date:
                        delivery_date = datetime.strptime(delivery_date, "%d-%b-%y").strftime("%Y-%m-%d")


                    order_data = {
                        "custom_ref_no": voucher_no,
                        "transaction_date":date,
                        "delivery_date":delivery_date,
                        "customer": customer_name, 
                        "items": []
                        }

                    inventory_entries = voucher.findall(".//ALLINVENTORYENTRIES.LIST")
                    if not inventory_entries:
                        print(" - Warning: No ALLINVENTORYENTRIES.LIST tag found.")
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
                            
                        order_data["items"].append(
                            {
                                "item_code": item_name,
                                "qty": quantity,
                                "rate": Rate,
                                "warehouse": "All Warehouses - SSL",
                            }
                        )
                    if order_data["items"]:
                        sales_orders.append(order_data)
                    else:
                        print(f" - No valid items found for customer '{customer_name}'")

                return sales_orders
            else:
                print("Failed to clean and parse XML from Tally.")
        else:
            print(f"Failed to connect to Tally. Status code: {response.status_code}")
    except requests.exceptions.RequestException as e:
        print(f"Error connecting to Tally: {e}")
    return []


def add_sales_order_to_erpnext(sales_order):
    erpnext_endpoint = "ERP_URL/api/resource/Sales Order"
    headers = {
        "Authorization": "token API KEY:API SECRET",
        "Content-Type": "application/json",
    }

    data = {
        "doctype": "Sales Order",
        "custom_ref_no":sales_order.get("custom_ref_no"),
        "customer": sales_order.get("customer"),
        "transaction_date": sales_order.get("transaction_date"),
        "delivery_date": sales_order.get("delivery_date"),
        "order_type": "Sales",
        "items": [
            {
                "item_code": item["item_code"],
                "delivery_date": sales_order.get("delivery_date"),
                "qty": item["qty"],
                "rate": item["rate"],
                "warehouse": item["warehouse"],
            }
            for item in sales_order.get("items", [])
        ],
    }

    try:
        response = requests.post(erpnext_endpoint, headers=headers, json=data)
        response.raise_for_status()
        print(f"Successfully added Sales Order for '{sales_order.get('customer')}' to ERPNext.")
    except requests.exceptions.HTTPError as err:
        print(f"Failed to add Sales Order for '{sales_order.get('customer')}' to ERPNext: {err}")
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
        print(f"Error occurred while adding Sales Order for '{sales_order.get('customer')}' to ERPNext: {err}")


def sync_sales_orders():
    print("Fetching Sales Orders from Tally Prime...")
    sales_orders = get_sales_orders_from_tally()

    if not sales_orders:
        print("No sales orders to sync.")
        return

    print(f"\nFound {len(sales_orders)} Sales Order(s) to sync.\n")

    for idx, sales_order in enumerate(sales_orders, start=1):
        print(f"Syncing Sales Order {idx}...")
        add_sales_order_to_erpnext(sales_order)


if __name__ == "__main__":
    sync_sales_orders()