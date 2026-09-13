// JobAgent Copilot - Content Script Bootstrap & Message Dispatcher
// Modular Architecture: Coordinates form_extractor, field_writer, document_uploader, local_fallback, and ui_overlay

(function () {
  "use strict";

  window.JobAgent = window.JobAgent || {};
  console.log("[JobAgent Copilot] Injected and active on:", window.location.href);

  function performAutofill(request, sendResponse) {
    const { schema, elementMap } = window.JobAgent.extractFormSchema();
    console.log(`[JobAgent Copilot] Autofill triggered on ${window.location.href}. Found ${schema.length} fields.`);

    if (schema.length === 0) {
      if (sendResponse) sendResponse({ filledCount: 0, totalFields: 0, method: "No fields detected" });
      return;
    }

    const profile = request.profile;
    const documents = request.documents;

    async function handleReasoningResult(data, method) {
      let filledCount = 0;
      const mappings = data.mappings || {};
      const requiresConfirm = new Set(data.requires_confirmation || []);
      const sapSelectQueue = [];

      for (const [fieldId, val] of Object.entries(mappings)) {
        const el = elementMap.get(fieldId);
        if (!el) continue;

        if (window.JobAgent.applyValueToElement(el, val)) {
          filledCount++;
          if (requiresConfirm.has(fieldId)) {
            el.style.border = "2px dashed #f59e0b";
            el.title = "⚠️ Legally sensitive field: please confirm before submitting";
          }
        }

        const isComboboxDiv = el.getAttribute?.("role") === "combobox";
        const isNativeSelectInSap = el.tagName?.toLowerCase() === "select" && !!el.closest?.('[role="combobox"], .sapMSlt');
        if (isComboboxDiv || isNativeSelectInSap) {
          const wrapper = isComboboxDiv ? el : el.closest('[role="combobox"], .sapMSlt');
          if (wrapper) {
            sapSelectQueue.push({ val: String(val), wrapper });
          }
        }
      }

      for (const { val, wrapper } of sapSelectQueue) {
        const labelEl = wrapper.querySelector(".sapMSltLabel, [class*='Label'], [class*='label'], span");
        const visibleText = (labelEl?.innerText || labelEl?.textContent || wrapper.innerText || "").trim().toLowerCase();
        const isAlreadySet = visibleText.includes(val.toLowerCase()) ||
          (val === "+49" && visibleText.includes("+49")) ||
          (val.toLowerCase() === "deutschland" && visibleText.includes("deutschland"));
        if (!isAlreadySet && window.JobAgent.applyValueToSapUi5Select) {
          const ok = await window.JobAgent.applyValueToSapUi5Select(wrapper, val);
          if (ok) filledCount++;
        }
      }

      const docsAttached = window.JobAgent.attachDocumentsToPage
        ? await window.JobAgent.attachDocumentsToPage(documents)
        : 0;
      filledCount += docsAttached;

      console.log(`[JobAgent Copilot] Form fill complete (${method}). Filled ${filledCount} fields.`);
      if (sendResponse) {
        sendResponse({ filledCount, method, totalFields: schema.length });
      }
    }

    if (chrome.runtime && chrome.runtime.sendMessage) {
      chrome.runtime.sendMessage(
        {
          action: "request_gateway_reason",
          payload: { url: window.location.href, fields: schema },
        },
        (response) => {
          if (!chrome.runtime.lastError && response?.ok && response?.data) {
            handleReasoningResult(response.data, "Gemini Flash & QA Memory (Proxy)");
            return;
          }

          console.log("[JobAgent Copilot] Message proxy unavailable, falling back to local engine...");
          window.JobAgent.localFallbackFill(schema, elementMap, profile, documents).then((count) => {
            if (window.JobAgent.attachDocumentsToPage) {
              window.JobAgent.attachDocumentsToPage(documents).then((docsAttached) => {
                if (sendResponse) {
                  sendResponse({ filledCount: count + docsAttached, method: "Local Candidate Engine", totalFields: schema.length });
                }
              });
            } else if (sendResponse) {
              sendResponse({ filledCount: count, method: "Local Candidate Engine", totalFields: schema.length });
            }
          });
        }
      );
      return;
    }

    window.JobAgent.localFallbackFill(schema, elementMap, profile, documents).then((count) => {
      if (window.JobAgent.attachDocumentsToPage) {
        window.JobAgent.attachDocumentsToPage(documents).then((docsAttached) => {
          if (sendResponse) {
            sendResponse({ filledCount: count + docsAttached, method: "Local Candidate Engine", totalFields: schema.length });
          }
        });
      } else if (sendResponse) {
        sendResponse({ filledCount: count, method: "Local Candidate Engine", totalFields: schema.length });
      }
    });
  }

  window.JobAgent.performAutofill = performAutofill;

  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "ping") {
      sendResponse({ status: "alive" });
      return true;
    }

    if (request.action === "extract_page_content") {
      const isLinkedIn = window.location.hostname.includes("linkedin.com");
      let company = "";
      const linkedInCompany = document.querySelector(
        ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, .job-details-jobs-unified-top-card__company-name a, [class*='top-card__company-name'], a[href*='/company/']"
      )?.innerText?.trim();

      if (linkedInCompany) {
        company = linkedInCompany;
      } else {
        const metaCompany = document.querySelector("meta[property='og:site_name']")?.content;
        if (metaCompany && (!isLinkedIn || metaCompany.toLowerCase() !== "linkedin")) {
          company = metaCompany;
        } else {
          const parts = document.title.split(/[-–|·]|\bat\b|@/i).map((p) => p.trim()).filter(Boolean);
          if (isLinkedIn && parts.length >= 3 && parts[parts.length - 1].toLowerCase().includes("linkedin")) {
            company = parts[parts.length - 2];
          } else if (parts.length > 1) {
            const last = parts[parts.length - 1];
            company = (isLinkedIn && last.toLowerCase().includes("linkedin") && parts.length > 2) ? parts[parts.length - 2] : last;
          }
        }
      }

      const title =
        document.querySelector(".job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, h1.t-24, h1")?.innerText?.trim() ||
        document.title.split(/[-–|·]|\bat\b|@/i)[0]?.trim() ||
        document.title;

      sendResponse({ title, company: company || "Company", html: document.body.innerHTML });
      return true;
    }

    if (request.action === "extract_job_posting") {
      const extractor = (typeof window.JobExtractor !== "undefined") ? window.JobExtractor : (typeof JobExtractor !== "undefined" ? JobExtractor : null);
      if (extractor) {
        const jobData = extractor.extractJobPosting();
        sendResponse({ success: true, jobData });
      } else {
        const title = document.querySelector("h1")?.innerText?.trim() || document.title;
        sendResponse({
          success: true,
          jobData: {
            applicationId: `job--${Date.now()}`,
            jobTitle: title,
            company: "Company",
            jobUrl: window.location.href,
            jobDescriptionRaw: document.body ? document.body.innerText.slice(0, 8000) : "",
            capturedDate: new Date().toLocaleDateString("de-DE"),
            capturedTimestamp: Date.now(),
            status: "CAPTURED",
          }
        });
      }
      return true;
    }

    if (request.action === "get_job_context") {
      const extractor = (typeof window.JobExtractor !== "undefined") ? window.JobExtractor : (typeof JobExtractor !== "undefined" ? JobExtractor : null);
      const jobData = extractor ? extractor.extractJobPosting() : null;
      sendResponse({
        success: true,
        jobContext: jobData || {
          jobTitle: document.querySelector("h1")?.innerText?.trim() || document.title,
          company: "",
          jobUrl: window.location.href,
          jobDescriptionRaw: document.body ? document.body.innerText.slice(0, 8000) : "",
        }
      });
      return true;
    }

    if (request.action === "fill_cover_letter_text") {
      const text = request.text || "";
      const allTextareas = Array.from(document.querySelectorAll("textarea, [contenteditable='true']"));
      let targetEl = allTextareas.find(t => {
        const ph = (t.placeholder || "").toLowerCase();
        const nm = (t.name || t.id || "").toLowerCase();
        const aria = (t.getAttribute("aria-label") || "").toLowerCase();
        const combined = `${ph} ${nm} ${aria}`;
        return combined.includes("cover") || combined.includes("anschreiben") || combined.includes("motivation") ||
               combined.includes("message") || combined.includes("nachricht") || combined.includes("fit") ||
               combined.includes("why you");
      });
      if (!targetEl && allTextareas.length > 0) targetEl = allTextareas[0];

      if (targetEl) {
        if (targetEl.isContentEditable) {
          targetEl.innerText = text;
        } else {
          targetEl.value = text;
        }
        targetEl.dispatchEvent(new Event("input", { bubbles: true }));
        targetEl.dispatchEvent(new Event("change", { bubbles: true }));
        try {
          targetEl.scrollIntoView({ behavior: "smooth", block: "center" });
        } catch (e) {}
        sendResponse({ success: true, filled: true });
      } else {
        sendResponse({ success: true, filled: false, note: "Text copied to clipboard" });
      }
      return true;
    }

    if (request.action === "autofill_form") {
      performAutofill(request, sendResponse);
      return true;
    }
  });

  if (window.JobAgent.initModalObserver) {
    window.JobAgent.initModalObserver();
  }
})();
