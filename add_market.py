import sqlite3
conn = sqlite3.connect('markets.db')
cursor = conn.cursor()
try:
    cursor.execute("INSERT INTO watched_markets (asset_id, title, is_active) VALUES (?, ?, ?)", 
                   ('dummy_asset_id_123', 'Test Market Update', 1))
    conn.commit()
    print("Market added.")
except Exception as e:
    print(e)
conn.close()
