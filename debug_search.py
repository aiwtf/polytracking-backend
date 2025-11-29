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
            
            for i, event in enumerate(events[:2]):
                f.write(f"\nEvent {i+1}: {event.get('title')}\n")
                markets = event.get("markets", [])
                f.write(f"Markets found: {len(markets)}\n")
                for j, m in enumerate(markets[:3]):
                    f.write(f"  Market {j+1}:\n")
                    f.write(f"    question: {m.get('question')}\n")
                    f.write(f"    groupItemTitle: {m.get('groupItemTitle')}\n")
                    f.write(f"    asset_id: {m.get('asset_id')}\n")
                    f.write(f"    clobTokenIds: {m.get('clobTokenIds')}\n")
                    f.write(f"    outcomes: {m.get('outcomes')}\n")
        else:
            f.write(f"Error: {response.text}\n")
            
    except Exception as e:
        f.write(f"Error: {e}\n")

if __name__ == "__main__":
    with open("search_debug_assets.txt", "w", encoding="utf-8") as f:
        debug_search("tweets", f)
