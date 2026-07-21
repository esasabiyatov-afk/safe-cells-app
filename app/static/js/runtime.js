"use strict";

(() => {
  const body = document.body;
  if (body.dataset.runtimeEnabled !== "true") return;

  const token = body.dataset.privateToken;
  const heartbeatUrl = body.dataset.runtimeHeartbeatUrl;
  const disconnectUrl = body.dataset.runtimeDisconnectUrl;
  const shutdownUrl = body.dataset.runtimeShutdownUrl;
  if (!token || !heartbeatUrl || !disconnectUrl || !shutdownUrl) return;

  function createTabId() {
    const bytes = new Uint8Array(18);
    window.crypto.getRandomValues(bytes);
    return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  }

  const tabId = createTabId();
  let exiting = false;

  function requestOptions({keepalive = false} = {}) {
    return {
      method: "POST",
      cache: "no-store",
      keepalive,
      headers: {
        "Content-Type": "application/json",
        "X-Safe-Cells-Token": token,
      },
      body: JSON.stringify({tab_id: tabId}),
    };
  }

  async function heartbeat() {
    if (exiting) return;
    try {
      await fetch(heartbeatUrl, requestOptions());
    } catch (_error) {
      // Ordinary data requests display connectivity errors. A lifecycle pulse
      // must never cover the screen or expose technical details.
    }
  }

  function disconnect() {
    if (exiting) return;
    const beaconPayload = new Blob(
      [JSON.stringify({tab_id: tabId, token})],
      {type: "application/json"},
    );
    if (navigator.sendBeacon(disconnectUrl, beaconPayload)) return;
    fetch(disconnectUrl, requestOptions({keepalive: true})).catch(() => {});
  }

  function showClosedScreen() {
    const panel = document.createElement("section");
    panel.className = "runtime-closed-panel";
    const title = document.createElement("h1");
    title.textContent = "Приложение закрыто";
    const note = document.createElement("p");
    note.textContent = "Эту вкладку можно закрыть. Для новой работы снова откройте ярлык «Сейфовые ячейки».";
    panel.append(title, note);
    body.className = "runtime-closed-body";
    body.replaceChildren(panel);
  }

  async function exitApplication(button) {
    if (exiting) return;
    if (!window.confirm("Закрыть приложение на этом компьютере? Несохранённые поля формы будут потеряны.")) return;
    exiting = true;
    button.disabled = true;
    try {
      const response = await fetch(shutdownUrl, {
        method: "POST",
        cache: "no-store",
        headers: {"X-Safe-Cells-Token": token},
      });
      if (!response.ok) throw new Error("shutdown rejected");
      showClosedScreen();
    } catch (_error) {
      exiting = false;
      button.disabled = false;
      window.alert("Не удалось закрыть приложение. Закройте все его вкладки браузера или обратитесь к администратору.");
    }
  }

  document.querySelectorAll("[data-runtime-exit]").forEach((button) => {
    button.addEventListener("click", () => exitApplication(button));
  });
  window.addEventListener("pagehide", disconnect);
  window.addEventListener("pageshow", heartbeat);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) heartbeat();
  });

  heartbeat();
  window.setInterval(heartbeat, 10_000);
})();
