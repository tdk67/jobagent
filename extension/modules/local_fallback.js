// JobAgent Copilot - Local Fast-Path Fallback Module
// Provides deterministic offline autofill when backend reasoning is unreachable

(function () {
  "use strict";

  window.JobAgent = window.JobAgent || {};

  async function localFallbackFill(schema, elementMap, profile, documents) {
    let filledCount = 0;
    let reviewCount = 0;
    const pers = profile?.personal || {};
    const sapSelectQueue = [];

    const applyValueToElement = window.JobAgent.applyValueToElement || (() => false);
    const uploadDocumentToInput = window.JobAgent.uploadDocumentToInput || (() => false);
    const markForReview = window.JobAgent.markForReview || (() => {});
    const applyValueToSapUi5Select = window.JobAgent.applyValueToSapUi5Select || (async () => false);

    for (const f of schema) {
      const el = elementMap.get(f.fieldId);
      if (!el) continue;

      const desc = `${f.label} ${f.name} ${f.placeholder} ${f.id}`.toLowerCase();

      // Security: Never autofill passwords
      if (f.type === "password" || /kennwort|passwort|password/i.test(desc)) {
        continue;
      }

      // File upload fields
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

      // 1. Middle Name
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
      // 5. Country Dialing Prefix
      else if (/länder.*vorwahl|regionsvorwahl|country.*code|vorwahl|dialing.*code/i.test(desc)) {
        val = pers.phoneCountryCode || "";
      }
      // 6. Phone Number
      else if (/phone|telefon|mobile|handy|rufnummer/i.test(desc) || f.type === "tel") {
        val = pers.phone;
      }
      // 7. Country of Residence
      else if (/aktuell.*wohnsitz|country.*residence|wohnsitz|land.*wohnsitz/i.test(desc)) {
        val = pers.countryDe || pers.countryEn || "";
      }
      // 8. Work Authorization
      else if (/arbeitserlaubnis|work.*authorization|legal.*right.*to.*work|erlaubnis.*in.*dem.*land/i.test(desc)) {
        val = pers.workAuthorizationDe || pers.workAuthorizationEn || "Ja";
        markForReview(el);
        reviewCount++;
      }
      // 9. Prior Employment
      else if (/bereits.*angestellt|previously.*employed|bereits.*gearbeitet|früher.*angestellt|früher.*beschäftigt/i.test(desc) || (/bereits/i.test(desc) && /angestellt|gearbeitet|beschäftigt/i.test(desc))) {
        val = "Nein";
      }
      // 10. Preferred Job Location
      else if (/welchen standort|bevorzugter standort|gewünschter standort/i.test(desc) || (desc.includes("standort") && /bewerben|primär|wunsch|arbeiten/i.test(desc))) {
        val = profile?.jobSearch?.preferredLocations?.[0] || profile?.preferences?.locations?.[0] || pers.city || null;
      }
      // 11. Languages
      else if (/kenntnis|wie gut|niveau|sprach|level|proficiency|skills/i.test(desc)) {
        const langs = profile?.languages || {};
        for (const [langKey, langVal] of Object.entries(langs)) {
          if (!langVal) continue;
          const k = langKey.toLowerCase().trim();
          if (desc.includes(k) || (k === "german" && desc.includes("deutsch")) || (k === "english" && desc.includes("englisch"))) {
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
      // 14. Salary Expectation
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
      // 16. Professional Links
      else if (/linkedin/i.test(desc)) {
        val = pers.linkedin || pers.linkedinUrl;
      } else if (/github/i.test(desc)) {
        val = pers.github || pers.githubUrl;
      }
      // 17. Consents
      else if (/job.*alert|job-angebot|benachrichtigung/i.test(desc) && f.type === "checkbox") {
        val = "true";
      } else if (/datenschutz|datenschutzerklärung|privacy/i.test(desc) && f.type === "checkbox") {
        val = "true";
      }
      // 18. Headline
      else if (/headline|berufsbezeichnung|professional.*headline|profil-slogan|kurztitel/i.test(desc)) {
        val = pers.headline || profile?.jobSearch?.headline || profile?.preferences?.targetRoles?.[0] || "Senior Software Engineer";
      }
      // 19. Summary
      else if (/summary|zusammenfassung|profilzusammenfassung|über mich|ueber mich|about.*me|kurzprofil|bio/i.test(desc)) {
        const isDe = /zusammenfassung|über mich|ueber mich|kurzprofil/i.test(desc);
        val = (isDe ? pers.summaryDe : (pers.summaryEn || pers.summaryDe)) || pers.summaryDe || pers.summaryEn || "";
      }
      // 20. Motivation / Cover Letter Text
      else if (/anschreiben|cover.*letter|coverletter|motivation|warum.*bewerben|why.*join|essay/i.test(desc)) {
        const isDe = /anschreiben|warum.*bewerben/i.test(desc);
        val = (isDe ? pers.coverLetterDe : (pers.coverLetterEn || pers.coverLetterDe)) || pers.coverLetterDe || pers.coverLetterEn || "";
      }

      if (val !== null) {
        const isCombobox = el.getAttribute?.("role") === "combobox";
        if (isCombobox) {
          sapSelectQueue.push({ val: String(val), wrapper: el });
        } else if (applyValueToElement(el, val)) {
          filledCount++;
        }
      }
    }

    for (const { val, wrapper } of sapSelectQueue) {
      const labelEl = wrapper.querySelector(".sapMSltLabel, [class*='Label'], [class*='label'], span");
      const visibleText = (labelEl?.innerText || labelEl?.textContent || wrapper.innerText || "").trim().toLowerCase();
      const isAlreadySet = visibleText.includes(val.toLowerCase()) ||
        (val === "+49" && visibleText.includes("+49")) ||
        (val.toLowerCase() === "deutschland" && visibleText.includes("deutschland"));
      if (!isAlreadySet) {
        const ok = await applyValueToSapUi5Select(wrapper, val);
        if (ok) filledCount++;
      }
    }

    return filledCount;
  }

  window.JobAgent.localFallbackFill = localFallbackFill;
})();
