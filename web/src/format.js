export const money = (value) => `$${Number(value).toFixed(2)}`;

export const miles = (value) => Math.round(Number(value)).toLocaleString("en-US");

export const gallons = (value) => Number(value).toFixed(1);

// Station names and city labels come from the price file, so they are escaped rather than
// trusted when they go into Leaflet popups or table cells.
export const escapeHtml = (value) =>
  String(value).replace(
    /[&<>"']/g,
    (character) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]
  );
