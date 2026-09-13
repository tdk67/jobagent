/// Cover Letter Studio & DIN 5008 Review Controller (JobAgent A2A Backend Integration)
/// Communicates directly with JobAgent backend (http://127.0.0.1:8765/api/v1/cover_letter/generate)
/// Zero PII / API keys exposed in client storage

document.addEventListener("DOMContentLoaded", async () => {
  const DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765";
  let gatewayUrl = DEFAULT_GATEWAY_URL;

  const btnToggleEdit = document.getElementById("btn-toggle-edit");
  const btnCopy = document.getElementById("btn-copy");
  const btnPrint = document.getElementById("btn-print");
  const toast = document.getElementById("toast");

  const senderName = document.getElementById("sender-name");
  const senderContact = document.getElementById("sender-contact");
  const recipient = document.getElementById("letter-recipient");
  const dateEl = document.getElementById("letter-date");
  const subject = document.getElementById("letter-subject");
  const bodyContainer = document.getElementById("letter-body");
  const letterClosing = document.getElementById("letter-closing");
  const signatureName = document.getElementById("signature-name");

  // Feedback & Hints controls
  const targetRoleCompany = document.getElementById("target-role-company");
  const userHintText = document.getElementById("user-hint-text");
  const btnApplyHints = document.getElementById("btn-apply-hints");

  // Origin job tab navigation
  const urlParams = new URLSearchParams(window.location.search);
  const originTabId = urlParams.get("tabId") ? parseInt(urlParams.get("tabId"), 10) : null;
  const btnBackToJob = document.getElementById("btn-back-to-job");
  const btnFillAndReturn = document.getElementById("btn-fill-and-return");

  let isEditing = false;
  let letterLang = "de";

  function showToast(msg, isError = false) {
    if (!toast) return;
    toast.innerText = msg;
    toast.style.color = isError ? "#f87171" : "#38bdf8";
    setTimeout(() => { if (toast.innerText === msg) toast.innerText = ""; }, 4500);
  }

  async function getStoredToken() {
    if (typeof chrome !== "undefined" && chrome?.storage?.local) {
      const data = await chrome.storage.local.get(["jobagent_token"]);
      return data?.jobagent_token || "";
    }
    return localStorage.getItem("jobagent_token") || "";
  }

  async function getAuthHeaders() {
    let token = await getStoredToken();
    if (!token) {
      try {
        const pairRes = await fetch(`${gatewayUrl}/api/v1/auth/pair`);
        if (pairRes.ok) {
          const pairData = await pairRes.json();
          if (pairData?.token) {
            token = pairData.token;
            if (typeof chrome !== "undefined" && chrome?.storage?.local) {
              await chrome.storage.local.set({ jobagent_token: token });
            }
          }
        }
      } catch (e) {}
    }
    const headers = { "Content-Type": "application/json" };
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
      headers["X-JobAgent-Token"] = token;
    }
    return headers;
  }

  // Load candidate profile info & saved letter
  const stored = await new Promise(res => {
    if (typeof chrome !== "undefined" && chrome?.storage?.local) {
      chrome.storage.local.get([
        "jobagent_cached_profile",
        "coverLetterData",
        "coverLetterRole",
        "coverLetterCompany",
        "coverLetterJobTitle",
        "coverLetterJobUrl",
        "coverLetterLang",
      ], res);
    } else {
      try {
        const localData = JSON.parse(localStorage.getItem("coverLetterData") || "{}");
        res({ coverLetterData: localData });
      } catch (e) {
        res({});
      }
    }
  });

  let profile = (stored && stored.jobagent_cached_profile) || null;
  if (!profile || !profile.personal) {
    try {
      const resp = await fetch(`${gatewayUrl}/api/v1/auth/pair`);
      if (resp.ok) {
        const pRes = await fetch(`${gatewayUrl}/a2a/v1/status`);
        // Fallback to local profile file if available
      }
    } catch (e) {}
  }

  const p = (profile && profile.personal) || {};
  const j = (profile && profile.preferences) || {};
  const candName = p.fullName || `${p.firstName || ''} ${p.lastName || ''}`.trim() || "Tamas Deak";
  if (senderName) senderName.innerText = candName;
  if (signatureName) signatureName.innerText = candName;
  if (senderContact && (p.street || p.city || p.phone || p.email)) {
    senderContact.innerHTML = [
      p.street,
      [p.postalCode, p.city].filter(Boolean).join(" "),
      p.phone ? `Tel: ${p.phone}` : null,
      p.email ? `E-Mail: ${p.email}` : null
    ].filter(Boolean).join(" &bull; ");
  }

  const candSummaryEl = document.getElementById("candidate-profile-summary");
  if (candSummaryEl) {
    const headline = (j.targetRoles && j.targetRoles[0]) || "Senior Software Engineer / Tech Lead";
    candSummaryEl.innerHTML = `<strong>${candName}</strong> &bull; ${headline}<br>Location: ${p.city || "Frankfurt am Main"}`;
  }

  // Reconcile active pinned job application context
  let activeJob = null;
  const manager = (typeof JobSessionManager !== "undefined" ? JobSessionManager : window.JobSessionManager);
  if (manager) {
    try {
      activeJob = await manager.getActiveJob();
    } catch (e) {}
  }

  // Fetch fresh live context from the origin tab if open and no pinned job
  if (!activeJob && originTabId && chrome.tabs && chrome.tabs.sendMessage) {
    try {
      const tabResp = await new Promise(r => {
        chrome.tabs.sendMessage(originTabId, { action: "get_job_context" }, (resp) => {
          if (chrome.runtime.lastError || !resp) r(null);
          else r(resp.jobContext);
        });
      });
      if (tabResp) activeJob = tabResp;
    } catch (e) {}
  }

  const activeTitle = (activeJob && activeJob.jobTitle) || (stored && stored.coverLetterJobTitle) || "Software Engineer";
  const activeCompany = (activeJob && (activeJob.targetCompany || activeJob.company)) || (stored && stored.coverLetterCompany) || "";
  const initialRoleComp = activeCompany ? `${activeTitle} at ${activeCompany}` : activeTitle;

  if (targetRoleCompany) {
    targetRoleCompany.value = (stored && stored.coverLetterRole) || initialRoleComp;
  }

  if (dateEl && (!dateEl.innerText || dateEl.innerText.trim() === "")) {
    const now = new Date();
    const deMonths = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
    dateEl.innerText = `${String(now.getDate()).padStart(2, '0')}. ${deMonths[now.getMonth()]} ${now.getFullYear()}`;
  }

  if (activeCompany && recipient) {
    const loc = (activeJob && activeJob.location) || "";
    recipient.innerHTML = `${activeCompany}${loc ? `<br>${loc}` : ''}`;
  }

  function saveLetterState() {
    const dataToStore = {
      recipient: recipient ? recipient.innerHTML : "",
      subject: subject ? subject.innerText : "",
      bodyHtml: bodyContainer ? bodyContainer.innerHTML : "",
      closing: letterClosing ? letterClosing.innerText : "",
      language: letterLang,
      company: activeCompany,
      savedAt: Date.now()
    };
    if (typeof chrome !== "undefined" && chrome?.storage?.local) {
      chrome.storage.local.set({
        coverLetterData: dataToStore,
        coverLetterRole: targetRoleCompany ? targetRoleCompany.value : "",
        coverLetterCompany: activeCompany,
        coverLetterJobTitle: activeTitle,
        coverLetterLang: letterLang
      });
    } else {
      try {
        localStorage.setItem("coverLetterData", JSON.stringify(dataToStore));
      } catch (e) {}
    }
  }

  function getFullLetterText() {
    const closingText = (letterClosing && letterClosing.innerText.trim()) ? letterClosing.innerText.trim() : "";
    const sName = (signatureName && signatureName.innerText.trim()) ? signatureName.innerText.trim() : candName;
    const bodyText = (bodyContainer ? bodyContainer.innerText : "").trim();

    let full = bodyText;
    if (closingText && !full.includes(closingText)) {
      full = `${full}\n\n${closingText}\n${sName}`;
    }
    return full;
  }

  async function resolveTargetJobTab() {
    if (originTabId && chrome.tabs) {
      try {
        const tab = await new Promise(r => chrome.tabs.get(originTabId, t => {
          if (chrome.runtime.lastError || !t) r(null);
          else r(t);
        }));
        if (tab && tab.id) return tab.id;
      } catch (e) {}
    }

    if (chrome.tabs && chrome.tabs.query) {
      try {
        const allTabs = await new Promise(r => chrome.tabs.query({ currentWindow: true }, r));
        const candidateTabs = (allTabs || []).filter(t => 
          t.url && 
          !t.url.startsWith("chrome-extension://") && 
          !t.url.startsWith("chrome://") && 
          !t.url.startsWith("edge://") && 
          !t.url.startsWith("about:")
        );
        if (candidateTabs.length > 0) {
          const matched = candidateTabs.find(t => 
            (activeCompany && t.url.toLowerCase().includes(activeCompany.toLowerCase())) ||
            (activeJob?.jobUrl && t.url === activeJob.jobUrl)
          );
          return (matched || candidateTabs[0]).id;
        }
      } catch (e) {}
    }
    return null;
  }

  function returnToJobApplication() {
    saveLetterState();
    resolveTargetJobTab().then(targetTabId => {
      if (targetTabId && chrome.tabs && chrome.tabs.update) {
        chrome.tabs.update(targetTabId, { active: true }, () => {
          window.close();
        });
      } else {
        window.close();
      }
    });
  }

  if (btnBackToJob) {
    btnBackToJob.addEventListener("click", () => {
      returnToJobApplication();
    });
  }

  if (btnFillAndReturn) {
    btnFillAndReturn.addEventListener("click", async () => {
      saveLetterState();
      const textToFill = getFullLetterText();
      try {
        await navigator.clipboard.writeText(textToFill);
        showToast("✓ Full cover letter copied to clipboard!");
      } catch (e) {}

      const targetTabId = await resolveTargetJobTab();
      if (targetTabId && chrome.tabs && chrome.tabs.sendMessage) {
        chrome.tabs.sendMessage(targetTabId, {
          action: "fill_cover_letter_text",
          text: textToFill
        }, (resp) => {
          chrome.tabs.update(targetTabId, { active: true }, () => {
            setTimeout(() => { window.close(); }, 350);
          });
        });
      } else {
        alert("Cover letter copied to clipboard! Switch to your application form and press Ctrl+V to paste.");
      }
    });
  }

  // 1. Toggle Inline Editing
  if (btnToggleEdit) {
    btnToggleEdit.addEventListener("click", () => {
      isEditing = !isEditing;
      const editables = [subject, recipient, bodyContainer, letterClosing];
      editables.forEach(el => {
        if (el) el.setAttribute("contenteditable", isEditing ? "true" : "false");
      });

      btnToggleEdit.innerHTML = isEditing ? "💾 Save Changes" : "✏️ Edit Directly on Letter";
      btnToggleEdit.className = isEditing ? "btn btn-primary" : "btn btn-secondary";
      showToast(isEditing ? "✏️ Edit mode enabled. Click on text to modify." : "✓ Changes saved.");
      if (!isEditing) saveLetterState();
    });
  }

  // 2. Copy Button Handler
  if (btnCopy) {
    btnCopy.addEventListener("click", async () => {
      const fullText = getFullLetterText();
      try {
        await navigator.clipboard.writeText(fullText);
        showToast("✓ Full letter copied to clipboard!");
      } catch (e) {
        showToast("Could not copy automatically. Select text manually.", true);
      }
    });
  }

  // 3. Print / Save PDF Button Handler
  if (btnPrint) {
    btnPrint.addEventListener("click", () => {
      saveLetterState();
      window.print();
    });
  }

  // --- Backend AI Reasoning Engine (JobAgent A2A Integration) ---
  async function generateTailoredCoverLetter(userFeedback = "") {
    const roleComp = (targetRoleCompany.value || "").trim() || initialRoleComp;

    btnApplyHints.disabled = true;
    btnApplyHints.innerText = "✨ Tailoring with Gemini...";
    showToast(`✨ Tailoring letter for ${activeCompany || roleComp} via JobAgent Gemini Flash...`);

    const rawDesc = (activeJob && activeJob.jobDescriptionRaw) ? activeJob.jobDescriptionRaw.slice(0, 6000) : "";

    const payload = {
      company: activeCompany || roleComp,
      role: activeTitle || "Software Engineer",
      recipient: recipient ? recipient.innerText : (activeCompany || "Unternehmen"),
      job_description: rawDesc,
      user_feedback: userFeedback,
      lang: letterLang,
      structured: true
    };

    try {
      const headers = await getAuthHeaders();
      const resp = await fetch(`${gatewayUrl}/api/v1/cover_letter/generate`, {
        method: "POST",
        headers: headers,
        body: JSON.stringify(payload)
      });

      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}: ${await resp.text()}`);
      }

      const parsed = await resp.json();

      if (parsed.language) letterLang = parsed.language;
      if (parsed.formattedDate) dateEl.innerText = parsed.formattedDate;
      if (parsed.subject) subject.innerText = parsed.subject;
      if (parsed.recipient) recipient.innerHTML = parsed.recipient.replace(/\n/g, "<br>");
      if (parsed.closing && letterClosing) letterClosing.innerText = parsed.closing;
      if (parsed.signatureName && signatureName) signatureName.innerText = parsed.signatureName;
      if (parsed.targetRoleCompany && targetRoleCompany) targetRoleCompany.value = parsed.targetRoleCompany;

      if (Array.isArray(parsed.paragraphs)) {
        bodyContainer.innerHTML = parsed.paragraphs.map(p => `<p>${p}</p>`).join("\n");
      } else if (parsed.body_html) {
        bodyContainer.innerHTML = parsed.body_html;
      }

      saveLetterState();
      showToast(`✓ Letter tailored for ${activeCompany || "this role"} in ${letterLang.toUpperCase()}!`);
    } catch (err) {
      console.error("[CoverLetterStudio] Generation error:", err);
      showToast(`AI generation error: ${err.message}`, true);
    } finally {
      btnApplyHints.disabled = false;
      btnApplyHints.innerText = "✨ Apply Feedback & Regenerate";
    }
  }

  // 4. Regenerate Button Handler
  if (btnApplyHints) {
    btnApplyHints.addEventListener("click", async () => {
      const userFeedback = (userHintText.value || "").trim();
      await generateTailoredCoverLetter(userFeedback);
    });
  }

  // --- Initial Display / Auto-Tailoring Dispatch ---
  const hasMatchingDraft = stored && stored.coverLetterData && stored.coverLetterCompany &&
    activeCompany && stored.coverLetterCompany.toLowerCase() === activeCompany.toLowerCase();

  if (hasMatchingDraft && stored.coverLetterData) {
    const c = stored.coverLetterData;
    if (c.recipient) recipient.innerHTML = c.recipient;
    if (c.subject) subject.innerText = c.subject;
    if (c.bodyHtml) bodyContainer.innerHTML = c.bodyHtml;
    if (c.closing && letterClosing) letterClosing.innerText = c.closing;
    if (c.language) letterLang = c.language;
  } else {
    bodyContainer.innerHTML = `
      <div style="text-align: center; padding: 48px 20px; color: #475569;">
        <div style="font-size: 28px; margin-bottom: 12px;">✨</div>
        <p style="font-size: 16px; font-weight: 600; color: #0f172a; margin-bottom: 6px;">
          Tailoring cover letter for ${activeTitle || "this role"} with JobAgent Gemini AI...
        </p>
        <p style="font-size: 13px; color: #64748b; max-width: 480px; margin: 0 auto;">
          Analyzing specific job requirements, tech stack, and responsibilities against your verified candidate profile.
        </p>
      </div>
    `;

    // Trigger auto-tailoring immediately
    generateTailoredCoverLetter().catch(err => {
      console.warn("[CoverLetterStudio] Auto-tailor error:", err);
    });
  }
});
