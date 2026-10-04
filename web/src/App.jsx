import { useEffect, useState } from "react";

import { getHealth } from "./api.js";
import PlannerView from "./components/PlannerView.jsx";
import StationsView from "./components/StationsView.jsx";

const TABS = [
  ["plan", "Plan"],
  ["stations", "Stations"],
];

function Brand() {
  return (
    <span className="brand">
      <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
        <rect x="1" y="1" width="28" height="28" rx="9" fill="#0a0f1a" />
        <path
          d="M8.5 21.5c4.5 0 4.5-13 9-13"
          fill="none"
          stroke="#ffffff"
          strokeWidth="1.7"
          strokeLinecap="round"
        />
        <circle cx="8.5" cy="21.5" r="2.1" fill="#15803d" />
        <circle cx="17.5" cy="8.5" r="2.1" fill="#b45309" />
      </svg>
      <span className="wordmark">
        <b>Spotter</b>
        <span>Fuel Route Planner</span>
      </span>
    </span>
  );
}

export default function App() {
  const [tab, setTab] = useState("plan");
  const [vehicle, setVehicle] = useState(null);

  // The vehicle assumptions come from the API rather than being repeated in the client.
  useEffect(() => {
    getHealth()
      .then((health) => setVehicle(health.vehicle))
      .catch(() => setVehicle(null));
  }, []);

  return (
    <div className="app">
      <header className="topbar glass">
        <Brand />
        <nav className="tabs">
          {TABS.map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={id === tab ? "tab active" : "tab"}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>
        {vehicle && (
          <span className="specs">
            <span className="chip">{Math.round(vehicle.max_range_miles)} MI RANGE</span>
            <span className="chip">{vehicle.mpg} MPG</span>
            <span className="chip">{Math.round(vehicle.tank_capacity_gallons)} GAL TANK</span>
          </span>
        )}
      </header>

      <main className="shell">{tab === "plan" ? <PlannerView /> : <StationsView />}</main>
    </div>
  );
}
