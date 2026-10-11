import requests
from bs4 import BeautifulSoup
import json
import os
from datetime import datetime

DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK")
# LGBS hosts the Dallas County tax sales (First Tuesday of the month)
TARGET_COUNTY = "DALLAS%20COUNTY"
LGBS_API_URL = f"https://taxsales.lgbs.com/api/properties?county={TARGET_COUNTY}&state=TX"

# Fix-and-Flip Assumptions (Dallas Market)
REHAB_COST_PER_SQFT = 45.00 # Moderate cosmetic rehab
ARV_PER_SQFT = 185.00 # Average Dallas After Repair Value
MAX_ALL_IN_BUDGET = 150000 # Your specified max budget

def calculate_deal_metrics(min_bid, sqft):
    rehab_cost = sqft * REHAB_COST_PER_SQFT
    arv = sqft * ARV_PER_SQFT
    all_in = min_bid + rehab_cost
    closing_holding_costs = arv * 0.08 # 8% for realtor fees and holding
    net_profit = arv - all_in - closing_holding_costs

    return rehab_cost, arv, all_in, net_profit

def scrape_tax_sales():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

    # Note: LGBS loads data dynamically. In production, intercept the JSON API endpoint.
    # We are simulating the parsed payload loop here.
    response = requests.get(LGBS_API_URL, headers=headers)

    # Fallback to local state if no new listings (prevents spamming)
    if not os.path.exists("seen_deals.json"):
        with open("seen_deals.json", "w") as f:
            json.dump([], f)

    with open("seen_deals.json", "r") as f:
        seen_deals = json.load(f)

    # Simulated parsed data for demonstration
    properties = [
        {"id": "DAL-101", "address": "1402 Example Ln, Mesquite, TX 75149", "min_bid": 35000, "sqft": 1200},
        {"id": "DAL-102", "address": "808 Sample St, Dallas, TX 75216", "min_bid": 18000, "sqft": 950},
        {"id": "DAL-103", "address": "2910 Test Dr, Garland, TX 75042", "min_bid": 45000, "sqft": 1400}
    ]

    new_deals_found = []

    for prop in properties:
        if prop["id"] in seen_deals:
            continue

        rehab, arv, all_in, profit = calculate_deal_metrics(prop["min_bid"], prop["sqft"])

        # Filter: Only send deals that fit your $150k max budget and have positive margin
        if all_in <= MAX_ALL_IN_BUDGET and profit > 20000:
            payload = {
                "embeds": [{
                    "title": "🚨 New Tax Sale Deal Fit",
                    "description": f"**Address:** {prop['address']}",
                    "color": 65280,
                    "fields": [
                        {"name": "Minimum Bid (Tax Due)", "value": f"${prop['min_bid']:,.0f}", "inline": True},
                        {"name": "Est. Rehab ($45/sqft)", "value": f"${rehab:,.0f}", "inline": True},
                        {"name": "Total All-In", "value": f"${all_in:,.0f}", "inline": True},
                        {"name": "Est. ARV ($185/sqft)", "value": f"${arv:,.0f}", "inline": False},
                        {"name": "Projected Net Profit", "value": f"**${profit:,.0f}**", "inline": False}
                    ],
                    "footer": {"text": "LGBS Dallas County Auction"}
                }]
            }
            requests.post(DISCORD_WEBHOOK, json=payload)
            seen_deals.append(prop["id"])
            new_deals_found.append(prop)

    with open("seen_deals.json", "w") as f:
        json.dump(seen_deals, f)

if __name__ == "__main__":
    scrape_tax_sales()
