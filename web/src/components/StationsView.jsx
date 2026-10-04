import { useEffect, useState } from "react";

import { listStations } from "../api.js";
import { money } from "../format.js";

const EMPTY = { state: "", city: "", maxPrice: "" };

export default function StationsView() {
  const [filters, setFilters] = useState(EMPTY);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function load(next) {
    setBusy(true);
    setError("");
    try {
      setData(await listStations(next));
    } catch (problem) {
      setData(null);
      setError(problem.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load(EMPTY);
  }, []);

  const change = (key) => (event) => setFilters({ ...filters, [key]: event.target.value });

  return (
    <div className="wide">
      <form
        className="panel glass"
        onSubmit={(event) => {
          event.preventDefault();
          load(filters);
        }}
      >
        <span className="eyebrow">Filters</span>
        <div className="filters">
          <div className="field">
            <label htmlFor="state">State</label>
            <input id="state" value={filters.state} onChange={change("state")} placeholder="TX" />
          </div>
          <div className="field">
            <label htmlFor="city">City</label>
            <input id="city" value={filters.city} onChange={change("city")} placeholder="Amarillo" />
          </div>
          <div className="field">
            <label htmlFor="maxPrice">Max price</label>
            <input
              id="maxPrice"
              value={filters.maxPrice}
              onChange={change("maxPrice")}
              placeholder="3.00"
            />
          </div>
          <div className="field">
            <label htmlFor="search">&nbsp;</label>
            <button id="search" className="primary" type="submit" disabled={busy}>
              {busy ? "Loading\u2026" : "Search"}
            </button>
          </div>
        </div>
        {error && <p className="alert">{error}</p>}
      </form>

      <section className="panel glass scroll">
        {data && (
          <div className="section-label">
            Catalogue
            <span>
              {data.returned} of {data.count.toLocaleString("en-US")}
            </span>
          </div>
        )}
        <table>
          <thead>
            <tr>
              <th>Station</th>
              <th>Location</th>
              <th className="num">Price</th>
            </tr>
          </thead>
          <tbody>
            {(data?.results ?? []).map((station) => (
              <tr key={station.id}>
                <td>
                  <span className="stop-name">{station.name}</span>
                  <div className="stop-meta">{station.address}</div>
                </td>
                <td>
                  <span className="stop-meta">
                    {station.city}, {station.state}
                  </span>
                </td>
                <td className="num">
                  <span className="price">{money(station.price)}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
