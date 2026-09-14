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

  const jobStatusBadge = document.getElementById("job-status-badge");
  const jobCapturedView = document.getElementById("job-captured-view");
  const jobActiveTitle = document.getElementById("job-active-title");
  const jobActiveCompany = document.getElementById("job-active-company");
  const jobActiveMeta = document.getElementById("job-active-meta");
  const jobViewUrl = document.getElementById("job-view-url");
  const btnClearJob = document.getElementById("btn-clear-job");
  const jobCaptureActionView = document.getElementById("job-capture-action-view");
  const btnCaptureJob = document.getElementById("btn-capture-job");
  const btnOpenClFull = document.getElementById("btn-open-cl-full");

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

      // Tab was opened before extension was reloaded: inject all modules + content.js on the fly
      if (chrome.scripting && chrome.scripting.executeScript) {
        await chrome.scripting.executeScript({
          target: { tabId: tabId, allFrames: true },
          files: [
            "modules/job_session_manager.js",
            "modules/job_extractor.js",
            "modules/form_extractor.js",
            "modules/field_writer.js",
            "modules/document_uploader.js",
            "modules/local_fallback.js",
            "modules/ui_overlay.js",
            "content.js",
          ],
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
            resultBox.textContent = `✅ Archived! Job description saved to CRM database.`;
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

      // Probe all frames to find which one has visible form fields.
      // SmartRecruiters, Workday, and other SPAs often render the application
      // form inside a child iframe — chrome.tabs.sendMessage without frameId
      // sends to the top frame first, which has no fields and replies
      // "No fields detected" before the iframe can respond.
      let targetFrameId = 0; // default to main frame
      try {
        if (chrome.scripting && chrome.scripting.executeScript) {
          const probeResults = await chrome.scripting.executeScript({
            target: { tabId: activeTab.id, allFrames: true },
            func: () => {
              if (window.JobAgent && typeof window.JobAgent.extractFormSchema === "function") {
                try {
                  return window.JobAgent.extractFormSchema().schema.length;
                } catch (e) { return 0; }
              }
              return 0;
            },
          });
          // Pick the frame with the most fields (prefer child frames over top frame)
          const best = (probeResults || [])
            .filter((r) => r.result > 0)
            .sort((a, b) => b.result - a.result)[0];
          if (best) {
            targetFrameId = best.frameId;
            console.log(`[JobAgent Copilot] Autofill targeting frameId=${targetFrameId} (${best.result} fields found)`);
          } else {
            console.log("[JobAgent Copilot] No fields found in any frame — will try main frame anyway.");
          }
        }
      } catch (probeErr) {
        console.warn("[JobAgent Copilot] Frame probe error (proceeding with main frame):", probeErr);
      }

      // Send to the frame that has fields (or fall back to main frame)
      chrome.tabs.sendMessage(activeTab.id, payload, { frameId: targetFrameId }, (res) => {
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
          } else if (res.totalFields > 0) {
            resultBox.textContent = `ℹ️ Detected ${res.totalFields} fields (no profile matches; passwords skipped).`;
            resultBox.className = "result-box";
          } else {
            resultBox.textContent = `ℹ️ No form fields detected on this page/modal.`;
            resultBox.className = "result-box";
          }
        } else {
          resultBox.textContent = "Autofill signal sent to page & iframes.";
          resultBox.className = "result-box";
        }
      });
    });
  });


  // 4. Pinned Job Context Handlers
  async function renderJobContext() {
    const manager = (typeof JobSessionManager !== "undefined" ? JobSessionManager : window.JobSessionManager);
    if (!manager) return;
    let activeJob = null;
    try {
      activeJob = await manager.getActiveJob();
    } catch (e) {}

    if (activeJob && activeJob.jobTitle) {
      if (jobCapturedView) jobCapturedView.classList.remove("hidden");
      if (jobCaptureActionView) jobCaptureActionView.classList.add("hidden");
      if (jobActiveTitle) jobActiveTitle.textContent = activeJob.jobTitle;
      if (jobActiveCompany) jobActiveCompany.textContent = activeJob.company ? `@ ${activeJob.company}` : "";

      const minsAgo = Math.round((Date.now() - (activeJob.capturedTimestamp || Date.now())) / 60000);
      const timeStr = minsAgo < 1 ? "Just now" : (minsAgo < 60 ? `${minsAgo}m ago` : `${Math.round(minsAgo / 60)}h ago`);
      if (jobActiveMeta) {
        jobActiveMeta.textContent = `${activeJob.platform ? `[${activeJob.platform}] ` : ""}${timeStr}${activeJob.location ? ` • ${activeJob.location}` : ""}`;
      }
      if (jobViewUrl) {
        if (activeJob.jobUrl && activeJob.jobUrl.startsWith("http")) {
          jobViewUrl.href = activeJob.jobUrl;
          jobViewUrl.style.display = "inline";
        } else {
          jobViewUrl.style.display = "none";
        }
      }
      if (jobStatusBadge) {
        jobStatusBadge.className = "job-status-badge pinned";
        jobStatusBadge.textContent = "✓ Pinned";
      }
    } else {
      if (jobCapturedView) jobCapturedView.classList.add("hidden");
      if (jobCaptureActionView) jobCaptureActionView.classList.remove("hidden");
      if (jobStatusBadge) {
        jobStatusBadge.className = "job-status-badge";
        jobStatusBadge.textContent = "Ready to Pin";
      }
    }
  }

  if (btnCaptureJob) {
    btnCaptureJob.addEventListener("click", async () => {
      btnCaptureJob.disabled = true;
      btnCaptureJob.textContent = "⏳ Pinning Job Description...";

      try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (!tab || !tab.id) {
          btnCaptureJob.disabled = false;
          btnCaptureJob.textContent = "📌 Pin Job Description";
          return;
        }

        try {
          await chrome.scripting.executeScript({
            target: { tabId: tab.id },
            files: [
              "modules/job_session_manager.js",
              "modules/job_extractor.js",
              "content.js"
            ]
          });
        } catch (e) {}

        chrome.tabs.sendMessage(tab.id, { action: "extract_job_posting" }, async (resp) => {
          btnCaptureJob.disabled = false;
          btnCaptureJob.textContent = "📌 Pin Job Description";

          if (chrome.runtime.lastError || !resp || !resp.success || !resp.jobData) {
            resultBox.textContent = "Could not extract job description from current page.";
            resultBox.className = "result-box error";
            return;
          }

          const job = resp.jobData;
          const manager = (typeof JobSessionManager !== "undefined" ? JobSessionManager : window.JobSessionManager);
          if (manager) {
            await manager.saveActiveJob(job);
          }
          resultBox.textContent = `✓ Pinned: ${job.jobTitle} at ${job.company}`;
          resultBox.className = "result-box";
          await renderJobContext();
        });
      } catch (err) {
        btnCaptureJob.disabled = false;
        btnCaptureJob.textContent = "📌 Pin Job Description";
        resultBox.textContent = "Error pinning job: " + err.message;
        resultBox.className = "result-box error";
      }
    });
  }

  if (btnClearJob) {
    btnClearJob.addEventListener("click", async () => {
      const manager = (typeof JobSessionManager !== "undefined" ? JobSessionManager : window.JobSessionManager);
      if (manager) {
        await manager.clearActiveJob();
      }
      resultBox.textContent = "Unpinned active job description.";
      resultBox.className = "result-box";
      await renderJobContext();
    });
  }

  // 5. Open Cover Letter Studio
  if (btnOpenClFull) {
    btnOpenClFull.addEventListener("click", async () => {
      let originTabId = "";
      try {
        const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (activeTab && activeTab.id) {
          originTabId = activeTab.id;
        }
      } catch (e) {}

      const originParam = originTabId ? `?tabId=${originTabId}` : "";
      const targetUrl = chrome.runtime.getURL(`cover_letter_preview.html${originParam}`);
      chrome.tabs.create({ url: targetUrl });
    });
  }

  // 6. Open Dashboard (P1 fix: clean URL without query token; auth via loopback/headers)
  btnDashboard.addEventListener("click", () => {
    chrome.tabs.create({ url: `${gatewayUrl}/dashboard` });
  });

  // Render initial pinned job context on open
  await renderJobContext();
});
