import { useEffect, useRef } from "react";
import L from "leaflet";

import { escapeHtml, gallons, miles, money } from "../format.js";

const TILES = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const CREDIT = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function pin(label, variant = "") {
  return L.divIcon({
    className: "",
    html: `<div class="pin ${variant}"><span>${escapeHtml(label)}</span></div>`,
    iconSize: [25, 25],
    iconAnchor: [12.5, 12.5],
    popupAnchor: [0, -15],
  });
}

function stopPopup(stop) {
  return (
    `<b>#${stop.sequence} ${escapeHtml(stop.name)}</b>` +
    `<span class="pop-price">${money(stop.price_per_gallon)} / gal</span>` +
    `<div class="pop-meta">${escapeHtml(stop.city)}, ${escapeHtml(stop.state)}<br>` +
    `mile ${miles(stop.distance_from_start_miles)} &middot; ${gallons(stop.gallons_purchased)} gal` +
    ` &middot; ${money(stop.cost_usd)}</div>`
  );
}

export default function RouteMap({ plan }) {
  const host = useRef(null);
  const map = useRef(null);
  const drawn = useRef([]);

  useEffect(() => {
    const instance = L.map(host.current, { zoomControl: false }).setView([39.5, -98.35], 4);
    L.control.zoom({ position: "bottomright" }).addTo(instance);
    L.tileLayer(TILES, { attribution: CREDIT, maxZoom: 19 }).addTo(instance);
    map.current = instance;
    return () => {
      instance.remove();
      map.current = null;
    };
  }, []);

  useEffect(() => {
    const instance = map.current;
    if (!instance) return;

    drawn.current.forEach((layer) => instance.removeLayer(layer));
    drawn.current = [];
    if (!plan) return;

    const path = plan.route.geometry.coordinates.map(([lon, lat]) => [lat, lon]);
    const route = L.layerGroup([
      L.polyline(path, { color: "#ffffff", weight: 7, opacity: 0.9 }),
      L.polyline(path, { color: "#1d4ed8", weight: 3, opacity: 0.95 }),
    ]).addTo(instance);

    const markers = L.layerGroup().addTo(instance);
    L.marker(path[0], { icon: pin("A", "t-origin") })
      .bindPopup(`<b>${escapeHtml(plan.start.label)}</b>`)
      .addTo(markers);
    L.marker(path[path.length - 1], { icon: pin("B", "t-destination") })
      .bindPopup(`<b>${escapeHtml(plan.finish.label)}</b>`)
      .addTo(markers);
    plan.fuel_stops.forEach((stop) => {
      L.marker([stop.latitude, stop.longitude], { icon: pin(String(stop.sequence)) })
        .bindPopup(stopPopup(stop))
        .addTo(markers);
    });

    drawn.current = [route, markers];
    instance.fitBounds(L.polyline(path).getBounds(), { padding: [30, 30] });
  }, [plan]);

  return <div className="map" ref={host} />;
}
