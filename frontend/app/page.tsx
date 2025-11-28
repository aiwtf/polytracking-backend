"use client";

import { useState, useEffect } from "react";
import { Trash2, Plus, Activity, RefreshCw, AlertTriangle } from "lucide-react";

interface Market {
  asset_id: string;
  title: string;
  is_active: boolean;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "https://polytracking-backend-tv7j.onrender.com";

export default function Home() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // Form State
  const [newAssetId, setNewAssetId] = useState("");
  const [newTitle, setNewTitle] = useState("");
  const [adding, setAdding] = useState(false);

  const fetchMarkets = async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/markets`);
      if (!res.ok) throw new Error("Failed to fetch markets");
      const data = await res.json();
      setMarkets(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMarkets();
  }, []);

  const handleAddMarket = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newAssetId || !newTitle) return;

    setAdding(true);
    setError("");
    try {
      const res = await fetch(`${API_URL}/api/markets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ asset_id: newAssetId, title: newTitle }),
      });
      if (!res.ok) throw new Error("Failed to add market");

      setNewAssetId("");
      setNewTitle("");
      fetchMarkets(); // Refresh list
    } catch (err: any) {
      setError(err.message);
    } finally {
      setAdding(false);
    }
  };

  const handleDeleteMarket = async (assetId: string) => {
    if (!confirm("Are you sure you want to stop monitoring this market?")) return;

    try {
      const res = await fetch(`${API_URL}/api/markets/${assetId}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error("Failed to delete market");
      fetchMarkets();
    } catch (err: any) {
      setError(err.message);
    }
  };

  return (
    <main className="min-h-screen bg-black text-green-500 font-mono p-8">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <header className="mb-8 border-b border-green-800 pb-4 flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-2">
              <Activity className="w-8 h-8" />
              POLYMARKET WAR MONITOR
            </h1>
            <p className="text-green-700 text-sm mt-1">Backend: {API_URL}</p>
          </div>
          <button
            onClick={fetchMarkets}
            className="p-2 hover:bg-green-900 rounded transition-colors"
            title="Refresh"
          >
            <RefreshCw className={`w-6 h-6 ${loading ? "animate-spin" : ""}`} />
          </button>
        </header>

        {/* Error Message */}
        {error && (
          <div className="mb-6 p-4 bg-red-900/20 border border-red-500 text-red-500 rounded flex items-center gap-2">
            <AlertTriangle className="w-5 h-5" />
            {error}
          </div>
        )}

        {/* Add Market Form */}
        <section className="mb-12 bg-gray-900/50 p-6 rounded border border-green-800">
          <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
            <Plus className="w-5 h-5" /> Add New Target
          </h2>
          <form onSubmit={handleAddMarket} className="flex flex-col md:flex-row gap-4">
            <input
              type="text"
              placeholder="Asset ID (Long String)"
              value={newAssetId}
              onChange={(e) => setNewAssetId(e.target.value)}
              className="flex-1 bg-black border border-green-700 p-2 rounded focus:outline-none focus:border-green-400 text-green-400 placeholder-green-800"
            />
            <input
              type="text"
              placeholder="Event Title (e.g. Taiwan Invasion)"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              className="flex-1 bg-black border border-green-700 p-2 rounded focus:outline-none focus:border-green-400 text-green-400 placeholder-green-800"
            />
            <button
              type="submit"
              disabled={adding}
              className="bg-green-700 text-black font-bold px-6 py-2 rounded hover:bg-green-600 disabled:opacity-50 transition-colors"
            >
              {adding ? "DEPLOYING..." : "START MONITOR"}
            </button>
          </form>
        </section>

        {/* Market List */}
        <section>
          <h2 className="text-xl font-bold mb-4">Active Targets ({markets.length})</h2>
          <div className="grid gap-4">
            {markets.map((market) => (
              <div
                key={market.asset_id}
                className="bg-gray-900/30 border border-green-900 p-4 rounded flex justify-between items-center hover:border-green-600 transition-colors"
              >
                <div>
                  <h3 className="text-lg font-bold text-green-400">{market.title}</h3>
                  <p className="text-xs text-green-800 font-mono mt-1 break-all">ID: {market.asset_id}</p>
                  <div className="flex items-center gap-2 mt-2">
                    <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse"></span>
                    <span className="text-xs text-green-600 uppercase">Monitoring Active</span>
                  </div>
                </div>
                <button
                  onClick={() => handleDeleteMarket(market.asset_id)}
                  className="p-2 text-red-500 hover:bg-red-900/20 rounded transition-colors"
                  title="Stop Monitoring"
                >
                  <Trash2 className="w-5 h-5" />
                </button>
              </div>
            ))}

            {markets.length === 0 && !loading && (
              <div className="text-center py-12 text-green-800 border border-dashed border-green-900 rounded">
                No active targets. Add one above.
              </div>
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
