"use client";

import { useState, useEffect, useCallback } from "react";
import { useUser, SignInButton, UserButton } from "@clerk/nextjs";
import { useDebounce } from "use-debounce";
import {
  Search,
  Plus,
  Trash2,
  Bell,
  Zap,
  Activity,
  Droplets,
  Fish,
  Anchor
} from "lucide-react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const BOT_USERNAME = "Polytracking_bot";

interface SearchResult {
  title: string;
  image: string;
  options: {
    name: string;
    asset_id: string;
    current_price: number;
  }[];
}

interface Subscription {
  id: number;
  asset_id: string;
  title: string;
  target_outcome: string;
  notify_0_5pct: boolean;
  notify_2pct: boolean;
  notify_5pct: boolean;
  notify_whale_10k: boolean;
  notify_whale_50k: boolean;
  notify_liquidity: boolean;
}

export default function Dashboard() {
  const { user, isLoaded, isSignedIn } = useUser();

  // State
  const [telegramToken, setTelegramToken] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [debouncedSearchQuery] = useDebounce(searchQuery, 500);
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(false);
  const [searching, setSearching] = useState(false);

  // Fetch Subscriptions
  const fetchSubscriptions = useCallback(async () => {
    if (!user) return;
    try {
      const res = await fetch(`${API_URL}/api/markets?clerk_user_id=${user.id}`);
      if (res.ok) {
        const data = await res.json();
        setSubscriptions(data);
      }
    } catch (err) {
      console.error("Failed to fetch subscriptions", err);
    }
  }, [user]);

  useEffect(() => {
    if (isSignedIn) {
      fetchSubscriptions();
    }
  }, [isSignedIn, fetchSubscriptions]);

  // Search Effect
  useEffect(() => {
    const search = async () => {
      if (!debouncedSearchQuery) {
        setSearchResults([]);
        return;
      }
      setSearching(true);
      try {
        const res = await fetch(`${API_URL}/api/proxy/search?q=${encodeURIComponent(debouncedSearchQuery)}`);
        if (res.ok) {
          const data = await res.json();
          setSearchResults(data);
        }
      } catch (err) {
        console.error("Search failed", err);
      } finally {
        setSearching(false);
      }
    };
    search();
  }, [debouncedSearchQuery]);

  // Handlers
  const handleConnectTelegram = async () => {
    if (!user) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/connect_telegram`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clerk_user_id: user.id }),
      });
      const data = await res.json();
      if (data.status === "success") {
        setTelegramToken(data.connection_token);
        window.open(`https://t.me/${BOT_USERNAME}?start=${data.connection_token}`, "_blank");
      }
    } catch (err) {
      alert("Failed to connect Telegram");
    } finally {
      setLoading(false);
    }
  };

  const handleTrack = async (title: string, option: { name: string, asset_id: string }) => {
    if (!user) return;
    try {
      const res = await fetch(`${API_URL}/api/markets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          clerk_user_id: user.id,
          asset_id: option.asset_id,
          title: `${title} - ${option.name}`,
          target_outcome: option.name,
          notify_2pct: true // Default setting
        }),
      });
      if (res.ok) {
        fetchSubscriptions();
        setSearchQuery(""); // Clear search on success
      } else {
        alert("Failed to track market");
      }
    } catch (err) {
      console.error(err);
    }
  };

  const handleUpdateSubscription = async (asset_id: string, updates: Partial<Subscription>) => {
    if (!user) return;

    // Optimistic update
    setSubscriptions(prev => prev.map(sub =>
      sub.asset_id === asset_id ? { ...sub, ...updates } : sub
    ));

    try {
      // We need to send the FULL object or at least the fields the backend expects.
      // The backend uses MarketCreate model for POST which expects all fields or defaults.
      // Let's find the current sub to merge.
      const currentSub = subscriptions.find(s => s.asset_id === asset_id);
      if (!currentSub) return;

      const payload = {
        clerk_user_id: user.id,
        asset_id: asset_id,
        title: currentSub.title,
        target_outcome: currentSub.target_outcome,
        notify_0_5pct: currentSub.notify_0_5pct,
        notify_2pct: currentSub.notify_2pct,
        notify_5pct: currentSub.notify_5pct,
        notify_whale_10k: currentSub.notify_whale_10k,
        notify_whale_50k: currentSub.notify_whale_50k,
        notify_liquidity: currentSub.notify_liquidity,
        ...updates
      };

      await fetch(`${API_URL}/api/markets`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      // No need to refetch if optimistic update worked, but maybe good for consistency
    } catch (err) {
      console.error("Update failed", err);
      fetchSubscriptions(); // Revert on error
    }
  };

  const handleDelete = async (asset_id: string) => {
    if (!user) return;
    if (!confirm("Are you sure you want to stop tracking this market?")) return;

    try {
      await fetch(`${API_URL}/api/markets/${asset_id}?clerk_user_id=${user.id}`, {
        method: "DELETE",
      });
      setSubscriptions(prev => prev.filter(s => s.asset_id !== asset_id));
    } catch (err) {
      alert("Failed to delete");
    }
  };

  // Render Loading
  if (!isLoaded) return <div className="flex h-screen items-center justify-center">Loading...</div>;

  // Render Landing Page
  if (!isSignedIn) {
    return (
      <div className="flex h-screen flex-col items-center justify-center bg-gray-50 p-4">
        <div className="text-center max-w-md">
          <h1 className="text-4xl font-bold text-gray-900 mb-4">PolyTracking SaaS</h1>
          <p className="text-gray-600 mb-8">
            Track Polymarket whales, liquidity spikes, and price surges in real-time.
            Get instant alerts on Telegram.
          </p>
          <div className="bg-blue-600 text-white px-6 py-3 rounded-lg hover:bg-blue-700 transition">
            <SignInButton mode="modal" />
          </div>
        </div>
      </div>
    );
  }

  // Render Dashboard
  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-5xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="text-blue-600" />
            <span className="font-bold text-xl">PolyTracking</span>
          </div>
          <UserButton />
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8 space-y-8">

        {/* Section A: Telegram Connection */}
        <section className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Zap className="text-yellow-500" size={20} />
            Connect Telegram
          </h2>
          <div className="flex items-center justify-between bg-blue-50 p-4 rounded-lg">
            <div>
              <p className="text-sm text-blue-900 font-medium">Receive real-time alerts</p>
              <p className="text-xs text-blue-700">Link your Telegram account to get notified instantly.</p>
            </div>
            {telegramToken ? (
              <a
                href={`https://t.me/${BOT_USERNAME}?start=${telegramToken}`}
                target="_blank"
                rel="noopener noreferrer"
                className="bg-blue-600 text-white px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-700 transition"
              >
                Open Telegram Bot ↗
              </a>
            ) : (
              <button
                onClick={handleConnectTelegram}
                disabled={loading}
                className="bg-white border border-blue-200 text-blue-600 px-4 py-2 rounded-lg text-sm font-medium hover:bg-blue-50 transition"
              >
                {loading ? "Generating..." : "Connect Telegram"}
              </button>
            )}
          </div>
        </section>

        {/* Section B: Search & Track */}
        <section className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Search className="text-gray-500" size={20} />
            Add Market
          </h2>
          <div className="relative">
            <input
              type="text"
              placeholder="Search Polymarket events (e.g. 'Bitcoin', 'Election')..."
              className="w-full p-3 pl-10 bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
            <Search className="absolute left-3 top-3.5 text-gray-400" size={18} />
          </div>

          {searching && <div className="mt-4 text-center text-gray-400 text-sm">Searching...</div>}

          {searchResults.length > 0 && (
            <div className="mt-4 space-y-3 max-h-96 overflow-y-auto">
              {searchResults.map((result, idx) => (
                <div key={idx} className="flex items-start gap-4 p-3 hover:bg-gray-50 rounded-lg transition border border-transparent hover:border-gray-100">
                  <img src={result.image} alt="" className="w-10 h-10 rounded-full object-cover bg-gray-200" />
                  <div className="flex-1">
                    <h3 className="font-medium text-sm text-gray-900">{result.title}</h3>
                    <div className="mt-2 flex flex-wrap gap-2">
                      {result.options.map((opt) => (
                        <div key={opt.asset_id} className="flex items-center gap-2 bg-white border border-gray-200 rounded-full px-3 py-1 text-xs shadow-sm">
                          <span className="font-semibold text-gray-700">{opt.name}</span>
                          <span className="text-gray-500">${opt.current_price.toFixed(2)}</span>
                          <button
                            onClick={() => handleTrack(result.title, opt)}
                            className="ml-1 p-1 hover:bg-blue-50 text-blue-600 rounded-full transition"
                            title="Track this outcome"
                          >
                            <Plus size={14} />
                          </button>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Section C: Watchlist */}
        <section>
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2 px-1">
            <Bell className="text-gray-500" size={20} />
            Your Watchlist ({subscriptions.length})
          </h2>

          <div className="grid gap-4 md:grid-cols-1">
            {subscriptions.map((sub) => (
              <div key={sub.asset_id} className="bg-white rounded-xl p-5 shadow-sm border border-gray-100 flex flex-col md:flex-row md:items-center justify-between gap-4">

                {/* Market Info */}
                <div className="flex-1">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="bg-blue-100 text-blue-700 text-[10px] font-bold px-2 py-0.5 rounded uppercase tracking-wide">
                      {sub.target_outcome}
                    </span>
                    <span className="text-xs text-gray-400 font-mono">{sub.asset_id.slice(0, 8)}...</span>
                  </div>
                  <h3 className="font-semibold text-gray-900 leading-tight">{sub.title}</h3>
                </div>

                {/* Toggles */}
                <div className="flex flex-wrap items-center gap-2">
                  <Toggle
                    label="0.5%"
                    active={sub.notify_0_5pct}
                    onClick={() => handleUpdateSubscription(sub.asset_id, { notify_0_5pct: !sub.notify_0_5pct })}
                  />
                  <Toggle
                    label="2%"
                    active={sub.notify_2pct}
                    onClick={() => handleUpdateSubscription(sub.asset_id, { notify_2pct: !sub.notify_2pct })}
                  />
                  <Toggle
                    label="5%"
                    active={sub.notify_5pct}
                    onClick={() => handleUpdateSubscription(sub.asset_id, { notify_5pct: !sub.notify_5pct })}
                  />
                  <div className="w-px h-6 bg-gray-200 mx-1 hidden md:block"></div>
                  <Toggle
                    icon={<Fish size={14} />}
                    label="10k"
                    active={sub.notify_whale_10k}
                    onClick={() => handleUpdateSubscription(sub.asset_id, { notify_whale_10k: !sub.notify_whale_10k })}
                  />
                  <Toggle
                    icon={<Anchor size={14} />}
                    label="50k"
                    active={sub.notify_whale_50k}
                    onClick={() => handleUpdateSubscription(sub.asset_id, { notify_whale_50k: !sub.notify_whale_50k })}
                  />
                  <Toggle
                    icon={<Droplets size={14} />}
                    label="Liq"
                    active={sub.notify_liquidity}
                    onClick={() => handleUpdateSubscription(sub.asset_id, { notify_liquidity: !sub.notify_liquidity })}
                  />
                </div>

                {/* Delete */}
                <button
                  onClick={() => handleDelete(sub.asset_id)}
                  className="text-gray-400 hover:text-red-500 p-2 transition"
                >
                  <Trash2 size={18} />
                </button>
              </div>
            ))}

            {subscriptions.length === 0 && (
              <div className="text-center py-12 bg-white rounded-xl border border-dashed border-gray-300">
                <p className="text-gray-500">No markets tracked yet. Search above to add one!</p>
              </div>
            )}
          </div>
        </section>

      </main>
    </div>
  );
}

// Helper Component for Toggles
function Toggle({ label, icon, active, onClick }: { label: string, icon?: React.ReactNode, active: boolean, onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`
        flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium transition border
        ${active
          ? "bg-blue-600 text-white border-blue-600 shadow-sm"
          : "bg-white text-gray-600 border-gray-200 hover:bg-gray-50"
        }
      `}
    >
      {icon}
      {label}
    </button>
  );
}
