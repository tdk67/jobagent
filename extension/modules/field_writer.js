// JobAgent Copilot - Field Writer Module
// Applies values to DOM inputs, selects, radios, checkboxes, and SAP UI5 / enterprise controls

(function () {
  "use strict";

  window.JobAgent = window.JobAgent || {};

  function highlightField(el) {
    if (!el) return;
    try {
      el.style.transition = "box-shadow 0.4s ease, border-color 0.4s ease";
      el.style.boxShadow = "0 0 8px rgba(16, 185, 129, 0.7)";
      el.style.borderColor = "#10b981";
      setTimeout(() => {
        el.style.boxShadow = "";
      }, 2500);
    } catch (e) {}
  }

  function markForReview(el) {
    if (!el) return;
    try {
      el.style.border = "2px dashed #f59e0b";
      el.title = "⚠️ Legally significant question — please answer manually";
    } catch (e) {}
  }

  function applyValueToElement(el, val) {
    if (!el || val === undefined || val === null) return false;
    const tag = el.tagName.toLowerCase();
    const type = (el.type || tag).toLowerCase();
    const strVal = String(val).trim();

    if (type === "file") {
      if (typeof val === "object" && val?.dataUrl && window.JobAgent.uploadDocumentToInput) {
        return window.JobAgent.uploadDocumentToInput(el, val);
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

        const isPlaceholder = /^(keine.*auswahl|bitte.*wählen|bitte.*wähle|please.*select|select\.{0,3}$|choose\.{0,3}$|---)/i.test(optTxt.trim());
        if (isPlaceholder) continue;

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
        } else if (isDePhone) {
          if (optTxt.includes("+49") || optTxt.includes("deutschland (+49)") || optVal === "de" || optVal === "+49" || optVal === "49") {
            matchedIndex = i;
            break;
          }
        } else if (isGermany) {
          if (/\b(deutschland|germany)\b/i.test(optTxt) || optVal === "de" || optVal === "deu" || optVal === "deutschland" || optVal === "germany") {
            matchedIndex = i;
            break;
          }
        } else if (cefrToken && (new RegExp(`\\b${cefrToken}\\b`, "i").test(optTxt) || new RegExp(`\\b${cefrToken}\\b`, "i").test(optVal))) {
          matchedIndex = i;
          break;
        } else {
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

          const container = el.closest(".sapMSlt, [class*='select'], [class*='combobox'], .form-group, .field, td, div");
          if (container) {
            const labelSpan = container.querySelector(".sapMSltLabel, [class*='label'], span");
            if (labelSpan && !labelSpan.querySelector("select, input")) {
              labelSpan.innerText = selectedOpt.text;
            }
            container.classList.remove("sapMInputBaseError", "sapMValidationError", "has-error", "error");
            const errElem = container.querySelector(".sapMInputBaseMessage, .error-message, [class*='error']");
            if (errElem && !errElem.contains(el)) errElem.style.display = "none";
          }
        }
        el.dispatchEvent(new Event("focus", { bubbles: true }));
        el.dispatchEvent(new Event("input", { bubbles: true, cancelable: true }));
        el.dispatchEvent(new Event("change", { bubbles: true, cancelable: true }));
        el.dispatchEvent(new Event("blur", { bubbles: true, cancelable: true }));
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
        highlightField(el);
        return true;
      }
      return false;
    }

    if (tag === "div" || el.getAttribute("role") === "combobox") {
      return false;
    }

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
    highlightField(el);
    return true;
  }

  async function applyValueToSapUi5Select(sapWrapper, targetText) {
    try {
      const target = (targetText || "").toLowerCase().trim();
      if (!target) return false;

      const trigger = sapWrapper.querySelector(
        ".sapMSltArrow, .sapMCbArrow, [id$='-arrow'], [id$='-trigger'], [id$='-icon'], button, .sapMInputBaseIcon"
      ) || sapWrapper;
      trigger.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
      trigger.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
      trigger.click();

      const popupSelectors = [
        '.sapMSelectList:not([style*="display: none"]):not([aria-hidden="true"])',
        '.sapMSltPicker:not([style*="display: none"]):not([aria-hidden="true"])',
        '.sapMPicker:not([style*="display: none"]):not([aria-hidden="true"])',
        '.sapMPopover:not([style*="display: none"]):not([aria-hidden="true"])',
        '.sapMDialog:not([style*="display: none"]):not([aria-hidden="true"])',
        '[id$="-picker"]:not([style*="display: none"]):not([aria-hidden="true"])',
        '[id$="-popup"]:not([style*="display: none"]):not([aria-hidden="true"])',
        '[role="listbox"]:not([aria-hidden="true"])'
      ];

      let popup = null;
      for (let i = 0; i < 6; i++) {
        popup = document.querySelector(popupSelectors.join(", "));
        if (popup) break;
        await new Promise((r) => setTimeout(r, 80));
      }

      if (!popup) {
        document.body.click();
        return false;
      }

      const items = Array.from(popup.querySelectorAll(
        'li, [role="option"], .sapMSelectListItem, .sapMSLI, .sapMCLI, [id$="-items"] > *'
      ));

      const isYes = ["yes", "ja", "true", "1", "t"].includes(target) || /^(yes|ja|true|1|y)\b/i.test(target);
      const isNo = ["no", "nein", "false", "0", "f"].includes(target) || /^(no|nein|false|0|n)\b/i.test(target);
      const isDePhone = ["+49", "49", "0049"].includes(target) || target.includes("+49");
      const isGermany = ["deutschland", "germany", "de", "deu"].includes(target);

      let matchedItem = null;

      for (const item of items) {
        const txt = (item.innerText || item.textContent || "").trim().toLowerCase();
        if (/keine.*auswahl|bitte.*w[äa]hl|please.*select/i.test(txt)) continue;

        if (isYes && (txt === "ja" || txt === "yes" || txt.startsWith("ja ") || txt.startsWith("yes ") || txt.startsWith("ja,"))) {
          matchedItem = item;
          break;
        }
        if (isNo && (txt === "nein" || txt === "no" || txt.startsWith("nein ") || txt.startsWith("no ") || txt.startsWith("nein,"))) {
          matchedItem = item;
          break;
        }
        if (isDePhone && (txt.includes("+49") || txt.includes("deutschland (+49)"))) {
          matchedItem = item;
          break;
        }
        if (isGermany && (/\b(deutschland|germany)\b/i.test(txt))) {
          matchedItem = item;
          break;
        }
        if (txt === target) {
          matchedItem = item;
          break;
        }
      }

      if (!matchedItem) {
        for (const item of items) {
          const txt = (item.innerText || item.textContent || "").trim().toLowerCase();
          if (/keine.*auswahl|bitte.*w[äa]hl|please.*select/i.test(txt)) continue;
          if (txt.includes(target) || target.includes(txt)) {
            matchedItem = item;
            break;
          }
        }
      }

      if (matchedItem) {
        matchedItem.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true }));
        matchedItem.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true }));
        matchedItem.click();
        await new Promise((r) => setTimeout(r, 120));
        highlightField(sapWrapper);
        return true;
      }

      const closeBtn = popup.closest("[class*='Picker'], [class*='picker']")?.querySelector(
        "[class*='Close'], button[aria-label*='schließen' i], button[aria-label*='close' i]"
      );
      if (closeBtn) closeBtn.click();
      else document.body.click();
      return false;
    } catch (e) {
      console.warn("[JobAgent Copilot] SAP UI5 select error:", e);
      return false;
    }
  }

  window.JobAgent.highlightField = highlightField;
  window.JobAgent.markForReview = markForReview;
  window.JobAgent.applyValueToElement = applyValueToElement;
  window.JobAgent.applyValueToSapUi5Select = applyValueToSapUi5Select;
})();
