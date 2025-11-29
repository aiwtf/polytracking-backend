import requests
import json

def debug_search(q):
    url = "https://gamma-api.polymarket.com/events"
    params = {
        "q": q,
        "limit": 50,
        "closed": "false"
    }
    try:
        response = requests.get(url, params=params)
        data = response.json()
        print(f"Search Query: {q}")
        print(f"Status Code: {response.status_code}")
        print(f"Found {len(data)} events")
        for event in data:
            print(f"- Title: {event.get('title')}")
            markets = event.get('markets', [])
            print(f"  - Markets: {len(markets)}")
            for m in markets:
                 print(f"    - Question: {m.get('question')}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    debug_search("Taiwan")
