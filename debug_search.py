import requests
import json

def debug_search(q, f):
    url = "https://gamma-api.polymarket.com/public-search"
    params = {
        "q": q,
        "limit": 5
    }
    try:
        f.write(f"\n--- Testing /public-search with q='{q}' ---\n")
        response = requests.get(url, params=params)
        
        if response.ok:
            data = response.json()
            events = data.get("events", []) if isinstance(data, dict) else data
            
            for i, event in enumerate(events[:2]): # Check first 2 events
                f.write(f"\nEvent {i+1}: {event.get('title')}\n")
                markets = event.get("markets", [])
                f.write(f"Markets found: {len(markets)}\n")
                for j, m in enumerate(markets[:3]): # Check first 3 markets
                    f.write(f"  Market {j+1}:\n")
                    f.write(f"    Keys: {list(m.keys())}\n")
                    f.write(f"    outcomePrices: {m.get('outcomePrices')}\n")
                    f.write(f"    bestBid: {m.get('bestBid')}\n")
                    f.write(f"    bestAsk: {m.get('bestAsk')}\n")
                    f.write(f"    lastTradePrice: {m.get('lastTradePrice')}\n")
        else:
            f.write(f"Error: {response.text}\n")
            
    except Exception as e:
        f.write(f"Error: {e}\n")

if __name__ == "__main__":
    with open("search_debug_prices.txt", "w", encoding="utf-8") as f:
        debug_search("tweets", f)
