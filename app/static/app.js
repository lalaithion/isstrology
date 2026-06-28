const form = document.getElementById("form");
const result = document.getElementById("result");
const picker = document.getElementById("picker");
const resultsView = document.getElementById("results-view");
const backBtn = document.getElementById("back");
const geoBtn = document.getElementById("geo");
const geoStatus = document.getElementById("geo-status");
const latEl = document.getElementById("lat");
const lonEl = document.getElementById("lon");
const placeEl = document.getElementById("place");

// Two views: the picker, and a results "page" that hides it. Back returns.
function showResults() {
  picker.hidden = true;
  resultsView.hidden = false;
  window.scrollTo(0, 0);
}
function showPicker() {
  resultsView.hidden = true;
  picker.hidden = false;
  result.innerHTML = "";
  window.scrollTo(0, 0);
}
backBtn.addEventListener("click", showPicker);

// Default the date/time inputs to "now" for convenience.
const now = new Date();
const pad = (n) => String(n).padStart(2, "0");
document.getElementById("month").value = String(now.getMonth() + 1);
document.getElementById("day").value = String(now.getDate());
document.getElementById("year").value = String(now.getFullYear());
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
      "Your browser can't share your location, please enter a place name instead.";
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
        1: "Location permission was blocked. Either change your browser settings to allow it, or enter a place name instead.",
        2: "Your location isn't available right now, please enter a place name instead.",
        3: "Locating took longer than 10 seconds. Please try again or enter a place name.",
      };
      geoStatus.textContent =
        messages[err.code] || "Couldn't get your location. Please enter a place name instead.";
    },
    { timeout: 10000 } // give up after 10s -> error code 3
  );
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  result.innerHTML = '<p class="loading">Charting the heavens…</p>';
  showResults();
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
      '<div class="notice">⚠️ Couldn\'t reach the server. Check your connection or firewall.</div>';
  }
});
