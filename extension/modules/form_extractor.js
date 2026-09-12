// JobAgent Copilot - Form Extractor Module
// Handles DOM label resolution, modal container scoping, and whole-form schema extraction

(function () {
  "use strict";

  window.JobAgent = window.JobAgent || {};

  function getFieldLabel(el) {
    if (!el) return "";

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

    // 5. Container label (SAP UI5, Bootstrap, Tailwind, LinkedIn Easy Apply fb-*, standard forms)
    const container = el.closest(
      ".form-group, .form-field, .form-row, .field, .input-wrapper, .fd-form-item, [class*='field'], [class*='form-group'], [class*='row'], [class*='form-component'], [class*='fb-'], .jobs-easy-apply-form-element"
    );
    if (container) {
      const lbl = container.querySelector("label, .label, [class*='label'], legend, span.title, .fd-form-label, h3, h4");
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
    if (!el) return "";
    const container = el.closest("fieldset, section, .card, .panel, .form-section, form");
    if (container) {
      const header = container.querySelector("legend, h1, h2, h3, h4, .section-title, .header");
      if (header && header.innerText.trim()) {
        return header.innerText.trim().replace(/\s+/g, " ");
      }
    }
    return "";
  }

  function getActiveFormContainer() {
    // 1. High-priority job application modals (LinkedIn Easy Apply, SAP UI5, Greenhouse, Lever, Workday)
    const jobModalSelectors = [
      "[data-test-modal-id='easy-apply-modal']",
      ".jobs-easy-apply-modal",
      ".jobs-easy-apply-content",
      "[role='dialog'][aria-labelledby*='easy-apply' i]",
      "[role='dialog'][aria-labelledby*='bewerb' i]",
      "[role='dialog'][aria-label*='easy-apply' i]",
      "[role='dialog'][aria-label*='bewerb' i]",
      ".application-modal",
      ".jobs-apply-form",
    ];

    for (const sel of jobModalSelectors) {
      const modals = Array.from(document.querySelectorAll(sel));
      for (const modal of modals) {
        if (modal.getAttribute("aria-hidden") === "true") continue;
        const isVisible = modal.offsetWidth > 0 || modal.offsetHeight > 0 || (window.getComputedStyle && window.getComputedStyle(modal).display !== "none");
        if (isVisible && modal.querySelector("input, textarea, select, [role='combobox']")) {
          return modal;
        }
      }
    }

    // 2. Generic visible modals / dialogs
    const genericModalSelectors = [
      ".artdeco-modal",
      "[role='dialog']:not([aria-hidden='true'])",
      "dialog[open]",
      ".modal.show",
      ".modal.in",
      "[aria-modal='true']:not([aria-hidden='true'])",
      ".popup-content",
    ];

    for (const sel of genericModalSelectors) {
      const modals = Array.from(document.querySelectorAll(sel));
      for (const modal of modals) {
        if (modal.getAttribute("aria-hidden") === "true") continue;
        const isVisible = modal.offsetWidth > 0 || modal.offsetHeight > 0 || (window.getComputedStyle && window.getComputedStyle(modal).display !== "none");
        if (isVisible && modal.querySelector("input, textarea, select, [role='combobox']")) {
          return modal;
        }
      }
    }
    return document;
  }

  function extractSchemaFromContainer(container) {
    const elements = Array.from(
      container.querySelectorAll(
        "input:not([type='hidden']):not([type='submit']):not([type='button']), textarea, select, [role='combobox']"
      )
    );

    const schema = [];
    const elementMap = new Map();
    let index = 0;

    for (const el of elements) {
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

  function extractFormSchema() {
    const container = getActiveFormContainer();
    let { schema, elementMap } = extractSchemaFromContainer(container);

    if (schema.length === 0 && container !== document) {
      console.warn("[JobAgent Copilot] Modal container yielded 0 fields. Falling back to document.");
      const fallback = extractSchemaFromContainer(document);
      schema = fallback.schema;
      elementMap = fallback.elementMap;
    }

    return { schema, elementMap };
  }

  window.JobAgent.getFieldLabel = getFieldLabel;
  window.JobAgent.getSectionHeader = getSectionHeader;
  window.JobAgent.getActiveFormContainer = getActiveFormContainer;
  window.JobAgent.extractSchemaFromContainer = extractSchemaFromContainer;
  window.JobAgent.extractFormSchema = extractFormSchema;
})();
