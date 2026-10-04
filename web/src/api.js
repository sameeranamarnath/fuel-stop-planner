const BASE = (import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export const API_BASE = BASE;

async function request(path, options) {
  const response = await fetch(`${BASE}${path}`, options);
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new Error(body?.error?.detail || `Request failed (${response.status})`);
  }
  return body;
}

export function getHealth() {
  return request("/api/v1/health/");
}

export function planRoute(start, finish) {
  return request("/api/v1/fuel-plan/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ start, finish }),
  });
}

export function listStations({ state = "", city = "", maxPrice = "", limit = 100 } = {}) {
  const query = new URLSearchParams({ limit });
  if (state) query.set("state", state);
  if (city) query.set("city", city);
  if (maxPrice) query.set("max_price", maxPrice);
  return request(`/api/v1/stations/?${query}`);
}
