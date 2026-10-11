import requests
from bs4 import BeautifulSoup
import feedparser
import json
import os
import pdfplumber
import io
import re
import urllib.parse
from datetime import datetime

# ==========================================
# CONFIGURATION & SECRETS
# ==========================================
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
RENTCAST_API_KEY = os.environ.get("RENTCAST_API_KEY")
ATTOM_API_KEY = os.environ.get("ATTOM_API_KEY")
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY")

STATE_FILE = "dfw_radar_state.json"

# Investment Criteria (Customizable)
REHAB_COST_PER_SQFT = 45.00
MAX_ALL_IN_BUDGET = 150000
MIN_NET_PROFIT = 25000

# ==========================================
# STATE MANAGEMENT
# ==========================================
def load_state():
    """Loads historical data to prevent duplicate Discord pings."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"seen_news": [], "seen_pdfs": [], "seen_tax_deals": []}

def save_state(state):
    """Saves current state to the filesystem."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)

# ==========================================
# MODULE 1: MACRO NEWS RADAR
# ==========================================
def check_foreclosure_news(state):
    """Scrapes Google News RSS for DFW distressed real estate & bankruptcies."""
    print("Checking Macro Foreclosure News...")
    query = urllib.parse.quote('(foreclosure OR "distressed property" OR bankruptcy) (Dallas OR "Tarrant County" OR "DFW")')
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

    feed = feedparser.parse(rss_url)

    for entry in feed.entries[:5]: # Process top 5 recent articles
        article_id = entry.link
        if article_id not in state["seen_news"]:
            payload = {
                "embeds": [{
                    "title": "📰 Breaking DFW Real Estate Distress News",
                    "description": f"**[{entry.title}]({entry.link})**",
                    "color": 16711680, # Red
                    "footer": {"text": f"Published: {entry.published}"}
                }]
            }
            requests.post(DISCORD_WEBHOOK, json=payload)
            state["seen_news"].append(article_id)

    # Truncate array to prevent infinite bloat
    state["seen_news"] = state["seen_news"][-50:]

# ==========================================
# MODULE 2: EARLY NOTICE OF TRUSTEE SALE (NTS) RADAR
# ==========================================
def extract_address_from_pdf(pdf_bytes):
    """Uses pdfplumber to find the street address inside a legal NTS filing."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "".join([page.extract_text() + "\n" for page in pdf.pages])
            match = re.search(r'(?i)(commonly known as|street address is|located at)[\s:]*([1-9]\d* [a-zA-Z0-9\s,\.]+TX\s*\d{5})', text)
            if match:
                return match.group(2).strip().replace('\n', ' ')
            return "Address hidden in legal description - Manual review required"
    except Exception:
        return "Could not parse PDF text."

def check_county_clerk_filings(state):
    """Monitors the Dallas County Clerk for new 21-day foreclosure postings."""
    print("Checking Dallas County Clerk NTS Filings...")
    url = "https://www.dallascounty.org/government/county-clerk/recording/foreclosures.php"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    try:
        response = requests.get(url, headers=headers)
        soup = BeautifulSoup(response.text, 'html.parser')
        pdf_links = soup.find_all('a', href=re.compile(r'\.pdf$'))

        for link in pdf_links:
            href = link.get('href')
            if not href.startswith('http'):
                href = "https://www.dallascounty.org" + href

            pdf_id = href.split('/')[-1]

            if pdf_id not in state["seen_pdfs"]:
                print(f"New Pre-Foreclosure Notice Found: {pdf_id}")
                pdf_response = requests.get(href, headers=headers)
                address = extract_address_from_pdf(pdf_response.content)

                payload = {
                    "embeds": [{
                        "title": "🏛️ PRE-FORECLOSURE: New 21-Day NTS Filed",
                        "description": f"**Extracted Address:**\n{address}",
                        "color": 3447003, # Blue
                        "fields": [{"name": "Original County PDF", "value": f"[Click to view Document]({href})"}],
                        "footer": {"text": "Notice filed at Dallas County Clerk"}
                    }]
                }
                requests.post(DISCORD_WEBHOOK, json=payload)
                state["seen_pdfs"].append(pdf_id)

        state["seen_pdfs"] = state["seen_pdfs"][-200:]
    except Exception as e:
        print(f"Error scraping county site: {e}")

# ==========================================
# MODULE 3: TAX SALE DEAL ANALYZER
# ==========================================
def get_property_specs(address):
    """API 1: Get exact SqFt from ATTOM Data."""
    url = "https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/detail"
    headers = {"apikey": ATTOM_API_KEY, "accept": "application/json"}
    parts = address.split(',')
    if len(parts) < 2: return 1200 # Fallback
    params = {"address1": parts[0].strip(), "address2": parts[1].strip()}
    try:
        res = requests.get(url, headers=headers, params=params).json()
        return int(res['property'][0]['building']['size']['universalsize'])
    except:
        return 1200 # Fallback estimate

def get_arv(address):
    """API 2: Get live After Repair Value (AVM) from RentCast."""
    url = "https://api.rentcast.io/v1/avm/value"
    headers = {"X-Api-Key": RENTCAST_API_KEY, "accept": "application/json"}
    params = {"address": address, "compCount": 5, "maxRadius": 2}
    try:
        res = requests.get(url, headers=headers, params=params).json()
        return res['price']
    except:
        return None
def get_zillow_data(address):
    """Pulls property picture and Resale Value (Zestimate)"""
    url = "https://zillow-com1.p.rapidapi.com/property"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "zillow-com1.p.rapidapi.com"
    }
    try:
        res = requests.get(url, headers=headers, params={"address": address}, timeout=10).json()
        image_url = res.get('imgSrc', 'https://via.placeholder.com/600x400?text=No+Image+Available')
        arv = res.get('zestimate')
        return image_url, arv
    except Exception:
        return 'https://via.placeholder.com/600x400?text=Image+Unavailable', None

def analyze_tax_deals(state):
    """Scrapes tax sale lists and underwrites the deals, and ranks Top 5 by ROI."""
    print("Checking Tax Sale Deals...")

    #REPLACED fake addresses with real dfw addresses so Zillow finds a value
    upcoming_auctions = [
        {"id": "DAL-75149-1", "address": "832 Brockden DR, Mesquite, TX 75149", "min_bid": 35000, "county": "Dallas"},
        {"id": "DAL-75216-2", "address": "2618 Idaho Ave, Dallas, TX 75216", "min_bid": 18000, "county": "Dallas"},
        {"id": "DAL-75042-3", "address": "1917 Larry Dr, Garland, TX 75042", "min_bid": 45000, "county": "Dallas"}
    ]

    qualified_deals = []
    for auction in upcoming_auctions:
        prop_id = auction["id"]
        if prop_id in state["seen_tax_deals"]:
            print(f"[SKIP] {prop_id} already processed.")
            continue

        address = auction["address"]
        min_bid = auction["min_bid"]
        county = auction["county"]

        sqft = get_property_specs(address)
        image_url, arv = get_zillow_data(address)

        # Fallback if Zillow fails, use a dallas average ($210/sqft) instead of crashing/skipping
        if not arv:
            arv = sqft * 210

        print(f"[EVALUATING] {address} | SqFt: {sqft} | Min Bid: ${min_bid} | ARV: {arv}")

        rehab_cost = sqft * REHAB_COST_PER_SQFT
        all_in_cost = min_bid + rehab_cost
        closing_costs = arv * 0.08
        net_profit = arv - all_in_cost - closing_costs
        roi_percentage = (net_profit / all_in_cost) * 100

        print(f"[METRICS] All-In: ${all_in_cost:,.0f} | Profit: ${net_profit:,.0f} | ROI: {roi_percentage:.1f}%")

        # 1. ADD VALID DEALS TO A LIST INSTEAD OF SENDING IMMEDIATELY
        if all_in_cost <= MAX_ALL_IN_BUDGET and net_profit >= MIN_NET_PROFIT:
            qualified_deals.append({
                "prop_id": prop_id,
                "address": address,
                "county": county,
                "sqft": sqft,
                "min_bid": min_bid,
                "rehab_cost": rehab_cost,
                "all_in_cost": all_in_cost,
                "arv": arv,
                "net_profit": net_profit,
                "roi_percentage": roi_percentage,
                "image_url": image_url
            }]
        else:
             print(f"[FILTERED OUT] Budget or profit thresold not met for {address}")
            
    # 2. SORT THE LIST BY HIGHEST ROI
    qualified_deals.sort(key=lambda x: x["roi_percentage"}, reverse=True)

    # 3. GRAB ONLY THE TOP 5 DEALS
    top_5_deals = qualified_deals[:5]

    # 4. SEND THE TOP 5 TO DISCORD
    for deal in top_5_deals:
        payload = {
            "embeds": [{
                "title": f"💰 TOP 5 FLIP: {deal['count']} County",
                "description": f"**{deal}[address']}**\n**SqFt:** {deal['sqft']}",
                "color": 16766720, Gold Color
                "image": {"url": deal['image_url']},
                "fields": [
                    {"name": "Min Bid (Acquisition)", "value": f"${min_bid:,.0f}", "inline": True},
                    {"name": "Est. Rehab", "value": f"${rehab_cost:,.0f}", "inline": True},
                    {"name": "Total All-In Cost", "value": f"${all_in_cost:,.0f}", "inline": True},
                    {"name": "Resale Value (ARV)", "value": f"${arv:,.0f}", "inline": False},
                    {"name": "Projected Net Profit", "value": f"**${net_profit:,.0f}**", "inline": True},
                    {"name": "Estimated ROI", "value": f"**{roi_percentage:.1f}%**", "inline": True}
                ]
            }]
        }
        if DISCORD_WEBHOOK:
            resp = requests.post(DISCORD_WEBHOOK, json=payload)
            print(f"[DISCORD POST] Top Deal Sent: {resp.status_code}")
            if resp.status_code != 204:
                print(f"[DISCORD ERROR] {resp.text}")
        else:
            print("[ERROR] DISCORD_WEBHOOK is not set or empty!")
        state["seen_tax_deals"].append(prop_id)
    else:
        print(f"[FILTERED OUT] Budget or profit threshold not met for {address}")
if __name__ == "__main__":
    from datetime import datetime
    print(f"Starting DFW Foreclosure Engine at {datetime.now()}")

    # Verify Webhook Connectivity immediately
    if DISCORD_WEBHOOK:
        test_resp = requests.post(DISCORD_WEBHOOK, json={"content": "🚀 **Foreclosure Scanner Connected & Running**"})
        print(f"Test Ping Status: {test_resp.status_code}")
    else:
        print("CRITICAL: DISCORD_WEBHOOK environment variable is missing!")

    current_state = load_state()
    check_foreclosure_news(current_state)
    check_county_clerk_filings(current_state)
    analyze_tax_deals(current_state)
    save_state(current_state)
    print("Execution Complete.")
