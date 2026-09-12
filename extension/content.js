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
  // 2. Whole-Form Schema Extractor with Modal/Dialog Scoping
  // ---------------------------------------------------------------------------
  function getActiveFormContainer() {
    // Detect active modal dialogs (LinkedIn Easy Apply, Greenhouse, Lever, Workday, etc.)
    const modalSelectors = [
      ".jobs-easy-apply-modal",
      ".artdeco-modal",
      "[role='dialog']:not([aria-hidden='true'])",
      "dialog[open]",
      ".modal.show",
      ".modal.in",
      "[aria-modal='true']",
      ".popup-content",
      ".application-modal",
      ".jobs-apply-form",
    ];

    for (const sel of modalSelectors) {
      const modals = Array.from(document.querySelectorAll(sel));
      for (const modal of modals) {
        if (modal.offsetWidth > 0 || modal.offsetHeight > 0 || (window.getComputedStyle && window.getComputedStyle(modal).display !== "none")) {
          const hasInputs = modal.querySelector("input, textarea, select");
          if (hasInputs) {
            return modal;
          }
        }
      }
    }
    return document;
  }

  function extractFormSchema() {
    const container = getActiveFormContainer();
    if (container !== document) {
      console.log("[JobAgent Copilot] 🎯 Active popup/modal dialog detected. Scoping autofill to modal container:", container);
    }

    const elements = Array.from(
      container.querySelectorAll(
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
      } else if (el.getAttribute("role") === "combobox") {
        // SAP UI5 / ARIA combobox: extract options from the associated listbox,
        // from a backing native <select>, or from visible role=option children.
        const listboxId = el.getAttribute("aria-controls") || el.getAttribute("aria-owns");
        const listbox = listboxId ? document.getElementById(listboxId) : null;
        if (listbox) {
          const optionEls = listbox.querySelectorAll('[role="option"], li, .sapMSelectListItem, .sapMSLI');
          if (optionEls.length) {
            options = Array.from(optionEls).map((o) => ({
              value: o.getAttribute("data-sap-ui") || o.getAttribute("id") || o.getAttribute("data-key") || (o.innerText || "").trim(),
              text: (o.innerText || o.textContent || "").trim(),
            }));
          }
        }
        // Fallback: backing native <select> inside the wrapper
        if (!options) {
          const backingSelect = el.querySelector("select");
          if (backingSelect) {
            options = Array.from(backingSelect.options).map((opt) => ({
              value: opt.value,
              text: (opt.text || "").trim(),
            }));
          }
        }
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

      if (typeof inputEl.onchange === "function") {
        try { inputEl.onchange(new Event("change", { bubbles: true })); } catch (e) {}
      }

      // Also dispatch drop event on surrounding dropzone/multiAttachment container if present
      const dropzone = inputEl.closest(".multiAttachmentWidget, .dropzone, [class*='upload'], [class*='drop'], [class*='attachment']");
      if (dropzone) {
        try {
          const dropEvt = new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt });
          dropzone.dispatchEvent(dropEvt);
        } catch (e) {}
        highlightField(dropzone);
      }

      highlightField(inputEl);
      console.log(`[JobAgent Copilot] 📎 Uploaded '${docObj.filename}' (${(docObj.sizeBytes / 1024).toFixed(1)} KB) to file input:`, inputEl);
      return true;
    } catch (e) {
      console.warn("[JobAgent Copilot] File upload error:", e);
      return false;
    }
  }

  function uploadDocumentToDropzone(dropzoneEl, docObj) {
    if (!dropzoneEl || !docObj?.dataUrl || !docObj?.filename) return false;
    try {
      const file = dataUrlToFile(docObj.dataUrl, docObj.filename);
      if (!file) return false;
      const dt = new DataTransfer();
      dt.items.add(file);

      // Check if dropzone contains or associates with a file input
      const nestedInput = dropzoneEl.querySelector("input[type='file']") ||
        (dropzoneEl.id ? document.querySelector(`input[type='file'][aria-labelledby*='${dropzoneEl.id}']`) : null);
      if (nestedInput) {
        uploadDocumentToInput(nestedInput, docObj);
      }

      // Dispatch full Drag and Drop lifecycle events
      const dragEnter = new DragEvent("dragenter", { bubbles: true, cancelable: true, dataTransfer: dt });
      const dragOver = new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: dt });
      const drop = new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt });

      dropzoneEl.dispatchEvent(dragEnter);
      dropzoneEl.dispatchEvent(dragOver);
      dropzoneEl.dispatchEvent(drop);

      highlightField(dropzoneEl);
      console.log(`[JobAgent Copilot] 📦 Dispatched drop event with '${docObj.filename}' (${(docObj.sizeBytes / 1024).toFixed(1)} KB) to dropzone:`, dropzoneEl);
      return true;
    } catch (e) {
      console.warn("[JobAgent Copilot] Dropzone upload error:", e);
      return false;
    }
  }

  function triggerMainWorldSync(el, val) {
    if (!el || !el.id) return;
    try {
      const script = document.createElement("script");
      script.textContent = `
        (function() {
          try {
            var el = document.getElementById(${JSON.stringify(el.id)});
            if (!el) return;
            if (window.jQuery) {
              window.jQuery(el).val(${JSON.stringify(val)}).trigger("change").trigger("input");
            }
            if (window.sap && window.sap.ui) {
              var core = window.sap.ui.getCore();
              var ctrl = (core && core.byId) ? core.byId(el.id) : null;
              if (!ctrl && window.jQuery && window.jQuery(el).control) {
                ctrl = window.jQuery(el).control()[0];
              }
              if (ctrl) {
                if (typeof ctrl.setSelectedKey === "function") ctrl.setSelectedKey(${JSON.stringify(val)});
                if (typeof ctrl.setValue === "function") ctrl.setValue(${JSON.stringify(val)});
                if (typeof ctrl.fireChange === "function") ctrl.fireChange();
              }
            }
          } catch (e) {}
        })();
      `;
      (document.head || document.documentElement).appendChild(script);
      script.remove();
    } catch (e) {}
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
      let matchedIndex = -1;
      const cleanTarget = strVal.toLowerCase();
      const isYes = ["yes", "ja", "true", "1", "t"].includes(cleanTarget) || /^(yes|ja|true|1|y)\b/i.test(cleanTarget);
      const isNo = ["no", "nein", "false", "0", "f"].includes(cleanTarget) || /^(no|nein|false|0|n)\b/i.test(cleanTarget);
      const isDePhone = ["+49", "49", "0049"].includes(cleanTarget);
      const isGermany = ["deutschland", "germany", "de", "deu"].includes(cleanTarget);
      const cefrToken = (strVal.match(/\b([a-c][12])\b/i)?.[1] || "").toLowerCase();

      for (let i = 0; i < el.options.length; i++) {
        const opt = el.options[i];
        const optVal = (opt.value || "").toLowerCase().trim();
        const optTxt = (opt.text || "").toLowerCase().trim();

        // Skip placeholder prompt options (e.g. "Keine Auswahl", "Bitte wählen", "Select").
        // Detection is intentionally text-only: some portals (e.g. SAP SuccessFactors) use
        // non-empty, non-numeric option values (GUIDs, "NONDISCLOSURE") for placeholders,
        // so checking optVal alone is not sufficient.
        const isPlaceholder = /^(keine.*auswahl|bitte.*wählen|bitte.*wähle|please.*select|select\.{0,3}$|choose\.{0,3}$|---)/i.test(optTxt.trim());
        if (isPlaceholder) {
          continue;
        }

        // 1. Semantic Yes/No matching
        if (isYes) {
          if (["ja", "yes", "1", "y", "true", "t"].includes(optVal) ||
              optTxt === "ja" || optTxt === "yes" || optTxt.startsWith("ja ") || optTxt.startsWith("ja,") || optTxt.startsWith("yes ") || optTxt.includes("vorhanden") || optTxt.includes("uneingeschränkt") || /besitze.*arbeitserlaubnis|gültige.*arbeitserlaubnis/i.test(optTxt)) {
            matchedIndex = i;
            break;
          }
        } else if (isNo) {
          if (["nein", "no", "false", "f", "n"].includes(optVal) ||
              optTxt === "nein" || optTxt === "no" || optTxt.startsWith("nein ") || optTxt.startsWith("nein,") || optTxt.startsWith("no ") || (/nein/i.test(optTxt) && !/auswahl/i.test(optTxt))) {
            matchedIndex = i;
            break;
          }
        }
        // 2. Phone country prefix (+49 -> Deutschland (+49))
        else if (isDePhone) {
          if (optTxt.includes("+49") || optTxt.includes("deutschland (+49)") || optVal === "de" || optVal === "+49" || optVal === "49") {
            matchedIndex = i;
            break;
          }
        }
        // 3. Country of residence (Deutschland / Germany)
        else if (isGermany) {
          if (/\b(deutschland|germany)\b/i.test(optTxt) || optVal === "de" || optVal === "deu" || optVal === "deutschland" || optVal === "germany") {
            matchedIndex = i;
            break;
          }
        }
        // 4. CEFR language level matching
        else if (cefrToken && (new RegExp(`\\b${cefrToken}\\b`, "i").test(optTxt) || new RegExp(`\\b${cefrToken}\\b`, "i").test(optVal))) {
          matchedIndex = i;
          break;
        }
        // 5. Exact or substring match
        else {
          if (optVal === cleanTarget || optTxt === cleanTarget || (cleanTarget && (optTxt.includes(cleanTarget) || cleanTarget.includes(optTxt)))) {
            matchedIndex = i;
            break;
          }
        }
      }

      if (matchedIndex >= 0) {
        const selectedOpt = el.options[matchedIndex];
        if (selectedOpt) {
          selectedOpt.selected = true;
          el.selectedIndex = matchedIndex;
          el.value = selectedOpt.value;

          // Update SAP UI5 / custom dropdown visible display label if present
          const container = el.closest(".sapMSlt, [class*='select'], [class*='combobox'], .form-group, .field, td, div");
          if (container) {
            const labelSpan = container.querySelector(".sapMSltLabel, [class*='label'], span");
            if (labelSpan && !labelSpan.querySelector("select, input")) {
              labelSpan.innerText = selectedOpt.text;
            }
            // Remove error highlight styling from container
            container.classList.remove("sapMInputBaseError", "sapMValidationError", "has-error", "error");
            const errElem = container.querySelector(".sapMInputBaseMessage, .error-message, [class*='error']");
            if (errElem && !errElem.contains(el)) errElem.style.display = "none";
          }
        }
        el.dispatchEvent(new Event("focus", { bubbles: true }));
        el.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
        el.dispatchEvent(new Event("change", { bubbles: true, cancelable: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true, cancelable: true }));
        triggerMainWorldSync(el, selectedOpt.value);
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
        const cefrToken = (strVal.match(/\b([a-c][12])\b/i)?.[1] || "").toLowerCase();

        for (const r of radios) {
          const rVal = (r.value || "").toLowerCase();
          const rLbl = (r.id ? document.querySelector(`label[for='${CSS.escape(r.id)}']`) : r.closest("label"))?.innerText?.toLowerCase() || "";

          const isMatch = (rVal === cleanTarget) ||
            rLbl.includes(cleanTarget) ||
            (cleanTarget && (cleanTarget.includes(rVal) || rVal.includes(cleanTarget))) ||
            (cefrToken && (new RegExp(`\\b${cefrToken}\\b`, "i").test(rLbl) || new RegExp(`\\b${cefrToken}\\b`, "i").test(rVal)));

          if (isMatch) {
            r.checked = true;
            r.click();
            r.dispatchEvent(new Event("input", { bubbles: true }));
            r.dispatchEvent(new Event("change", { bubbles: true }));
            triggerMainWorldSync(r, r.value);
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
        if (!el.checked) {
          el.click();
        }
        el.checked = true;
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
        triggerMainWorldSync(el, "true");
        highlightField(el);
        return true;
      }
      return false;
    }

    // Standard input, email, tel, text, textarea:
    try {
      const proto = Object.getPrototypeOf(el);
      const isTextarea = tag === "textarea";
      const protoDesc = Object.getOwnPropertyDescriptor(proto, "value");
      const defaultDesc = isTextarea
        ? (window.HTMLTextAreaElement ? Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value") : null)
        : (window.HTMLInputElement ? Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value") : null);
      const desc = protoDesc || defaultDesc;
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
    triggerMainWorldSync(el, strVal);
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
  function markForReview(el) {
    // Visible marker: dashed amber border + tooltip telling the user to answer
    // manually. Used for legally significant questions that must not be
    // auto-answered with fabricated values.
    try {
      el.style.border = "2px dashed #f59e0b";
      el.title = "⚠️ Legally significant question — please answer manually";
    } catch (e) {}
  }

  function localFallbackFill(schema, elementMap, profile, documents) {
    let filledCount = 0;
    let reviewCount = 0;
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

      const isSelect = el.tagName.toLowerCase() === "select";
      const selectVal = isSelect ? (el.value || "").toLowerCase().trim() : "";
      const isSelectPlaceholder = isSelect && (
        !selectVal || selectVal === "-1" || selectVal === "0" || selectVal === "none" ||
        /keine.*auswahl|select|bitte|choose/i.test(el.options[el.selectedIndex]?.text || "")
      );
      if (el.value && (!isSelect || !isSelectPlaceholder)) continue;

      let val = null;

      // 1. Middle Name (Zweiter Vorname) - MUST be evaluated before First Name!
      if (/zweiter.*vorname|middle.*name|weitere.*vornamen/i.test(desc)) {
        val = pers.middleName || "";
        applyValueToElement(el, val);
        continue;
      }
      // 2. First Name
      else if ((/first.*name|vorname|given.*name/i.test(desc)) && !/zweiter|middle|weitere/i.test(desc)) {
        val = pers.firstName || (pers.fullName ? pers.fullName.split(" ")[0] : "");
      }
      // 3. Last Name
      else if (/last.*name|nachname|familienname|surname/i.test(desc)) {
        val = pers.lastName || ((pers.fullName || "").split(" ").slice(1).join(" "));
      }
      // 4. Full Name
      else if (/full.*name|ihr.*name|name/i.test(desc) && !/company|file|user|firma|datei|benutzer|first|last|vorname|nachname|zweiter|middle/i.test(desc)) {
        val = pers.fullName;
      }
      // 5. Country Dialing Prefix (Länder-/Regionsvorwahl)
      else if (/länder.*vorwahl|regionsvorwahl|country.*code|vorwahl|dialing.*code/i.test(desc)) {
        val = pers.phoneCountryCode || "";
      }
      // 6. Phone Number
      else if (/phone|telefon|mobile|handy|rufnummer/i.test(desc) || f.type === "tel") {
        val = pers.phone;
      }
      // 7. Country of Residence (Land des aktuellen Wohnsitzes)
      else if (/aktuell.*wohnsitz|country.*residence|wohnsitz|land.*wohnsitz/i.test(desc)) {
        val = pers.countryDe || pers.countryEn || "";
      }
      // 8. Work Authorization (Arbeitserlaubnis in dem Land)
      else if (/arbeitserlaubnis|work.*authorization|legal.*right.*to.*work|erlaubnis.*in.*dem.*land/i.test(desc)) {
        val = pers.workAuthorizationDe || pers.workAuthorizationEn || "Ja";
        markForReview(el);
        reviewCount++;
      }
      // 9. Previously Employed (Warst du bereits bei der ... Gruppe angestellt?)
      else if (/bereits.*angestellt|previously.*employed|bereits.*gearbeitet|früher.*angestellt|früher.*beschäftigt/i.test(desc) || (/bereits/i.test(desc) && /angestellt|gearbeitet|beschäftigt/i.test(desc))) {
        val = "Nein";
      }
      // 10. Preferred Job Location / Standort (Not residential street)
      else if (/welchen standort|bevorzugter standort|gewünschter standort/i.test(desc) || (desc.includes("standort") && /bewerben|primär|wunsch|arbeiten/i.test(desc))) {
        val = profile?.jobSearch?.preferredLocations?.[0] || profile?.preferences?.locations?.[0] || pers.city || null;
      }
      // 11. Language Proficiency (Dynamic from candidate's profile configuration - any language)
      else if (/kenntnis|wie gut|niveau|sprach|level|proficiency|skills/i.test(desc)) {
        const langs = profile?.languages || {};
        for (const [langKey, langVal] of Object.entries(langs)) {
          if (!langVal) continue;
          const k = langKey.toLowerCase().trim();
          const aliases = [k];
          if (k === "german" || k === "deutsch") aliases.push("deutsch", "german");
          else if (k === "english" || k === "englisch") aliases.push("englisch", "english");
          else if (k === "french" || k === "französisch" || k === "franzosisch") aliases.push("französisch", "franzosisch", "french");
          else if (k === "spanish" || k === "spanisch") aliases.push("spanisch", "spanish");
          else if (k === "hungarian" || k === "ungarisch") aliases.push("ungarisch", "hungarian");
          else if (k === "italian" || k === "italienisch") aliases.push("italienisch", "italian");

          if (aliases.some(alias => desc.includes(alias))) {
            val = langVal;
            break;
          }
        }
      }
      // 12. Email Address
      else if (/email|e-mail|mail.*adresse/i.test(desc) || f.type === "email") {
        val = pers.email;
      }
      // 13. Address & Location
      else if (/city|ort|stadt|wohnort/i.test(desc)) {
        val = pers.city || ((pers.address || "").split(",")[1] || "").replace(/^\s*\d{4,5}\s*/, "").trim() || "";
      } else if (/address|adresse|straße|strasse|hausnummer/i.test(desc)) {
        val = pers.street || pers.address;
      } else if (/zip|plz|postleitzahl|postal/i.test(desc)) {
        val = pers.postalCode || ((pers.address || "").match(/\b\d{5}\b/)?.[0] || "");
      }
      // 14. Salary Expectation — may autofill from the profile but requires confirmation
      else if (/salary|gehalt|gehaltsvorstellung|compensation|vergütung/i.test(desc)) {
        val = pers.salaryExpectation;
        if (val) {
          markForReview(el);
          reviewCount++;
        }
      }
      // 15. Notice Period / Availability
      else if (/notice|kündigungsfrist|verfügbar|availability|start.*date|eintritt/i.test(desc)) {
        val = pers.noticePeriod;
        if (val) {
          markForReview(el);
          reviewCount++;
        }
      }
      // 16. Links
      else if (/linkedin/i.test(desc)) {
        val = pers.linkedin || pers.linkedinUrl;
      } else if (/github/i.test(desc)) {
        val = pers.github || pers.githubUrl;
      }
      // 17. Checkboxes: Notifications & Consent
      else if (/job.*alert|job-angebot|benachrichtigung/i.test(desc) && f.type === "checkbox") {
        val = "true";
      }
      else if (/datenschutz|datenschutzerklärung|privacy/i.test(desc) && f.type === "checkbox") {
        val = "true";
      }
      // 18. Professional Headline (LinkedIn Easy Apply Headline input)
      else if (/headline|berufsbezeichnung|professional.*headline|profil-slogan|kurztitel/i.test(desc)) {
        val = pers.headline || profile?.jobSearch?.headline || profile?.preferences?.targetRoles?.[0] || "Senior Software Engineer / Tech Lead";
      }
      // 19. Profile Summary / Bio / About Me (LinkedIn Easy Apply Summary textarea)
      else if (/summary|zusammenfassung|profilzusammenfassung|über mich|ueber mich|about.*me|kurzprofil|bio/i.test(desc)) {
        const isDe = /zusammenfassung|über mich|ueber mich|kurzprofil/i.test(desc);
        val = (isDe ? pers.summaryDe : (pers.summaryEn || pers.summaryDe)) || pers.summaryDe || pers.summaryEn || "";
      }
      // 20. Text Cover Letter / Motivation / Essay (Textarea)
      else if (/anschreiben|cover.*letter|coverletter|motivation|warum.*bewerben|why.*join|essay/i.test(desc)) {
        const isDe = /anschreiben|warum.*bewerben/i.test(desc);
        val = (isDe ? pers.coverLetterDe : (pers.coverLetterEn || pers.coverLetterDe)) || pers.coverLetterDe || pers.coverLetterEn || "";
      }

      if (val !== null && applyValueToElement(el, val)) {
        filledCount++;
      }
    }

    // Documents are attached separately as an async step in performAutofill
    if (reviewCount > 0) {
      console.log(`[JobAgent Copilot] ⚠️ ${reviewCount} legally significant question(s) left empty and marked for human review.`);
    }
    return filledCount;
  }

  // ---------------------------------------------------------------------------
  // SAP SuccessFactors / Workday widget helpers
  // ---------------------------------------------------------------------------

  /**
   * Waits for a file input to appear inside `containerEl` (or document) within
   * `timeoutMs`. Used for SAP SuccessFactors' multiAttachmentWidget whose
   * <input type="file"> is dynamically injected ONLY after the "hochladen"
   * button click opens a file-picker — we observe the DOM instead of clicking
   * the button ourselves (which would open the native OS dialog).
   *
   * If no input appears, resolves with null so the caller can fall back
   * gracefully.
   */
  function waitForFileInput(containerEl, timeoutMs = 800) {
    return new Promise((resolve) => {
      // Already present?
      const existing = containerEl.querySelector("input[type='file']");
      if (existing) return resolve(existing);

      const timer = setTimeout(() => {
        observer.disconnect();
        resolve(null);
      }, timeoutMs);

      const observer = new MutationObserver(() => {
        const found = containerEl.querySelector("input[type='file']");
        if (found) {
          clearTimeout(timer);
          observer.disconnect();
          resolve(found);
        }
      });
      observer.observe(containerEl, { childList: true, subtree: true });
    });
  }

  /**
   * Attaches CV and cover-letter documents to all discoverable file inputs on
   * the page, including hidden/transparent ones (SAP UI5 FileUploader pattern)
   * and those inside accessible iframes.
   *
   * Strategy:
   *   Phase 1 – Direct hidden-input injection: query ALL file inputs (including
   *             opacity:0 / display:none) and try programmatic DataTransfer.
   *   Phase 2 – SAP widget click: if phase 1 finds nothing, click the upload
   *             button on each widget and watch for the dynamically injected
   *             <input> via MutationObserver (avoids opening the OS file dialog).
   *   Phase 3 – Dropzone drag-and-drop fallback.
   */
  async function attachDocumentsToPage(documents) {
    if (!documents || (!documents.cv && !documents.coverLetter)) {
      console.log("[JobAgent Copilot] No document bundle available to upload.");
      return 0;
    }
    let attachedCount = 0;
    let cvAttached = false;
    let clAttached = false;

    // ── Phase 1: direct hidden-input injection ────────────────────────────────
    // `querySelectorAll` finds inputs regardless of visibility/opacity.
    const allFileInputs = Array.from(document.querySelectorAll("input[type='file']"));
    const iframes = Array.from(document.querySelectorAll("iframe"));
    for (const ifr of iframes) {
      try {
        if (ifr.contentDocument) {
          allFileInputs.push(...Array.from(ifr.contentDocument.querySelectorAll("input[type='file']")));
        }
      } catch (e) {}
    }

    console.log(`[JobAgent Copilot] 📂 Found ${allFileInputs.length} file input(s) on page (phase 1).`);

    for (let idx = 0; idx < allFileInputs.length; idx++) {
      const el = allFileInputs[idx];
      if (el.files && el.files.length > 0) continue;

      const container = el.closest(".multiAttachmentWidget, .file-upload, [class*='upload'], [class*='attachment'], .form-group, .field, td, div") || el.parentElement;
      const contextText = `${getFieldLabel(el)} ${el.name} ${el.id} ${el.placeholder} ${container?.innerText || ""}`.toLowerCase();

      if (/anschreiben|cover.*letter|motivation/i.test(contextText)) {
        if (documents.coverLetter && uploadDocumentToInput(el, documents.coverLetter)) {
          attachedCount++;
          clAttached = true;
        }
      } else if (/lebenslauf|cv|resume|curriculum/i.test(contextText)) {
        if (documents.cv && uploadDocumentToInput(el, documents.cv)) {
          attachedCount++;
          cvAttached = true;
        }
      } else {
        // Fallback: first unknown input → CV, second → cover letter
        if (idx === 0 && documents.cv && !cvAttached) {
          if (uploadDocumentToInput(el, documents.cv)) {
            attachedCount++;
            cvAttached = true;
          }
        } else if (idx === 1 && documents.coverLetter && !clAttached) {
          if (uploadDocumentToInput(el, documents.coverLetter)) {
            attachedCount++;
            clAttached = true;
          }
        }
      }
    }

    // ── Phase 2: SAP widget click → body-level MutationObserver ─────────────
    // SAP UI5 FileUploader does NOT keep a persistent hidden input in the DOM.
    // Instead it appends a temporary <input type="file"> to <body> just before
    // calling .click() internally. We click the upload button and watch
    // document.body for ANY new file input appearing anywhere — before the
    // browser has a chance to show the OS file-picker dialog.
    if (!cvAttached || !clAttached) {
      const CV_BTN = /lebenslauf.*hochladen|upload.*cv|upload.*resume|cv.*hochladen/i;
      const CL_BTN = /anschreiben.*anh[\u00e4a]ngen|cover.*letter/i;
      const widgetBtns = Array.from(document.querySelectorAll(
        ".multiAttachmentWidget button, [class*='uploadBtn'] button, " +
        "[class*='attachmentUpload'] button, [class*='sapUiUfdFU'] button, " +
        "button[id*='lebenslauf' i], button[id*='anschreiben' i], " +
        "button[aria-label*='hochladen' i], button[title*='hochladen' i]"
      ));

      for (const btn of widgetBtns) {
        const btnTxt = (btn.innerText || btn.title || btn.getAttribute("aria-label") || "").trim();
        const isCV = CV_BTN.test(btnTxt) && !clAttached === false; // cleaner: explicit
        const isCVBtn = !cvAttached && documents.cv && CV_BTN.test(btnTxt);
        const isCLBtn = !clAttached && documents.coverLetter && CL_BTN.test(btnTxt);

        if (!isCVBtn && !isCLBtn) continue;

        // Watch document.body for a new file input BEFORE clicking
        const inputPromise = waitForFileInput(document.body, 700);
        btn.click();
        const input = await inputPromise;
        if (input) {
          if (isCVBtn && uploadDocumentToInput(input, documents.cv)) {
            attachedCount++;
            cvAttached = true;
            console.log("[JobAgent Copilot] 📎 CV injected via body MutationObserver");
          } else if (isCLBtn && uploadDocumentToInput(input, documents.coverLetter)) {
            attachedCount++;
            clAttached = true;
            console.log("[JobAgent Copilot] 📎 Cover letter injected via body MutationObserver");
          }
        }
      }
    }

    // ── Phase 3: dropzone drag-and-drop fallback ──────────────────────────────
    if (!cvAttached || !clAttached) {
      const dropzones = Array.from(document.querySelectorAll(
        ".multiAttachmentWidget, [class*='dropzone'], [class*='upload-box'], " +
        "[class*='attachment-widget'], div[title*='hochladen'], div[title*='upload']"
      ));
      // Also catch elements whose inner text signals CV/cover-letter upload
      const textNodes = Array.from(document.querySelectorAll("div, button, a")).filter((el) => {
        const t = (el.innerText || "").toLowerCase().trim();
        return (
          t.includes("lebenslauf hochladen") ||
          t.includes("anschreiben anhängen") ||
          t.includes("upload resume") ||
          t.includes("upload cv")
        ) && el.children.length <= 4;
      });
      for (const tc of textNodes) {
        if (!dropzones.includes(tc)) dropzones.push(tc);
      }

      for (const dz of dropzones) {
        const dzText = `${dz.innerText || ""} ${dz.className || ""} ${dz.id || ""} ${dz.getAttribute("title") || ""}`.toLowerCase();
        if (!cvAttached && documents.cv && /lebenslauf|cv|resume|curriculum/i.test(dzText)) {
          if (uploadDocumentToDropzone(dz, documents.cv)) {
            attachedCount++;
            cvAttached = true;
          }
        } else if (!clAttached && documents.coverLetter && /anschreiben|cover.*letter|motivation/i.test(dzText)) {
          if (uploadDocumentToDropzone(dz, documents.coverLetter)) {
            attachedCount++;
            clAttached = true;
          }
        }
      }
    }

    return attachedCount;
  }

  /**
   * Sets a SAP UI5 Select (sap.m.Select / sap.m.ComboBox) to a target value by
   * simulating real user interaction — open the popup, click the matching item.
   *
   * This is required because SAP UI5 Select controls DO NOT react to programmatic
   * changes of the backing native <select> element's selectedIndex; the component
   * maintains its own internal model that only updates through click events.
   *
   * Falls back gracefully (closes the popup) if no match is found.
   *
   * @param {Element} sapWrapper   The element with role="combobox" or .sapMSlt class.
   * @param {string}  targetText   The visible text to match (not the option value).
   * @returns {Promise<boolean>}   True if an option was clicked successfully.
   */
  async function applyValueToSapUi5Select(sapWrapper, targetText) {
    try {
      const target = targetText.toLowerCase().trim();
      if (!target) return false;

      // Open the dropdown
      sapWrapper.click();
      await new Promise((r) => setTimeout(r, 380));

      // SAP UI5 renders the list as a global floating layer, NOT inside the wrapper
      const popup = document.querySelector(
        '.sapMSelectList:not([style*="display: none"]):not([aria-hidden="true"]), ' +
        '.sapMSltPicker:not([style*="display: none"]):not([aria-hidden="true"]), ' +
        '[role="listbox"]:not([aria-hidden="true"])'
      );
      if (!popup) {
        document.body.click(); // close any half-open state
        return false;
      }

      const items = Array.from(popup.querySelectorAll(
        'li, [role="option"], .sapMSelectListItem, .sapMSLI'
      ));

      // Pass 1 – exact match
      for (const item of items) {
        const txt = (item.innerText || item.textContent || "").trim().toLowerCase();
        if (/keine.*auswahl|bitte.*w[äa]hl|please.*select/i.test(txt)) continue;
        if (txt === target) {
          item.click();
          await new Promise((r) => setTimeout(r, 80));
          console.log("[JobAgent Copilot] ✅ SAP UI5 select (exact):", txt);
          return true;
        }
      }
      // Pass 2 – substring match
      for (const item of items) {
        const txt = (item.innerText || item.textContent || "").trim().toLowerCase();
        if (/keine.*auswahl|bitte.*w[äa]hl|please.*select/i.test(txt)) continue;
        if (txt.includes(target) || target.includes(txt)) {
          item.click();
          await new Promise((r) => setTimeout(r, 80));
          console.log("[JobAgent Copilot] ✅ SAP UI5 select (partial):", txt);
          return true;
        }
      }

      // No match — dismiss the popup cleanly
      const closeBtn = popup.closest("[class*='Picker'], [class*='picker']")?.querySelector("[class*='Close'], button[aria-label*='schließen' i], button[aria-label*='close' i]");
      if (closeBtn) closeBtn.click();
      else document.body.click();
      return false;
    } catch (e) {
      console.warn("[JobAgent Copilot] SAP UI5 select error:", e);
      return false;
    }
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
    console.log("[JobAgent Copilot] Documents payload received:", documents ? Object.keys(documents) : "none");

    // NOTE: async so we can await SAP UI5 click simulation + document upload
    async function handleReasoningResult(data, method) {
      let filledCount = 0;
      const mappings = data.mappings || {};
      const requiresConfirm = new Set(data.requires_confirmation || []);
      const sapSelectQueue = []; // selects inside SAP UI5 wrappers — need click simulation

      for (const [fieldId, val] of Object.entries(mappings)) {
        const el = elementMap.get(fieldId);
        if (!el) continue;

        if (applyValueToElement(el, val)) {
          filledCount++;
          if (requiresConfirm.has(fieldId)) {
            el.style.border = "2px dashed #f59e0b";
            el.title = "⚠️ Legally sensitive field: please confirm before submitting";
          }
        }

        // Queue elements that need SAP UI5 click simulation:
        // - [role="combobox"] divs (SAP UI5 Select wrapper, the main element extracted)
        // - native <select> elements inside a SAP wrapper (less common)
        const isComboboxDiv = el.getAttribute?.("role") === "combobox";
        const isNativeSelectInSap = el.tagName?.toLowerCase() === "select" && !!el.closest?.('[role="combobox"], .sapMSlt');

        if (isComboboxDiv || isNativeSelectInSap) {
          const wrapper = isComboboxDiv ? el : el.closest('[role="combobox"], .sapMSlt');
          if (wrapper) {
            sapSelectQueue.push({ val: String(val), wrapper });
          }
        }
      }

      // ── Post-process SAP UI5 selects via click simulation ─────────────────
      for (const { val, wrapper } of sapSelectQueue) {
        // Check current visible label — use wrapper's inner text as a proxy
        const labelEl = wrapper.querySelector(".sapMSltLabel, [class*='Label'], [class*='label'], span");
        const visibleText = (labelEl?.innerText || labelEl?.textContent || wrapper.innerText || "").trim();
        if (/keine.*auswahl|bitte|please.*select|^$/i.test(visibleText.split('\n')[0])) {
          const ok = await applyValueToSapUi5Select(wrapper, val);
          if (ok) filledCount++;
        }
      }

      // ── Document uploads (async, includes MutationObserver wait) ──────────
      const docsAttached = await attachDocumentsToPage(documents);
      filledCount += docsAttached;

      console.log(`[JobAgent Copilot] Form fill complete (${method}). Filled ${filledCount} fields (incl. ${docsAttached} docs).`);
      if (sendResponse) {
        sendResponse({
          filledCount,
          method,
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

          // Message proxy failed or server offline — fall back to local engine
          console.log("[JobAgent Copilot] Message proxy unavailable, falling back to local engine...");
          const count = localFallbackFill(schema, elementMap, profile, documents);
          attachDocumentsToPage(documents).then((docsAttached) => {
            if (sendResponse) {
              sendResponse({
                filledCount: count + docsAttached,
                method: "Local Candidate Engine",
                totalFields: schema.length,
              });
            }
          });
        }
      );
      return;
    }

    // Direct local fallback (no chrome.runtime)
    const count = localFallbackFill(schema, elementMap, profile, documents);
    attachDocumentsToPage(documents).then((docsAttached) => {
      if (sendResponse) {
        sendResponse({
          filledCount: count + docsAttached,
          method: "Local Candidate Engine",
          totalFields: schema.length,
        });
      }
    });
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

  // ---------------------------------------------------------------------------
  // 7. Dynamic In-Modal Helper Button (e.g. for LinkedIn Easy Apply Multi-Step Popups)
  // ---------------------------------------------------------------------------
  function attachModalAutofillButton() {
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

      // Retrieve cached profile AND configured gateway URL from extension storage
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

      performAutofill(
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
    });

    if (window.getComputedStyle(container).position === "static") {
      container.style.position = "relative";
    }
    container.appendChild(btn);
  }

  // Observe DOM for modal dialog appearances (e.g. clicking 'Einfach bewerben')
  try {
    const modalObserver = new MutationObserver(() => {
      attachModalAutofillButton();
    });
    modalObserver.observe(document.body, { childList: true, subtree: true });
    // Initial probe
    attachModalAutofillButton();
  } catch (e) {}

  // JobAgent Copilot content script — no window-level "message" listeners.
  // All communication uses chrome.runtime.onMessage (extension-private, invisible
  // to page scripts and third-party iframes).
})();
