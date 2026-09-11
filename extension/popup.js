const DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765";
let gatewayUrl = DEFAULT_GATEWAY_URL;
let cachedProfile = null;
let apiToken = "";

async function getGatewayUrl() {
  if (typeof chrome !== "undefined" && chrome.storage?.sync) {
    try {
      const data = await chrome.storage.sync.get({ gatewayUrl: DEFAULT_GATEWAY_URL });
      return data.gatewayUrl || DEFAULT_GATEWAY_URL;
    } catch (e) {
      return DEFAULT_GATEWAY_URL;
    }
  }
  return DEFAULT_GATEWAY_URL;
}

function getAuthHeaders(extra = {}) {
  const headers = { ...extra };
  if (apiToken) {
    headers["Authorization"] = `Bearer ${apiToken}`;
  }
  return headers;
}

document.addEventListener("DOMContentLoaded", async () => {
  gatewayUrl = await getGatewayUrl();
  const statusBadge = document.getElementById("gateway-status");
  const candName = document.getElementById("cand-name");
  const candRole = document.getElementById("cand-role");
  const candInitials = document.getElementById("cand-initials");
  const btnArchive = document.getElementById("btn-archive");
  const btnAutofill = document.getElementById("btn-autofill");
  const btnDashboard = document.getElementById("btn-dashboard");
  const resultBox = document.getElementById("archive-result");

  const tokenCard = document.getElementById("token-card");
  const tokenInput = document.getElementById("token-input");
  const btnSaveToken = document.getElementById("btn-save-token");

  async function getStoredToken() {
    if (typeof chrome !== "undefined" && chrome?.storage?.local) {
      const data = await chrome.storage.local.get(["jobagent_token"]);
      return data?.jobagent_token || "";
    }
    return localStorage.getItem("jobagent_token") || "";
  }

  async function saveStoredToken(token) {
    if (typeof chrome !== "undefined" && chrome?.storage?.local) {
      await chrome.storage.local.set({ jobagent_token: token });
    }
    localStorage.setItem("jobagent_token", token);
  }

  async function getStoredProfile() {
    if (typeof chrome !== "undefined" && chrome?.storage?.local) {
      const data = await chrome.storage.local.get(["jobagent_cached_profile"]);
      return data?.jobagent_cached_profile || null;
    }
    try {
      return JSON.parse(localStorage.getItem("jobagent_cached_profile") || "null");
    } catch (e) {
      return null;
    }
  }

  async function saveStoredProfile(profile) {
    if (!profile) return;
    if (typeof chrome !== "undefined" && chrome?.storage?.local) {
      await chrome.storage.local.set({ jobagent_cached_profile: profile });
    }
    try {
      localStorage.setItem("jobagent_cached_profile", JSON.stringify(profile));
    } catch (e) {}
  }

  function displayProfile(profile, isOnline) {
    if (!profile) return;
    const name = profile?.personal?.fullName || "Candidate";
    candName.textContent = name;
    candRole.textContent = isOnline
      ? (profile?.preferences?.targetRoles?.[0] || "Backend Connected")
      : "Offline (Local Profile Active)";
    
    const parts = name.split(" ");
    const initials = parts.map(p => p[0]).join("").toUpperCase().slice(0, 2);
    candInitials.textContent = initials || "JA";
  }

  apiToken = await getStoredToken();
  cachedProfile = await getStoredProfile();
  if (cachedProfile) {
    displayProfile(cachedProfile, false);
  }

  // Auto-pair with local backend on loopback if token is missing
  async function ensureToken() {
    if (!apiToken) {
      try {
        const pairRes = await fetch(`${gatewayUrl}/api/v1/auth/pair`, { signal: AbortSignal.timeout(1500) });
        if (pairRes.ok) {
          const pairData = await pairRes.json();
          if (pairData?.token) {
            apiToken = pairData.token;
            await saveStoredToken(apiToken);
            console.log("[JobAgent Copilot] Auto-paired with local backend token.");
          }
        }
      } catch (e) {
        console.warn("[JobAgent Copilot] Auto-pair probe skipped:", e);
      }
    }
  }

  async function fetchProfile() {
    await ensureToken();
    try {
      const profRes = await fetch(`${gatewayUrl}/api/v1/profile`, {
        headers: getAuthHeaders(),
      });
      if (profRes.ok) {
        if (tokenCard) tokenCard.classList.add("hidden");
        cachedProfile = await profRes.json();
        await saveStoredProfile(cachedProfile);
        displayProfile(cachedProfile, true);
        return;
      }
      
      // If 401, re-attempt loopback auto-pairing once (in case server generated new token)
      if (profRes.status === 401) {
        try {
          const pairRes = await fetch(`${gatewayUrl}/api/v1/auth/pair`, { signal: AbortSignal.timeout(1500) });
          if (pairRes.ok) {
            const pairData = await pairRes.json();
            if (pairData?.token) {
              apiToken = pairData.token;
              await saveStoredToken(apiToken);
              const retryRes = await fetch(`${gatewayUrl}/api/v1/profile`, { headers: getAuthHeaders() });
              if (retryRes.ok) {
                if (tokenCard) tokenCard.classList.add("hidden");
                cachedProfile = await retryRes.json();
                await saveStoredProfile(cachedProfile);
                displayProfile(cachedProfile, true);
                return;
              }
            }
          }
        } catch (e) {}

        if (tokenCard) tokenCard.classList.remove("hidden");
        candName.textContent = "Auth Token Required";
        candRole.textContent = "Pair token in settings below";
        candInitials.textContent = "🔒";
      }
    } catch (e) {
      console.warn("[JobAgent Copilot] Profile fetch warning:", e);
    }
  }

  if (btnSaveToken) {
    btnSaveToken.addEventListener("click", async () => {
      const val = tokenInput.value.trim();
      if (val) {
        apiToken = val;
        await saveStoredToken(val);
        await fetchProfile();
      }
    });
  }

  // 1. Check Gateway connection and sync candidate profile
  let isGatewayOnline = false;
  try {
    const healthRes = await fetch(`${gatewayUrl}/health`, { signal: AbortSignal.timeout(2000) });
    if (healthRes.ok) {
      isGatewayOnline = true;
      statusBadge.textContent = "Gateway Online";
      statusBadge.className = "status-badge connected";
      await fetchProfile();
    } else {
      throw new Error("Gateway non-200");
    }
  } catch (err) {
    isGatewayOnline = false;
    statusBadge.textContent = "Offline";
    statusBadge.className = "status-badge disconnected";
    if (!cachedProfile) {
      candName.textContent = "JobAgent Offline";
      candRole.textContent = "Start: python run_agent.py --server";
      candInitials.textContent = "!";
    } else {
      displayProfile(cachedProfile, false);
    }
  }

  async function ensureContentScriptInjected(tabId) {
    try {
      const ping = await new Promise((resolve) => {
        chrome.tabs.sendMessage(tabId, { action: "ping" }, (res) => {
          if (chrome.runtime.lastError || !res) resolve(false);
          else resolve(true);
        });
      });
      if (ping) return true;

      // Tab was opened before extension was reloaded: inject content.js on the fly
      if (chrome.scripting && chrome.scripting.executeScript) {
        await chrome.scripting.executeScript({
          target: { tabId: tabId, allFrames: true },
          files: ["content.js"],
        });
        await new Promise((r) => setTimeout(r, 150));
        return true;
      }
    } catch (e) {
      console.warn("[JobAgent Copilot] Dynamic injection error:", e);
    }
    return false;
  }

  // 2. 1-Click Archive Button
  btnArchive.addEventListener("click", async () => {
    resultBox.classList.remove("hidden");
    if (!isGatewayOnline) {
      resultBox.textContent = "⚠️ JobAgent server is offline. Run 'python run_agent.py --server' to archive.";
      resultBox.className = "result-box error";
      console.warn("[JobAgent Copilot] Archiving unavailable while backend is offline.");
      return;
    }

    btnArchive.disabled = true;
    btnArchive.textContent = "Archiving...";
    resultBox.textContent = "Capturing page and sending to backend...";
    resultBox.className = "result-box";

    chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
      const activeTab = tabs[0];
      if (!activeTab?.id) {
        btnArchive.disabled = false;
        btnArchive.textContent = "1-Click Archive Posting";
        resultBox.textContent = "No active tab found.";
        resultBox.className = "result-box error";
        return;
      }

      await ensureContentScriptInjected(activeTab.id);

      chrome.tabs.sendMessage(activeTab.id, { action: "extract_page_content" }, async (response) => {
        if (!response) {
          resultBox.textContent = "Could not extract page (protected browser tab).";
          resultBox.className = "result-box error";
          btnArchive.disabled = false;
          btnArchive.textContent = "1-Click Archive Posting";
          return;
        }

        try {
          const archiveRes = await fetch(`${gatewayUrl}/api/v1/archive`, {
            method: "POST",
            headers: getAuthHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({
              url: activeTab.url,
              company: response.company || "Company",
              role: response.title || activeTab.title,
              html: response.html,
            }),
          });

          if (archiveRes.ok) {
            resultBox.textContent = `Archived! Markdown & visual PDF snapshot saved.`;
            resultBox.className = "result-box";
          } else {
            resultBox.textContent = "Failed to archive posting (backend error).";
            resultBox.className = "result-box error";
          }
        } catch (e) {
          resultBox.textContent = "Error connecting to JobAgent backend.";
          resultBox.className = "result-box error";
        } finally {
          btnArchive.disabled = false;
          btnArchive.textContent = "1-Click Archive Posting";
        }
      });
    });
  });

  // 3. Auto-Fill Current Form
  btnAutofill.addEventListener("click", async () => {
    resultBox.classList.remove("hidden");
    resultBox.className = "result-box";

    if (!cachedProfile) {
      cachedProfile = await getStoredProfile();
    }

    // If server is offline and we have no cached profile, explain clearly to the user
    if (!cachedProfile && !isGatewayOnline) {
      resultBox.textContent = "⚠️ JobAgent server is offline. Please run 'python run_agent.py --server' in your terminal.";
      resultBox.className = "result-box error";
      console.warn("[JobAgent Copilot] Cannot autofill: Backend server is offline (http://127.0.0.1:8765) and no local profile was cached.");
      return;
    }

    if (!isGatewayOnline) {
      resultBox.textContent = "⚡ Backend offline: using local candidate profile to autofill...";
    } else {
      resultBox.textContent = "🧠 Reasoning over form fields with JobAgent...";
    }

    btnAutofill.disabled = true;
    btnAutofill.textContent = "Filling...";

    chrome.tabs.query({ active: true, currentWindow: true }, async (tabs) => {
      const activeTab = tabs[0];
      if (!activeTab?.id) {
        btnAutofill.disabled = false;
        btnAutofill.textContent = "Auto-Fill Current Form";
        resultBox.textContent = "No active tab detected.";
        resultBox.className = "result-box error";
        return;
      }

      await ensureContentScriptInjected(activeTab.id);

      // Fetch document bundle (CV, Cover Letter, Reference) with extension privileges
      let docBundle = null;
      if (isGatewayOnline) {
        try {
          const docRes = await fetch(`${gatewayUrl}/api/v1/documents/bundle`, {
            headers: getAuthHeaders(),
            signal: AbortSignal.timeout(3000),
          });
          if (docRes.ok) {
            docBundle = await docRes.json();
            console.log("[JobAgent Copilot] Document bundle loaded:", Object.keys(docBundle));
          }
        } catch (e) {
          console.warn("[JobAgent Copilot] Document bundle fetch note:", e);
        }
      }

      const payload = {
        action: "autofill_form",
        profile: cachedProfile,
        documents: docBundle,
        gatewayUrl: isGatewayOnline ? gatewayUrl : "",
      };

      // Runtime messaging (chrome.tabs.sendMessage) reaches content scripts in ALL
      // frames of the tab — no window-level broadcast needed (would expose the
      // payload to any third-party iframe on the page).


      // Send standard runtime message to active tab
      chrome.tabs.sendMessage(activeTab.id, payload, (res) => {
        btnAutofill.disabled = false;
        btnAutofill.textContent = "Auto-Fill Current Form";

        if (chrome.runtime.lastError) {
          console.warn("[JobAgent Copilot] Tab communication note:", chrome.runtime.lastError.message);
          resultBox.textContent = "Please refresh the target page once to attach JobAgent.";
          resultBox.className = "result-box error";
          return;
        }

        if (res && res.filledCount !== undefined) {
          if (res.filledCount > 0) {
            resultBox.textContent = `✅ Filled ${res.filledCount} field${res.filledCount > 1 ? "s" : ""} (${res.method})!`;
            resultBox.className = "result-box";
          } else {
            resultBox.textContent = `ℹ️ Detected ${res.totalFields || 0} fields (no profile matches; passwords skipped).`;
            resultBox.className = "result-box";
          }
        } else {
          resultBox.textContent = "Autofill signal sent to page & iframes.";
          resultBox.className = "result-box";
        }
      });
    });
  });

  // Message Bridge: Proxy form reasoning requests from content script to bypass page mixed-content restrictions
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (msg.action === "request_gateway_reason") {
      fetch(`${gatewayUrl}/api/v1/form/reason`, {
        method: "POST",
        headers: getAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(msg.payload),
      })
        .then((r) => {
          if (!r.ok) throw new Error(`Gateway returned HTTP ${r.status}`);
          return r.json();
        })
        .then((data) => sendResponse({ ok: true, data }))
        .catch((err) => sendResponse({ ok: false, error: err.message }));
      return true; // async reply
    }
  });

  // 4. Open Dashboard (P1 fix: clean URL without query token; auth via loopback/headers)
  btnDashboard.addEventListener("click", () => {
    chrome.tabs.create({ url: `${gatewayUrl}/dashboard` });
  });
});
