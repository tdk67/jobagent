/**
 * Job Session & Application Archive Manager
 * Persists active job applications in chrome.storage.local across redirects,
 * new tabs, logins, and email validation hops.
 * Also maintains an immutable local history archive.
 */

(function(root) {
  const ACTIVE_KEY = "activeJobApplication";
  const HISTORY_KEY = "savedJobApplications";
  const MAX_ACTIVE_AGE_MS = 12 * 60 * 60 * 1000; // 12 hours expiration

  async function getStorage(keys) {
    if (typeof chrome === "undefined" || !chrome.storage || !chrome.storage.local) {
      return {};
    }
    return new Promise(res => chrome.storage.local.get(keys, res));
  }

  async function setStorage(items) {
    if (typeof chrome === "undefined" || !chrome.storage || !chrome.storage.local) {
      return;
    }
    return new Promise(res => chrome.storage.local.set(items, res));
  }

  async function saveActiveJob(jobData) {
    if (!jobData || !jobData.applicationId) return null;
    
    // Save as active job
    await setStorage({ [ACTIVE_KEY]: jobData });

    // Append / update in history archive
    const data = await getStorage(HISTORY_KEY);
    const history = Array.isArray(data[HISTORY_KEY]) ? data[HISTORY_KEY] : [];
    const existingIdx = history.findIndex(h => h.applicationId === jobData.applicationId);
    if (existingIdx >= 0) {
      history[existingIdx] = { ...history[existingIdx], ...jobData };
    } else {
      history.unshift(jobData);
    }
    // Keep max 200 items in local history
    await setStorage({ [HISTORY_KEY]: history.slice(0, 200) });
    console.log("[JobSessionManager] Saved active job application:", jobData.applicationId);
    return jobData;
  }

  async function getActiveJob() {
    const data = await getStorage(ACTIVE_KEY);
    const active = data[ACTIVE_KEY];
    if (!active || !active.capturedTimestamp) return null;

    // Check expiration
    const age = Date.now() - active.capturedTimestamp;
    if (age > MAX_ACTIVE_AGE_MS) {
      console.log("[JobSessionManager] Active job expired (> 12h):", active.applicationId);
      await clearActiveJob();
      return null;
    }
    return active;
  }

  async function clearActiveJob() {
    if (typeof chrome === "undefined" || !chrome.storage || !chrome.storage.local) return;
    return new Promise(res => chrome.storage.local.remove(ACTIVE_KEY, res));
  }

  async function markJobApplied(applicationId, details = {}) {
    const active = await getActiveJob();
    const targetId = applicationId || (active ? active.applicationId : null);
    if (!targetId) return;

    const data = await getStorage(HISTORY_KEY);
    const history = Array.isArray(data[HISTORY_KEY]) ? data[HISTORY_KEY] : [];
    const idx = history.findIndex(h => h.applicationId === targetId);

    const updates = {
      status: "APPLIED",
      appliedTimestamp: Date.now(),
      appliedDate: details.appliedDate || new Date().toLocaleDateString("de-DE"),
      cvSent: details.cvSent || "",
      coverLetterSent: details.coverLetterSent || "",
      notes: details.notes || ""
    };

    if (idx >= 0) {
      history[idx] = { ...history[idx], ...updates };
      await setStorage({ [HISTORY_KEY]: history });
    }

    if (active && active.applicationId === targetId) {
      await setStorage({ [ACTIVE_KEY]: { ...active, ...updates } });
    }

    console.log("[JobSessionManager] Marked job as APPLIED:", targetId);
  }

  async function getJobHistory() {
    const data = await getStorage(HISTORY_KEY);
    return Array.isArray(data[HISTORY_KEY]) ? data[HISTORY_KEY] : [];
  }

  const JobSessionManager = {
    saveActiveJob,
    getActiveJob,
    clearActiveJob,
    markJobApplied,
    getJobHistory
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = JobSessionManager;
  } else {
    root.JobSessionManager = JobSessionManager;
  }
})(typeof window !== "undefined" ? window : globalThis);
