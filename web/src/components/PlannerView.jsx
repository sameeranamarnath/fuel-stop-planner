import { useState } from "react";

import { planRoute } from "../api.js";
import { gallons, miles, money } from "../format.js";
import RouteMap from "./RouteMap.jsx";

export default function PlannerView() {
  const [start, setStart] = useState("New York, NY");
  const [finish, setFinish] = useState("Los Angeles, CA");
  const [plan, setPlan] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setPlan(await planRoute(start.trim(), finish.trim()));
    } catch (problem) {
      setPlan(null);
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  const stops = plan?.fuel_stops ?? [];

  return (
    <div className="planner">
      <div className="rail">
        <form className="panel glass" onSubmit={submit}>
          <span className="eyebrow">Route</span>

          <div className="field">
            <label htmlFor="start">Origin</label>
            <input
              id="start"
              value={start}
              onChange={(event) => setStart(event.target.value)}
              placeholder="City, ST"
              autoComplete="off"
            />
          </div>

          <div className="field">
            <label htmlFor="finish">Destination</label>
            <input
              id="finish"
              value={finish}
              onChange={(event) => setFinish(event.target.value)}
              placeholder="City, ST"
              autoComplete="off"
            />
          </div>

          <div className="actions">
            <button className="primary" type="submit" disabled={busy}>
              {busy ? "Planning\u2026" : "Plan route"}
            </button>
          </div>

          {error && <p className="alert">{error}</p>}
        </form>

        {plan && (
          <section className="panel glass">
            <span className="eyebrow">Summary</span>
            <dl className="kpis">
              <div className="kpi headline">
                <dt>Total fuel cost</dt>
                <dd>{money(plan.summary.total_fuel_cost_usd)}</dd>
              </div>
              <div className="kpi">
                <dt>Distance</dt>
                <dd>
                  {miles(plan.summary.total_distance_miles)}
                  <small>mi</small>
                </dd>
              </div>
              <div className="kpi">
                <dt>Fuel stops</dt>
                <dd>{plan.summary.number_of_fuel_stops}</dd>
              </div>
              <div className="kpi">
                <dt>Gallons</dt>
                <dd>
                  {gallons(plan.summary.total_gallons_purchased)}
                  <small>gal</small>
                </dd>
              </div>
              <div className="kpi">
                <dt>Average price</dt>
                <dd>
                  {money(plan.summary.average_price_per_gallon)}
                  <small>/gal</small>
                </dd>
              </div>
            </dl>
          </section>
        )}

        {plan && (
          <section className="panel glass">
            <div className="section-label">
              Fuel stops
              <span>{plan.elapsed_ms.toFixed(0)} ms</span>
            </div>
            {stops.length ? (
              <table>
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Station</th>
                    <th className="num">Price</th>
                    <th className="num">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {stops.map((stop) => (
                    <tr key={stop.sequence}>
                      <td>
                        <span className="seq">{stop.sequence}</span>
                      </td>
                      <td>
                        <span className="stop-name">{stop.name}</span>
                        <div className="stop-meta">
                          {stop.city}, {stop.state} &middot; mi{" "}
                          {miles(stop.distance_from_start_miles)}
                        </div>
                      </td>
                      <td className="num">
                        <span className="price">{money(stop.price_per_gallon)}</span>
                        <div className="sub">{gallons(stop.gallons_purchased)} gal</div>
                      </td>
                      <td className="num">
                        <span className="price">{money(stop.cost_usd)}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="note">No refuelling needed &mdash; the initial tank covers this trip.</p>
            )}
          </section>
        )}
      </div>

      <RouteMap plan={plan} />
    </div>
  );
}
