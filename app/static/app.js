const form = document.getElementById("form");
const result = document.getElementById("result");
const geoBtn = document.getElementById("geo");
const geoStatus = document.getElementById("geo-status");
const latEl = document.getElementById("lat");
const lonEl = document.getElementById("lon");
const placeEl = document.getElementById("place");

// Default the date/time inputs to "now" for convenience.
const now = new Date();
const pad = (n) => String(n).padStart(2, "0");
document.getElementById("date").value =
  `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
document.getElementById("time").value = `${pad(now.getHours())}:${pad(now.getMinutes())}`;

// Typing a place name invalidates any stored geolocation coordinates.
placeEl.addEventListener("input", () => {
  latEl.value = "";
  lonEl.value = "";
});

geoBtn.addEventListener("click", () => {
  if (!navigator.geolocation) {
    // Also the case on insecure (http://) origins, where browsers disable it.
    geoStatus.textContent =
      "Your browser won't share location here — type a place name instead.";
    return;
  }
  geoStatus.textContent = "Locating…";
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      latEl.value = pos.coords.latitude.toFixed(5);
      lonEl.value = pos.coords.longitude.toFixed(5);
      placeEl.value = `My location (${latEl.value}, ${lonEl.value})`;
      geoStatus.textContent = "Using your current location.";
    },
    (err) => {
      const messages = {
        1: "Location permission was blocked — allow it in your browser, or type a place name.",
        2: "Your location isn't available right now — type a place name instead.",
        3: "Locating took too long — try again, or type a place name.",
      };
      geoStatus.textContent =
        messages[err.code] || "Couldn't get your location — type a place name instead.";
    }
  );
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  result.innerHTML = '<p class="loading">Charting the heavens…</p>';
  const data = new FormData(form);
  // Don't send the synthetic "My location (...)" label as a place name.
  if (latEl.value && lonEl.value) data.set("place", "");
  try {
    const resp = await fetch("/calculate", { method: "POST", body: data });
    // The server returns a friendly HTML fragment on handled errors (status
    // 200). Any other status is unexpected — show our own message rather than
    // dumping a raw error body into the page.
    if (!resp.ok) throw new Error(`status ${resp.status}`);
    result.innerHTML = await resp.text();
  } catch (err) {
    result.innerHTML =
      '<div class="notice">⚠️ Couldn\'t reach the server — check your connection and try again.</div>';
  }
});
