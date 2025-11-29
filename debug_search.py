import requests
import json

def debug_search(q, f):
    # Try public-search endpoint with 'q'
    url = "https://gamma-api.polymarket.com/public-search"
    params = {
        "q": q,
        "limit": 20
    }
    try:
        f.write(f"\n--- Testing /public-search with q='{q}' ---\n")
        response = requests.get(url, params=params)
        
        f.write(f"Status: {response.status_code}\n")
        if response.ok:
            data = response.json()
            f.write(f"Response data type: {type(data)}\n")
            if isinstance(data, list):
                f.write(f"Found {len(data)} items\n")
                for i, item in enumerate(data[:5]):
                    f.write(f"{i+1}. {item}\n")
            elif isinstance(data, dict):
                 f.write(f"Keys: {list(data.keys())}\n")
                 # Check for 'events' or 'markets'
                 if 'events' in data:
                     events = data['events']
                     f.write(f"Found {len(events)} events\n")
                     for i, e in enumerate(events[:5]):
                         f.write(f"{i+1}. {e.get('title')}\n")
        else:
            f.write(f"Error: {response.text}\n")
            
    except Exception as e:
        f.write(f"Error: {e}\n")

if __name__ == "__main__":
    with open("search_results_v4.txt", "w", encoding="utf-8") as f:
        debug_search("Elon", f)
        debug_search("tweets", f)
