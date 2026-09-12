// JobAgent Copilot - UI Overlay Module
// Handles in-modal helper button injection and DOM modal observers

(function () {
  "use strict";

  window.JobAgent = window.JobAgent || {};

  function attachModalAutofillButton() {
    const getActiveFormContainer = window.JobAgent.getActiveFormContainer;
    if (!getActiveFormContainer) return;

    const container = getActiveFormContainer();
    if (!container || container === document) return;

    if (container.querySelector("#ja-modal-fill-btn") || document.getElementById("ja-modal-fill-btn")) return;

    const btn = document.createElement("button");
    btn.id = "ja-modal-fill-btn";
    btn.type = "button";
    btn.innerHTML = "✨ <b>JobAgent</b> Fill";
    btn.style.cssText = `
      position: absolute;
      top: 14px;
      right: 54px;
      z-index: 100000;
      background: linear-gradient(135deg, #2563eb, #1d4ed8);
      color: #ffffff;
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 9999px;
      padding: 6px 14px;
      font-size: 13px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4);
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s ease;
    `;
    btn.onmouseenter = () => {
      btn.style.transform = "translateY(-1px)";
      btn.style.boxShadow = "0 6px 18px rgba(37, 99, 235, 0.5)";
    };
    btn.onmouseleave = () => {
      btn.style.transform = "none";
      btn.style.boxShadow = "0 4px 14px rgba(37, 99, 235, 0.4)";
    };

    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      btn.innerHTML = "⏳ Filling...";
      btn.disabled = true;

      let profile = null;
      let resolvedGatewayUrl = "http://127.0.0.1:8765";
      try {
        if (typeof chrome !== "undefined" && chrome?.storage) {
          const [localData, syncData] = await Promise.all([
            chrome.storage.local.get(["jobagent_cached_profile"]),
            chrome.storage.sync.get({ gatewayUrl: "http://127.0.0.1:8765" }),
          ]);
          profile = localData?.jobagent_cached_profile || null;
          resolvedGatewayUrl = syncData?.gatewayUrl || resolvedGatewayUrl;
        }
      } catch (err) {}

      if (window.JobAgent.performAutofill) {
        window.JobAgent.performAutofill(
          {
            profile: profile,
            gatewayUrl: resolvedGatewayUrl,
          },
          (res) => {
            btn.disabled = false;
            if (res && res.filledCount > 0) {
              btn.innerHTML = `✓ Filled ${res.filledCount}`;
              btn.style.background = "#10b981";
              setTimeout(() => {
                btn.innerHTML = "✨ <b>JobAgent</b> Fill";
                btn.style.background = "linear-gradient(135deg, #2563eb, #1d4ed8)";
              }, 3000);
            } else {
              btn.innerHTML = "✨ <b>JobAgent</b> Fill";
            }
          }
        );
      }
    });

    if (window.getComputedStyle(container).position === "static") {
      container.style.position = "relative";
    }
    container.appendChild(btn);
  }

  function initModalObserver() {
    try {
      const modalObserver = new MutationObserver(() => {
        attachModalAutofillButton();
      });
      modalObserver.observe(document.body, { childList: true, subtree: true });
      attachModalAutofillButton();
    } catch (e) {}
  }

  window.JobAgent.attachModalAutofillButton = attachModalAutofillButton;
  window.JobAgent.initModalObserver = initModalObserver;
})();
