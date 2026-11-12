/* UrBG Remover - login page */
(function () {
  "use strict";

  const form = document.getElementById("login-form");
  const button = document.getElementById("login-button");
  const label = document.getElementById("login-label");
  const errorBox = document.getElementById("login-error");

  function showError(message) {
    errorBox.textContent = message;
    errorBox.classList.add("show");
  }

  function clearError() {
    errorBox.textContent = "";
    errorBox.classList.remove("show");
  }

  function setBusy(busy) {
    button.disabled = busy;
    label.innerHTML = busy
      ? '<span class="spinner"></span> Signing in…'
      : "Sign in";
  }

  function nextTarget() {
    const params = new URLSearchParams(window.location.search);
    const next = params.get("next");
    if (next && next.startsWith("/") && !next.startsWith("//")) {
      return next;
    }
    return "/";
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    clearError();

    const username = document.getElementById("username").value.trim();
    const password = document.getElementById("password").value;

    if (!username || !password) {
      showError("Enter both your username and password.");
      return;
    }

    setBusy(true);
    try {
      const response = await fetch("/admin/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ username: username, password: password }),
      });

      let payload = {};
      try {
        payload = await response.json();
      } catch (_) {
        payload = {};
      }

      if (!response.ok) {
        const message =
          (payload.error && payload.error.message) ||
          "Sign in failed. Please check your credentials.";
        showError(message);
        setBusy(false);
        return;
      }

      window.location.href = nextTarget();
    } catch (err) {
      showError("Could not reach the server. Please try again.");
      setBusy(false);
    }
  });
})();
