import { NavLink, Route, Routes, Navigate, useLocation } from "react-router-dom";
import LiveDetectionPage from "./pages/LiveDetection.jsx";
import DashboardPage from "./pages/Dashboard.jsx";
import HistoryPage from "./pages/History.jsx";

const navItems = [
  { to: "/live", label: "Live Detection" },
  { to: "/history", label: "History" },
  { to: "/dashboard", label: "User Dashboard" },
];

function App() {
  const location = useLocation();

  return (
    <div className="min-h-screen bg-gradient-to-br from-midnight-900 via-midnight-800 to-midnight-900 text-slate-100">
      <header className="sticky top-0 z-40 border-b border-white/10 bg-slate-950/70 backdrop-blur">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 px-6 py-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-col">
            <span className="text-xs uppercase tracking-[0.3em] text-slate-400">Brand Pulse</span>
            <h1 className="text-2xl font-semibold text-white">Brand Protection Portal</h1>
            <p className="mt-1 text-sm text-slate-400">
              Monitor suspicious activity in real time and stay ahead of brand misuse.
            </p>
          </div>
          <nav className="flex flex-wrap gap-2">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) =>
                  `rounded-full px-5 py-2 text-sm font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-500 ` +
                  (isActive
                    ? "bg-accent-500 text-slate-950 shadow-card"
                    : "bg-white/5 text-slate-200 hover:bg-white/10")
                }
                end={item.to === "/dashboard"}
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl px-6 py-10">
        <Routes location={location}>
          <Route path="/" element={<Navigate to="/live/url" replace />} />
          <Route path="/live" element={<Navigate to="/live/url" replace />} />\n          <Route path="/live/:view?" element={<LiveDetectionPage />} />
          <Route path="/history" element={<HistoryPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;

