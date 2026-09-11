// JobAgent Content Script
// Handles DOM extraction for 1-Click Archiving and Intelligent Whole-Form Reasoning

(function () {
  "use strict";

  console.log("[JobAgent Copilot] Injected and active on:", window.location.href);

  // ---------------------------------------------------------------------------
  // 1. Enhanced Label Extraction Helpers
  // ---------------------------------------------------------------------------
  function getFieldLabel(el) {
    // 1. Explicit <label for="id">
    if (el.id) {
      try {
        const explicitLabel = document.querySelector(`label[for="${CSS.escape(el.id)}"]`);
        if (explicitLabel && explicitLabel.innerText.trim()) {
          return explicitLabel.innerText.trim();
        }
      } catch (e) {}
    }

    // 2. Enclosing <label>
    const parentLabel = el.closest("label");
    if (parentLabel && parentLabel.innerText.trim()) {
      return parentLabel.innerText.trim();
    }

    // 3. aria-label, title, or aria-labelledby
    const ariaLabel = el.getAttribute("aria-label");
    if (ariaLabel && ariaLabel.trim()) {
      return ariaLabel.trim();
    }

    const titleAttr = el.getAttribute("title");
    if (titleAttr && titleAttr.trim()) {
      return titleAttr.trim();
    }

    const ariaLabelledBy = el.getAttribute("aria-labelledby");
    if (ariaLabelledBy) {
      try {
        const refEl = document.getElementById(ariaLabelledBy);
        if (refEl && refEl.innerText.trim()) {
          return refEl.innerText.trim();
        }
      } catch (e) {}
    }

    // 4. Table layout (e.g. <tr><td>Label</td><td><input></td></tr>)
    const tr = el.closest("tr");
    if (tr) {
      const cell = el.closest("td, th");
      const prevCell = cell?.previousElementSibling;
      if (prevCell && prevCell.innerText.trim()) {
        return prevCell.innerText.trim();
      }
    }

    // 5. Container label (SAP UI5, Bootstrap, Tailwind, standard forms)
    const container = el.closest(
      ".form-group, .form-field, .form-row, .field, .input-wrapper, .fd-form-item, [class*='field'], [class*='form-group'], [class*='row']"
    );
    if (container) {
      const lbl = container.querySelector("label, .label, [class*='label'], legend, span.title, .fd-form-label");
      if (lbl && lbl.innerText.trim()) {
        return lbl.innerText.trim();
      }
    }

    // 6. Preceding sibling (label or span)
    const prev = el.previousElementSibling;
    if (prev && (prev.tagName === "LABEL" || prev.tagName === "SPAN" || prev.tagName === "DIV") && prev.innerText.trim()) {
      return prev.innerText.trim();
    }

    // 7. Parent's preceding sibling
    const parentPrev = el.parentElement?.previousElementSibling;
    if (parentPrev && parentPrev.innerText.trim()) {
      return parentPrev.innerText.trim();
    }

    return el.placeholder || el.name || el.id || "";
  }

  function getSectionHeader(el) {
    const container = el.closest("fieldset, section, .card, .panel, .form-section, form");
    if (container) {
      const header = container.querySelector("legend, h1, h2, h3, h4, .section-title, .header");
      if (header && header.innerText.trim()) {
        return header.innerText.trim().replace(/\s+/g, " ");
      }
    }
    return "";
  }

  // ---------------------------------------------------------------------------
  // 2. Whole-Form Schema Extractor
  // ---------------------------------------------------------------------------
  function extractFormSchema() {
    const elements = Array.from(
      document.querySelectorAll(
        "input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select, [role='combobox']"
      )
    );

    const schema = [];
    const elementMap = new Map();
    let index = 0;

    for (const el of elements) {
      // Check visibility
      const isVisible =
        el.offsetWidth > 0 ||
        el.offsetHeight > 0 ||
        (window.getComputedStyle && window.getComputedStyle(el).display !== "none");
      const isSpecial = el.type === "radio" || el.type === "checkbox" || el.type === "file";
      if (!isVisible && !isSpecial) continue;

      const tag = el.tagName.toLowerCase();
      const type = (el.type || (tag === "textarea" ? "textarea" : tag)).toLowerCase();
      const fieldId = `ja_f_${index++}`;
      el.dataset.jaFieldId = fieldId;
      elementMap.set(fieldId, el);

      let options = undefined;
      if (tag === "select") {
        options = Array.from(el.options).map((opt) => ({
          value: opt.value,
          text: (opt.text || "").trim(),
        }));
      } else if (type === "radio" && el.name) {
        try {
          const radios = Array.from(
            document.querySelectorAll(`input[type='radio'][name='${CSS.escape(el.name)}']`)
          );
          options = radios.map((r) => {
            const rlbl = r.id ? document.querySelector(`label[for='${CSS.escape(r.id)}']`) : r.closest("label");
            return {
              value: r.value,
              text: (rlbl ? rlbl.innerText : r.value || "").trim(),
            };
          });
        } catch (e) {}
      }

      schema.push({
        fieldId: fieldId,
        tagName: tag,
        type: type,
        name: el.name || "",
        id: el.id || "",
        label: getFieldLabel(el),
        placeholder: el.placeholder || "",
        sectionHeader: getSectionHeader(el),
        options: options,
      });
    }

    return { schema, elementMap };
  }

  // ---------------------------------------------------------------------------
  // 3. Safe DOM Value Setter (Works with React, Angular, Vue, and SAP UI5)
  // ---------------------------------------------------------------------------
  function dataUrlToFile(dataUrl, filename) {
    try {
      const parts = dataUrl.split(",");
      const mime = parts[0].match(/:(.*?);/)?.[1] || "application/pdf";
      const bstr = atob(parts[1]);
      let n = bstr.length;
      const u8arr = new Uint8Array(n);
      while (n--) {
        u8arr[n] = bstr.charCodeAt(n);
      }
      return new File([u8arr], filename, { type: mime });
    } catch (e) {
      console.warn("[JobAgent Copilot] Failed to convert dataUrl to File:", e);
      return null;
    }
  }

  function uploadDocumentToInput(inputEl, docObj) {
    if (!inputEl || !docObj?.dataUrl || !docObj?.filename) return false;
    try {
      const file = dataUrlToFile(docObj.dataUrl, docObj.filename);
      if (!file) return false;
      const dt = new DataTransfer();
      dt.items.add(file);
      inputEl.files = dt.files;
      inputEl.dispatchEvent(new Event("input", { bubbles: true }));
      inputEl.dispatchEvent(new Event("change", { bubbles: true }));
      inputEl.dispatchEvent(new Event("blur", { bubbles: true }));
      highlightField(inputEl);
      console.log(`[JobAgent Copilot] 📎 Uploaded '${docObj.filename}' to file input:`, inputEl);
      return true;
    } catch (e) {
      console.warn("[JobAgent Copilot] File upload error:", e);
      return false;
    }
  }

  function applyValueToElement(el, val) {
    if (!el || val === undefined || val === null) return false;
    const tag = el.tagName.toLowerCase();
    const type = (el.type || tag).toLowerCase();
    const strVal = String(val).trim();

    if (type === "file") {
      if (typeof val === "object" && val?.dataUrl) {
        return uploadDocumentToInput(el, val);
      }
      return false;
    }

    if (tag === "select") {
      let matched = false;
      const cleanTarget = strVal.toLowerCase();
      const isYes = ["yes", "ja", "true", "1"].includes(cleanTarget);
      const isNo = ["no", "nein", "false", "0"].includes(cleanTarget);
      const isDePhone = ["+49", "49", "0049"].includes(cleanTarget);
      const isGermany = ["deutschland", "germany", "de"].includes(cleanTarget);

      for (let i = 0; i < el.options.length; i++) {
        const opt = el.options[i];
        const optVal = (opt.value || "").toLowerCase().trim();
        const optTxt = (opt.text || "").toLowerCase().trim();

        // Skip placeholder prompt options
        if (!optVal && /bitte|auswählen|select|choose|keine auswahl/i.test(optTxt)) {
          continue;
        }

        // 1. Semantic Yes/No matching
        if (isYes) {
          if (["ja", "yes", "1", "y"].includes(optVal) || ["ja", "yes"].includes(optTxt) || optTxt.startsWith("ja ") || optTxt.startsWith("yes ")) {
            el.selectedIndex = i;
            matched = true;
            break;
          }
        } else if (isNo) {
          if (["nein", "no", "0", "n"].includes(optVal) || ["nein", "no"].includes(optTxt) || (optTxt.startsWith("nein") && !optTxt.includes("auswahl"))) {
            el.selectedIndex = i;
            matched = true;
            break;
          }
        }
        // 2. Phone country prefix (+49 -> Deutschland (+49))
        else if (isDePhone) {
          if (optTxt.includes("+49") || optTxt.includes("deutschland (+49)") || optVal === "de" || optVal === "+49" || optVal === "49") {
            el.selectedIndex = i;
            matched = true;
            break;
          }
        }
        // 3. Country of residence (Deutschland / Germany)
        else if (isGermany) {
          if (optTxt.includes("deutschland") || optTxt.includes("germany") || optVal === "de" || optVal === "deutschland" || optVal === "germany") {
            el.selectedIndex = i;
            matched = true;
            break;
          }
        }
        // 4. Exact or substring match
        else {
          if (optVal === cleanTarget || optTxt === cleanTarget || (cleanTarget && (optTxt.includes(cleanTarget) || cleanTarget.includes(optTxt)))) {
            el.selectedIndex = i;
            matched = true;
            break;
          }
        }
      }

      if (matched) {
        el.dispatchEvent(new Event("change", { bubbles: true }));
        highlightField(el);
        return true;
      }
      return false;
    }

    if (type === "radio") {
      try {
        const radios = el.name
          ? Array.from(document.querySelectorAll(`input[type='radio'][name='${CSS.escape(el.name)}']`))
          : [el];
        const cleanTarget = strVal.toLowerCase();
        for (const r of radios) {
          const rVal = (r.value || "").toLowerCase();
          const rLbl = (r.id ? document.querySelector(`label[for='${CSS.escape(r.id)}']`) : r.closest("label"))?.innerText?.toLowerCase() || "";
          if (rVal === cleanTarget || rLbl.includes(cleanTarget)) {
            r.checked = true;
            r.dispatchEvent(new Event("click", { bubbles: true }));
            r.dispatchEvent(new Event("change", { bubbles: true }));
            highlightField(r);
            return true;
          }
        }
      } catch (e) {}
      return false;
    }

    if (type === "checkbox") {
      const affirmative = ["yes", "ja", "true", "1", "agreed", "zugestimmt"].includes(strVal.toLowerCase());
      if (affirmative) {
        el.checked = true;
        el.dispatchEvent(new Event("change", { bubbles: true }));
        highlightField(el);
        return true;
      }
      return false;
    }

    // Standard input, email, tel, text, textarea:
    try {
      const proto = Object.getPrototypeOf(el);
      const desc = Object.getOwnPropertyDescriptor(proto, "value") ||
                   Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
      if (desc && desc.set) {
        desc.set.call(el, strVal);
      } else {
        el.value = strVal;
      }
    } catch (e) {
      el.value = strVal;
    }

    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
    highlightField(el);
    return true;
  }

  function highlightField(el) {
    try {
      el.style.transition = "box-shadow 0.4s ease, border-color 0.4s ease";
      el.style.boxShadow = "0 0 8px rgba(16, 185, 129, 0.7)";
      el.style.borderColor = "#10b981";
      setTimeout(() => {
        el.style.boxShadow = "";
      }, 2500);
    } catch (e) {}
  }

  // ---------------------------------------------------------------------------
  // 4. Local Fast-Path Fallback (Works fully offline)
  // ---------------------------------------------------------------------------
  function localFallbackFill(schema, elementMap, profile, documents) {
    let filledCount = 0;
    const pers = profile?.personal || {};
    const commonAnswers = profile?.common_answers || pers?.qaAnswers || {};

    console.log("[JobAgent Copilot] Running local fallback form fill with candidate profile:", pers.fullName || "(unnamed)");

    for (const f of schema) {
      const el = elementMap.get(f.fieldId);
      if (!el) continue;

      const desc = `${f.label} ${f.name} ${f.placeholder} ${f.id}`.toLowerCase();

      // Security: Never fill password fields
      if (f.type === "password" || /kennwort|passwort|password/i.test(desc)) {
        console.log("[JobAgent Copilot] 🔒 Skipping sensitive password field for security:", f.label || desc);
        continue;
      }

      // 0. File upload fields (CV, Cover Letter, Reference Letter)
      if (f.type === "file") {
        if (/lebenslauf|cv|resume|curriculum/i.test(desc)) {
          if (documents?.cv && uploadDocumentToInput(el, documents.cv)) {
            filledCount++;
            continue;
          }
        } else if (/anschreiben|cover.*letter|motivation/i.test(desc)) {
          if (documents?.coverLetter && uploadDocumentToInput(el, documents.coverLetter)) {
            filledCount++;
            continue;
          }
        } else if (/zeugnis|referenz|reference/i.test(desc)) {
          if (documents?.reference && uploadDocumentToInput(el, documents.reference)) {
            filledCount++;
            continue;
          }
        } else if (documents?.cv) {
          // Default to CV for generic file field
          if (uploadDocumentToInput(el, documents.cv)) {
            filledCount++;
            continue;
          }
        }
        continue;
      }

      if (el.value) continue;

      let val = null;

      // 1. Middle Name (Zweiter Vorname) - MUST be evaluated before First Name!
      if (/zweiter.*vorname|middle.*name/i.test(desc)) {
        val = pers.middleName || null; // Leave empty if candidate has no middle name
      }
      // 2. First Name
      else if (/first.*name|vorname|given.*name/i.test(desc)) {
        val = pers.firstName || (pers.fullName ? pers.fullName.split(" ")[0] : "");
      }
      // 3. Last Name
      else if (/last.*name|nachname|familienname|surname/i.test(desc)) {
        val = pers.lastName || ((pers.fullName || "").split(" ").slice(1).join(" "));
      }
      // 4. Full Name
      else if (/full.*name|ihr.*name|name/i.test(desc) && !/company|file|user|firma|datei|benutzer/i.test(desc)) {
        val = pers.fullName;
      }
      // 5. Country Dialing Prefix (Länder-/Regionsvorwahl)
      else if (/länder.*vorwahl|regionsvorwahl|country.*code|vorwahl|dialing.*code/i.test(desc)) {
        val = pers.phoneCountryCode || "+49";
      }
      // 6. Phone Number
      else if (/phone|telefon|mobile|handy|rufnummer/i.test(desc) || f.type === "tel") {
        val = pers.phone;
      }
      // 7. Country of Residence (Land des aktuellen Wohnsitzes)
      else if (/aktuell.*wohnsitz|country.*residence|wohnsitz|land.*wohnsitz/i.test(desc)) {
        val = pers.countryDe || pers.countryEn || "Deutschland";
      }
      // 8. Work Authorization (Arbeitserlaubnis in dem Land)
      else if (/arbeitserlaubnis|work.*authorization|legal.*right.*to.*work/i.test(desc)) {
        val = "Ja";
      }
      // 9. Previously Employed (Warst du bereits bei der ... Gruppe angestellt?)
      else if (/bereits.*angestellt|previously.*employed|bereits.*gearbeitet|früher.*angestellt/i.test(desc)) {
        val = "Nein";
      }
      // 10. Email Address
      else if (/email|e-mail|mail.*adresse/i.test(desc) || f.type === "email") {
        val = pers.email;
      }
      // 11. Address & Location
      else if (/city|ort|stadt|wohnort/i.test(desc)) {
        val = pers.city || ((pers.address || "").split(",")[1] || "").replace(/^\s*\d{4,5}\s*/, "").trim() || "";
      } else if (/address|adresse|straße|strasse|hausnummer/i.test(desc)) {
        val = pers.street || pers.address;
      } else if (/zip|plz|postleitzahl|postal/i.test(desc)) {
        val = pers.postalCode || ((pers.address || "").match(/\b\d{5}\b/)?.[0] || "");
      }
      // 12. Salary Expectation
      else if (/salary|gehalt|gehaltsvorstellung|compensation|vergütung/i.test(desc)) {
        val = pers.salaryExpectation;
      }
      // 13. Notice Period / Availability
      else if (/notice|kündigungsfrist|verfügbar|availability|start.*date|eintritt/i.test(desc)) {
        val = pers.noticePeriod;
      }
      // 14. Links
      else if (/linkedin/i.test(desc)) {
        val = pers.linkedinUrl || "";
      } else if (/github/i.test(desc)) {
        val = pers.githubUrl || "";
      }

      // 15. Check persistent Q&A memory for questionnaire fields
      if (!val && commonAnswers) {
        for (const [qKey, qAns] of Object.entries(commonAnswers)) {
          const normKey = qKey.toLowerCase().replace(/[^\w\s]/g, " ").trim();
          if (normKey.length >= 4 && desc.includes(normKey)) {
            val = qAns;
            break;
          }
        }
      }

      if (val && applyValueToElement(el, val)) {
        console.log(`[JobAgent Copilot] ✅ Auto-filled field '${f.label || f.name}':`, val);
        filledCount++;
      }
    }
    return filledCount;
  }

  // ---------------------------------------------------------------------------
  // 5. Autofill Execution Handler
  // ---------------------------------------------------------------------------
  function performAutofill(request, sendResponse) {
    const { schema, elementMap } = extractFormSchema();
    console.log(`[JobAgent Copilot] Autofill triggered on ${window.location.href}. Found ${schema.length} fields.`);

    if (schema.length === 0) {
      if (sendResponse) sendResponse({ filledCount: 0, totalFields: 0, method: "No fields detected" });
      return;
    }

    const gatewayUrl = request.gatewayUrl;
    const profile = request.profile;
    const documents = request.documents;

    function handleReasoningResult(data, method) {
      let filledCount = 0;
      const mappings = data.mappings || {};
      const requiresConfirm = new Set(data.requires_confirmation || []);

      for (const [fieldId, val] of Object.entries(mappings)) {
        const el = elementMap.get(fieldId);
        if (el && applyValueToElement(el, val)) {
          filledCount++;
          // C3: Confirmation Gating Preview
          if (requiresConfirm.has(fieldId)) {
            el.style.border = "2px dashed #f59e0b";
            el.title = "⚠️ Legally sensitive field: please confirm before submitting";
          }
        }
      }

      // Also ensure document file uploads are processed if not already handled
      for (const f of schema) {
        if (f.type === "file") {
          const el = elementMap.get(f.fieldId);
          if (el && (!el.files || el.files.length === 0)) {
            const desc = `${f.label} ${f.name} ${f.placeholder} ${f.id}`.toLowerCase();
            if (/anschreiben|cover.*letter/i.test(desc) && documents?.coverLetter) {
              if (uploadDocumentToInput(el, documents.coverLetter)) filledCount++;
            } else if (documents?.cv) {
              if (uploadDocumentToInput(el, documents.cv)) filledCount++;
            }
          }
        }
      }

      console.log(`[JobAgent Copilot] Form fill complete (${method}). Filled ${filledCount} fields.`);
      if (sendResponse) {
        sendResponse({
          filledCount: filledCount,
          method: method,
          totalFields: schema.length,
        });
      }
    }

    // Attempt reasoning via Extension Message Proxy first (avoids HTTPS/mixed-content block)
    if (chrome.runtime && chrome.runtime.sendMessage) {
      chrome.runtime.sendMessage(
        {
          action: "request_gateway_reason",
          payload: {
            url: window.location.href,
            fields: schema,
          },
        },
        (response) => {
          if (!chrome.runtime.lastError && response?.ok && response?.data) {
            handleReasoningResult(response.data, "Gemini Flash & QA Memory (Proxy)");
            return;
          }

          // If message proxy failed or offline, try local fallback
          console.log("[JobAgent Copilot] Message proxy unavailable, falling back to local engine...");
          const count = localFallbackFill(schema, elementMap, profile, documents);
          if (sendResponse) {
            sendResponse({
              filledCount: count,
              method: "Local Candidate Engine",
              totalFields: schema.length,
            });
          }
        }
      );
      return;
    }

    // Direct local fallback
    const count = localFallbackFill(schema, elementMap, profile, documents);
    if (sendResponse) {
      sendResponse({
        filledCount: count,
        method: "Local Candidate Engine",
        totalFields: schema.length,
      });
    }
  }

  // ---------------------------------------------------------------------------
  // 6. Listen for Events (Runtime messages and iframe window broadcasts)
  // ---------------------------------------------------------------------------
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "ping") {
      sendResponse({ status: "alive" });
      return true;
    }

    // 1-Click Page Archiving
    if (request.action === "extract_page_content") {
      const title = document.querySelector("h1")?.innerText?.trim() || document.title;
      let company = "";
      const metaCompany = document.querySelector("meta[property='og:site_name']")?.content;
      if (metaCompany) {
        company = metaCompany;
      } else {
        const parts = document.title.split(/[-–|·at@]/);
        if (parts.length > 1) {
          company = parts[parts.length - 1].trim();
        }
      }

      sendResponse({
        title: title,
        company: company || "Company",
        html: document.body.innerHTML,
      });
      return true;
    }

    // Intelligent Whole-Form Auto-Fill
    if (request.action === "autofill_form") {
      performAutofill(request, sendResponse);
      return true; // Keep message channel open for async response
    }
  });

  // JobAgent Copilot content script — no window-level "message" listeners.
  // All communication uses chrome.runtime.onMessage (extension-private, invisible
  // to page scripts and third-party iframes).
})();
