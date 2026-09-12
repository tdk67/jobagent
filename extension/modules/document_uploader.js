// JobAgent Copilot - Document Uploader Module
// Handles file input detection, DataTransfer injection, SAP UI5 FileUploader body observer, and dropzone fallbacks

(function () {
  "use strict";

  window.JobAgent = window.JobAgent || {};

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

      const dropzone = inputEl.closest(".multiAttachmentWidget, .dropzone, [class*='upload'], [class*='drop'], [class*='attachment']");
      if (dropzone) {
        try {
          const dropEvt = new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt });
          dropzone.dispatchEvent(dropEvt);
        } catch (e) {}
        if (window.JobAgent.highlightField) window.JobAgent.highlightField(dropzone);
      }

      if (window.JobAgent.highlightField) window.JobAgent.highlightField(inputEl);
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

      const nestedInput = dropzoneEl.querySelector("input[type='file']") ||
        (dropzoneEl.id ? document.querySelector(`input[type='file'][aria-labelledby*='${dropzoneEl.id}']`) : null);
      if (nestedInput) {
        uploadDocumentToInput(nestedInput, docObj);
      }

      const dragEnter = new DragEvent("dragenter", { bubbles: true, cancelable: true, dataTransfer: dt });
      const dragOver = new DragEvent("dragover", { bubbles: true, cancelable: true, dataTransfer: dt });
      const drop = new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: dt });

      dropzoneEl.dispatchEvent(dragEnter);
      dropzoneEl.dispatchEvent(dragOver);
      dropzoneEl.dispatchEvent(drop);

      if (window.JobAgent.highlightField) window.JobAgent.highlightField(dropzoneEl);
      return true;
    } catch (e) {
      console.warn("[JobAgent Copilot] Dropzone upload error:", e);
      return false;
    }
  }

  function waitForFileInput(containerEl, timeoutMs = 800) {
    return new Promise((resolve) => {
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

  async function attachDocumentsToPage(documents) {
    if (!documents || (!documents.cv && !documents.coverLetter)) {
      return 0;
    }
    let attachedCount = 0;
    let cvAttached = false;
    let clAttached = false;

    function querySelectorAllDeep(selector, root = document) {
      const results = [];
      try {
        results.push(...Array.from(root.querySelectorAll(selector)));
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
        let node = walker.nextNode();
        while (node) {
          if (node.shadowRoot) {
            results.push(...querySelectorAllDeep(selector, node.shadowRoot));
          }
          node = walker.nextNode();
        }
      } catch (e) {}
      return results;
    }

    const allFileInputs = querySelectorAllDeep("input[type='file']");
    const iframes = Array.from(document.querySelectorAll("iframe"));
    for (const ifr of iframes) {
      try {
        if (ifr.contentDocument) {
          allFileInputs.push(...querySelectorAllDeep("input[type='file']", ifr.contentDocument));
        }
      } catch (e) {}
    }

    const getFieldLabel = window.JobAgent.getFieldLabel || (() => "");

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
        const isCVBtn = !cvAttached && documents.cv && CV_BTN.test(btnTxt);
        const isCLBtn = !clAttached && documents.coverLetter && CL_BTN.test(btnTxt);

        if (!isCVBtn && !isCLBtn) continue;

        const inputPromise = waitForFileInput(document.body, 700);
        btn.click();
        const input = await inputPromise;
        if (input) {
          if (isCVBtn && uploadDocumentToInput(input, documents.cv)) {
            attachedCount++;
            cvAttached = true;
          } else if (isCLBtn && uploadDocumentToInput(input, documents.coverLetter)) {
            attachedCount++;
            clAttached = true;
          }
        }
      }
    }

    if (!cvAttached || !clAttached) {
      const dropzones = Array.from(document.querySelectorAll(
        ".multiAttachmentWidget, [class*='dropzone'], [class*='upload-box'], " +
        "[class*='attachment-widget'], div[title*='hochladen'], div[title*='upload']"
      ));
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
        if (!dz || dz.id === "outershell" || dz === document.body || dz.offsetWidth > 900) continue;
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

  window.JobAgent.dataUrlToFile = dataUrlToFile;
  window.JobAgent.uploadDocumentToInput = uploadDocumentToInput;
  window.JobAgent.uploadDocumentToDropzone = uploadDocumentToDropzone;
  window.JobAgent.waitForFileInput = waitForFileInput;
  window.JobAgent.attachDocumentsToPage = attachDocumentsToPage;
})();
