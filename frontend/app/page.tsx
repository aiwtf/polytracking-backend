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
  Anchor,
  CheckCircle,
  X
} from "lucide-react";

// Use the URL provided by the user or fallback to localhost
// Use the URL provided by the user or fallback to localhost
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const BOT_USERNAME = "@PolytrackingBot";

// --- Types ---
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
  image_url?: string;
  notify_0_5pct: boolean;
  notify_2pct: boolean;
  notify_5pct: boolean;
  notify_whale_10k: boolean;
  notify_whale_50k: boolean;
  notify_liquidity: boolean;
  user?: {
    telegram_chat_id: string | null;
  };
}

interface TrackingConfig {
  notify_0_5pct: boolean;
  notify_2pct: boolean;
  notify_5pct: boolean;
  notify_whale_10k: boolean;
  notify_whale_50k: boolean;
  notify_liquidity: boolean;
}

const DEFAULT_CONFIG: TrackingConfig = {
  notify_0_5pct: false,
  notify_2pct: true, // Default
  notify_5pct: false,
  notify_whale_10k: false,
  notify_whale_50k: false,
  notify_liquidity: false,
};

export default function Dashboard() {
  const { user, isLoaded, isSignedIn } = useUser();

  // State
  const [telegramConnected, setTelegramConnected] = useState(false);
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(false);

  // Fetch Data
  const fetchData = useCallback(async () => {
    if (!user) return;
    try {
      // Fetch User Status
      const statusRes = await fetch(`${API_URL}/api/user/status?clerk_user_id=${user.id}`);
      if (statusRes.ok) {
        const statusData = await statusRes.json();
        setTelegramConnected(statusData.telegram_connected);
      }

      // Fetch Subscriptions
      const subRes = await fetch(`${API_URL}/api/subscriptions?clerk_user_id=${user.id}`);
      if (subRes.ok) {
        const data = await subRes.json();
        setSubscriptions(data);
      }
    } catch (err) {
      console.error("Failed to fetch data", err);
    }
  }, [user]);

  useEffect(() => {
    if (isSignedIn) {
      fetchData();
    } else {
      // Clear data if user signs out
      setTelegramConnected(false);
      setSubscriptions([]);
    }
  }, [isSignedIn, fetchData]);

  // Render Loading
  if (!isLoaded) return <div className="flex h-screen items-center justify-center">Loading...</div>;

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900 font-sans flex flex-col items-center">
      {/* Header */}
      <header className="w-full bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Activity className="text-blue-600" />
            <span className="font-bold text-xl tracking-tight">PolyTracking</span>
          </div>
          <div className="flex items-center gap-4">
            {!isSignedIn && (
              <SignInButton mode="modal">
                <button className="text-sm font-medium text-gray-700 hover:text-gray-900">Sign In</button>
              </SignInButton>
            )}
            <UserButton />
          </div>
        </div>
      </header>

      <main className="w-full max-w-3xl px-4 py-6 space-y-6 flex-1">

        {/* 1. Telegram Connection */}
        <TelegramSection userId={user?.id} connected={telegramConnected} onStatusChange={fetchData} />

        {/* 2. Market Search */}
        <SearchSection userId={user?.id} onSubscribe={fetchData} />

        {/* 3. Subscription List */}
        <SubscriptionList subscriptions={subscriptions} userId={user?.id} onUpdate={fetchData} />

      </main>
    </div>
  );
}

// --- Components ---

function TelegramSection({ userId, connected, onStatusChange }: { userId: string | undefined | null, connected: boolean, onStatusChange: () => void }) {
  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Polling for status change when token is present (user is connecting)
  useEffect(() => {
    if (!token || connected) return;

    const interval = setInterval(async () => {
      onStatusChange();
    }, 2000); // Poll every 2 seconds

    return () => clearInterval(interval);
  }, [token, connected, onStatusChange]);

  const handleConnect = async () => {
    if (!userId) {
      alert("Please sign in to connect Telegram.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/connect_telegram`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ clerk_user_id: userId }),
      });
      const data = await res.json();
      if (data.status === "success") {
        setToken(data.connection_token);
        window.open(`https://t.me/${BOT_USERNAME.replace('@', '')}?start=${data.connection_token}`, "_blank");
      }
    } catch (err) {
      alert("Failed to connect Telegram");
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    // Placeholder for disconnect logic if needed, or just UI for now as requested
    // For now, we don't have a disconnect endpoint, so maybe just show alert or do nothing
    // The user asked for UI layout.
    alert("Disconnect feature coming soon!");
  };

  return (
    <section className="bg-white rounded-xl p-6 shadow-sm border border-gray-100 flex items-center justify-between">
      <div>
        <h2 className="text-lg font-semibold text-gray-900">
          Telegram alerts
        </h2>
        <p className="text-xs text-gray-500 mt-0.5">
          Receive real-time notifications via <span className="text-blue-600">@polytrackingbot</span>
        </p>
      </div>

      {connected ? (
        <button
          onClick={handleDisconnect}
          className="bg-white text-gray-700 border border-gray-200 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 transition"
        >
          Disconnect
        </button>
      ) : (
        <button
          onClick={handleConnect}
          disabled={loading}
          className="bg-black text-white px-5 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-800 transition"
        >
          {loading ? "..." : "Connect"}
        </button>
      )}
    </section>
  );
}

function SearchSection({ userId, onSubscribe }: { userId: string | undefined | null, onSubscribe: () => void }) {
  const [query, setQuery] = useState("");
  const [debouncedQuery] = useDebounce(query, 500);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);
  const [selectedOption, setSelectedOption] = useState<{ title: string, name: string, asset_id: string } | null>(null);

  useEffect(() => {
    if (!debouncedQuery) {
      setResults([]);
      return;
    }
    setSearching(true);
    fetch(`${API_URL}/api/proxy/search?q=${encodeURIComponent(debouncedQuery)}`)
      .then(res => res.json())
      .then(data => setResults(data))
      .catch(err => console.error(err))
      .finally(() => setSearching(false));
  }, [debouncedQuery]);

  return (
    <section className="bg-white rounded-xl p-6 shadow-sm border border-gray-100">
      <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
        <Search className="text-gray-500" size={20} />
        Find Markets
      </h2>

      <div className="relative">
        <input
          type="text"
          placeholder="Search (e.g. 'Bitcoin', 'Election')..."
          className="w-full p-3 pl-10 bg-gray-50 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 transition"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Search className="absolute left-3 top-3.5 text-gray-400" size={18} />
      </div>

      {searching && <div className="mt-4 text-center text-gray-400 text-sm">Searching...</div>}

      <div className="mt-4 space-y-3">
        {results.map((result, idx) => (
          <div key={idx} className="flex items-center gap-4 p-3 hover:bg-gray-50 rounded-lg transition border border-transparent hover:border-gray-100">
            <img src={result.image} alt="" className="w-12 h-12 rounded-full object-cover bg-gray-200" />
            <div className="flex-1 min-w-0">
              <h3 className="font-medium text-gray-900 truncate">{result.title}</h3>
              <div className="mt-2 flex gap-2 overflow-x-auto pb-2 scrollbar-hide">
                {result.options.map((opt) => (
                  <button
                    key={opt.asset_id}
                    onClick={() => setSelectedOption({ title: result.title, name: opt.name, asset_id: opt.asset_id })}
                    className="px-3 py-1 rounded-md text-sm font-medium border border-gray-200 hover:border-blue-500 hover:text-blue-600 transition whitespace-nowrap flex-shrink-0"
                  >
                    {opt.name} <span className="text-gray-400 text-xs ml-1">${opt.current_price.toFixed(2)}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {selectedOption && (
        <TrackingModal
          option={selectedOption}
          userId={userId}
          onClose={() => setSelectedOption(null)}
          onSuccess={() => {
            setSelectedOption(null);
            setQuery("");
            onSubscribe();
          }}
        />
      )}
    </section>
  );
}

function TrackingModal({ option, userId, onClose, onSuccess }: { option: { title: string, name: string, asset_id: string }, userId: string | undefined | null, onClose: () => void, onSuccess: () => void }) {
  const [config, setConfig] = useState<TrackingConfig>(DEFAULT_CONFIG);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    if (!userId) {
      alert("Please sign in to track markets.");
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch(`${API_URL}/api/subscribe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          clerk_user_id: userId,
          asset_id: option.asset_id,
          title: option.title,
          target_outcome: option.name,
          ...config
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        const errMsg = errData.detail ? (typeof errData.detail === 'object' ? JSON.stringify(errData.detail) : errData.detail) : "Server returned " + res.status;
        throw new Error(errMsg);
      }

      onSuccess();
    } catch (err: any) {
      console.error("Track error:", err);
      alert(`Failed to track: ${err.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl max-w-sm w-full p-6 shadow-2xl animate-in fade-in zoom-in duration-200">
        <div className="flex justify-between items-start mb-4">
          <div>
            <h3 className="text-lg font-bold text-gray-900">Track Market</h3>
            <p className="text-sm text-gray-500 mt-1">{option.title}</p>
            <div className="mt-2 inline-block bg-blue-100 text-blue-700 text-xs font-bold px-2 py-0.5 rounded">
              {option.name}
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={20} />
          </button>
        </div>

        <div className="space-y-3 mb-6">
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Notify me when:</p>

          <Checkbox
            label="Price changes > 0.5%"
            checked={config.notify_0_5pct}
            onChange={(c) => setConfig(p => ({ ...p, notify_0_5pct: c }))}
          />
          <Checkbox
            label="Price changes > 2%"
            checked={config.notify_2pct}
            onChange={(c) => setConfig(p => ({ ...p, notify_2pct: c }))}
          />
          <Checkbox
            label="Price changes > 5%"
            checked={config.notify_5pct}
            onChange={(c) => setConfig(p => ({ ...p, notify_5pct: c }))}
          />
          <div className="h-px bg-gray-100 my-2"></div>
          <Checkbox
            label="Whale buys > $10k"
            checked={config.notify_whale_10k}
            onChange={(c) => setConfig(p => ({ ...p, notify_whale_10k: c }))}
          />
          <Checkbox
            label="Whale buys > $50k"
            checked={config.notify_whale_50k}
            onChange={(c) => setConfig(p => ({ ...p, notify_whale_50k: c }))}
          />
        </div>

        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="w-full bg-blue-600 text-white py-3 rounded-lg font-semibold hover:bg-blue-700 transition"
        >
          {submitting ? "Saving..." : "Start Tracking"}
        </button>
      </div>
    </div>
  );
}

function SubscriptionList({ subscriptions, userId, onUpdate }: { subscriptions: Subscription[], userId: string | undefined | null, onUpdate: () => void }) {
  // Local state for optimistic updates
  const [optimisticSubs, setOptimisticSubs] = useState(subscriptions);

  // Sync local state when props change (e.g. from polling)
  useEffect(() => {
    setOptimisticSubs(subscriptions);
  }, [subscriptions]);

  const handleToggle = async (id: number, field: keyof TrackingConfig, value: boolean) => {
    if (!userId) return;

    // 1. Optimistic Update with Mutual Exclusivity Logic
    setOptimisticSubs(prev => prev.map(sub => {
      if (sub.id !== id) return sub;

      const newSub = { ...sub, [field]: value };

      // Enforce mutual exclusivity for percentages
      if (value === true) {
        if (field === 'notify_0_5pct') {
          newSub.notify_2pct = false;
          newSub.notify_5pct = false;
        } else if (field === 'notify_2pct') {
          newSub.notify_0_5pct = false;
          newSub.notify_5pct = false;
        } else if (field === 'notify_5pct') {
          newSub.notify_0_5pct = false;
          newSub.notify_2pct = false;
        }

        // Enforce mutual exclusivity for whales
        if (field === 'notify_whale_10k') {
          newSub.notify_whale_50k = false;
        } else if (field === 'notify_whale_50k') {
          newSub.notify_whale_10k = false;
        }
      }

      return newSub;
    }));

    try {
      // 2. Call API in background (we send the single update, backend handles it? 
      // Actually, if we want to turn others OFF, we might need to send multiple updates or a full update.
      // The current PATCH endpoint updates specific fields. 
      // To ensure consistency, we should probably send the full state or multiple patches.
      // But for simplicity/speed, let's just send the one we clicked, 
      // AND if we turned others off, we need to send those too.
      // Ideally, the backend should handle this logic, but user asked for frontend logic change.
      // Let's send a PATCH with ALL relevant fields to be safe.

      const subToUpdate = optimisticSubs.find(s => s.id === id);
      if (!subToUpdate) return;

      // Calculate the new state again (same logic as above)
      const updates: any = { [field]: value };
      if (value === true) {
        if (field === 'notify_0_5pct') { updates.notify_2pct = false; updates.notify_5pct = false; }
        if (field === 'notify_2pct') { updates.notify_0_5pct = false; updates.notify_5pct = false; }
        if (field === 'notify_5pct') { updates.notify_0_5pct = false; updates.notify_2pct = false; }
        if (field === 'notify_whale_10k') { updates.notify_whale_50k = false; }
        if (field === 'notify_whale_50k') { updates.notify_whale_10k = false; }
      }

      await fetch(`${API_URL}/api/subscriptions/${id}?clerk_user_id=${userId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });

      onUpdate();
    } catch (err) {
      console.error(err);
      setOptimisticSubs(subscriptions);
      alert("Failed to update setting.");
    }
  };

  const handleDelete = async (id: number) => {
    if (!userId) return;
    if (!confirm("Stop tracking this market?")) return;

    // Optimistic delete
    setOptimisticSubs(prev => prev.filter(sub => sub.id !== id));

    try {
      const res = await fetch(`${API_URL}/api/subscriptions/${id}?clerk_user_id=${userId}`, {
        method: "DELETE",
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Server returned " + res.status);
      }

      onUpdate();
    } catch (err: any) {
      console.error("Delete error:", err);
      alert(`Failed to delete: ${err.message}`);
      // Revert
      setOptimisticSubs(subscriptions);
    }
  };

  const handleTestNotification = async (id: number) => {
    if (!userId) return;
    try {
      const res = await fetch(`${API_URL}/api/debug/test-notification`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ subscription_id: id, clerk_user_id: userId }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Server returned " + res.status);
      }

      alert("Test notification sent! Check your Telegram.");
    } catch (err: any) {
      console.error("Test notification error:", err);
      alert(`Failed to send test: ${err.message}`);
    }
  };

  return (
    <section>
      <h2 className="text-lg font-semibold mb-4 flex items-center gap-2 px-1">
        <Bell className="text-gray-500" size={20} />
        Your Watchlist ({optimisticSubs.length})
      </h2>

      <div className="grid gap-4">
        {optimisticSubs.map((sub) => (
          <div key={sub.id} className="bg-white rounded-xl p-4 shadow-sm border border-gray-100 flex flex-col md:flex-row md:items-center justify-between gap-4">

            <div className="flex items-center gap-4 flex-1">
              {/* Image Icon */}
              <div className="w-10 h-10 flex-shrink-0 rounded-full overflow-hidden bg-gray-100 border border-gray-200">
                {sub.image_url ? (
                  <img src={sub.image_url} alt="icon" className="w-full h-full object-cover" />
                ) : (
                  <div className="w-full h-full flex items-center justify-center text-gray-400">
                    <Activity size={20} />
                  </div>
                )}
              </div>

              <div className="min-w-0">
                {/* Title only, no badge, no asset ID */}
                <h3 className="font-semibold text-gray-900 leading-tight text-sm md:text-base line-clamp-2">
                  {sub.title}
                </h3>
                {/* Optional: Show target outcome if it's short, e.g. "Yes" */}
                {['Yes', 'No'].includes(sub.target_outcome) && (
                  <span className="text-xs text-gray-500 font-medium mt-0.5 block">
                    Outcome: {sub.target_outcome}
                  </span>
                )}
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2 self-start md:self-center">
              <Toggle label="0.5%" active={sub.notify_0_5pct} onClick={() => handleToggle(sub.id, 'notify_0_5pct', !sub.notify_0_5pct)} />
              <Toggle label="2%" active={sub.notify_2pct} onClick={() => handleToggle(sub.id, 'notify_2pct', !sub.notify_2pct)} />
              <Toggle label="5%" active={sub.notify_5pct} onClick={() => handleToggle(sub.id, 'notify_5pct', !sub.notify_5pct)} />
              <div className="w-px h-6 bg-gray-200 mx-1 hidden md:block"></div>
              <Toggle icon={<Fish size={14} />} label="10k" active={sub.notify_whale_10k} onClick={() => handleToggle(sub.id, 'notify_whale_10k', !sub.notify_whale_10k)} />
              <Toggle icon={<Anchor size={14} />} label="50k" active={sub.notify_whale_50k} onClick={() => handleToggle(sub.id, 'notify_whale_50k', !sub.notify_whale_50k)} />
            </div>


            <div className="flex items-center gap-2 self-end md:self-center">
              <button
                onClick={() => handleTestNotification(sub.id)}
                className="text-gray-300 hover:text-yellow-500 p-2 transition cursor-pointer"
                title="Send Test Notification"
              >
                <Zap size={18} />
              </button>
              <button
                onClick={() => handleDelete(sub.id)}
                className="text-gray-300 hover:text-red-500 p-2 transition cursor-pointer"
                title="Stop Tracking"
              >
                <Trash2 size={18} />
              </button>
            </div>
          </div>
        ))}

        {optimisticSubs.length === 0 && (
          <div className="text-center py-12 bg-white rounded-xl border border-dashed border-gray-300">
            <p className="text-gray-500">No markets tracked yet. Search above to add one!</p>
          </div>
        )}
      </div>
    </section>
  );
}

// --- Helpers ---

function Toggle({ label, icon, active, onClick }: { label: string, icon?: React.ReactNode, active: boolean, onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`
        flex items-center gap-1 px-3 py-1.5 rounded-md text-xs font-medium transition border cursor-pointer select-none
        ${active
          ? "bg-blue-600 text-white border-blue-600 shadow-sm"
          : "bg-white text-gray-500 border-gray-200 hover:bg-gray-50"
        }
      `}
    >
      {icon}
      {label}
    </button>
  );
}

function Checkbox({ label, checked, onChange }: { label: string, checked: boolean, onChange: (c: boolean) => void }) {
  return (
    <label className="flex items-center gap-3 cursor-pointer group">
      <div className={`
        w-5 h-5 rounded border flex items-center justify-center transition
        ${checked ? "bg-blue-600 border-blue-600" : "bg-white border-gray-300 group-hover:border-blue-400"}
      `}>
        {checked && <CheckCircle size={14} className="text-white" />}
      </div>
      <input
        type="checkbox"
        className="hidden"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      <span className="text-sm text-gray-700">{label}</span>
    </label>
  );
}
