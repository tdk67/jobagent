/**
 * Job Description Extractor Module
 * Extracts structured job posting metadata and full job description text
 * across major job portals (LinkedIn, StepStone, Indeed, Personio, Workday, etc.)
 * and company career landing pages.
 */

(function(root) {
  function slugify(text) {
    if (!text) return "unknown";
    return String(text)
      .toLowerCase()
      .replace(/[äöüß]/g, m => ({ "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss" }[m] || m))
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 40) || "unknown";
  }

  function cleanText(text) {
    if (!text) return "";
    return text
      .replace(/\r\n/g, "\n")
      .replace(/\t/g, " ")
      .replace(/[ \u00A0]+/g, " ")
      .replace(/\n\s*\n\s*\n+/g, "\n\n")
      .trim();
  }

  function detectRecruitingAgency(hostname) {
    const host = (hostname || window.location.hostname).toLowerCase();
    const agencyPatterns = [
      { name: "Ratbacher GmbH", regex: /ratbacher/ },
      { name: "Hays", regex: /hays/ },
      { name: "Michael Page", regex: /michaelpage|pagepersonnel/ },
      { name: "Amoria Bond", regex: /amoriabond/ },
      { name: "Nigel Frank", regex: /nigelfrank/ },
      { name: "Computer Futures", regex: /computerfutures/ },
      { name: "Glocomms", regex: /glocomms/ },
      { name: "Robert Half", regex: /roberthalf/ },
      { name: "Adecco", regex: /adecco/ },
      { name: "Randstad", regex: /randstad/ },
      { name: "SThree", regex: /sthree/ },
      { name: "Austin Fraser", regex: /austinfraser/ }
    ];
    for (const a of agencyPatterns) {
      if (a.regex.test(host)) return a.name;
    }
    return null;
  }

  function extractRequisitionId(url, pageText) {
    const urlStr = url || window.location.href;
    // Common URL requisition patterns
    const mUrl = urlStr.match(/(?:job|id|requisition|position|posting|req)[/=_ -]([0-9A-Za-z_-]{4,20})/i);
    if (mUrl && !["view", "search", "detail", "apply", "index"].includes(mUrl[1].toLowerCase())) {
      return mUrl[1];
    }
    // In-page reference/ID patterns (Ref-Nr, Job-ID, Req ID)
    const mPage = pageText ? pageText.match(/(?:job[- ]?id|ref(?:erenz)?[- ]?(?:nr\.?|nummer)?|requisition[- ]?id)[:\s]+([0-9A-Za-z_-]{4,20})/i) : null;
    if (mPage) return mPage[1];
    return null;
  }

  function extractJobPosting(customDoc, customUrl) {
    const doc = customDoc || (typeof document !== "undefined" ? document : null);
    const url = customUrl || (typeof window !== "undefined" && window.location ? window.location.href : "");
    let hostname = "";
    try {
      hostname = url ? new URL(url).hostname : (typeof window !== "undefined" && window.location ? window.location.hostname : "");
    } catch (e) {
      hostname = (typeof window !== "undefined" && window.location ? window.location.hostname : "");
    }

    if (!doc) return null;

    const isDe = doc.documentElement?.lang?.startsWith("de") || /deutschland|stellenangebot|aufgaben|profil/i.test(doc.body?.innerText || "");

    let jobTitle = "";
    let company = "";
    let location = "";
    let descriptionText = "";
    let reqId = "";

    let platformName = "Direct / Careers Site";
    if (hostname.includes("linkedin")) platformName = "LinkedIn";
    else if (hostname.includes("stepstone")) platformName = "StepStone";
    else if (hostname.includes("indeed")) platformName = "Indeed";
    else if (hostname.includes("personio")) platformName = "Personio";

    // 0. Schema.org JSON-LD extraction (Industry standard across Google Jobs, LinkedIn, StepStone, etc.)
    try {
      const scripts = Array.from(doc.querySelectorAll("script[type='application/ld+json']"));
      for (const s of scripts) {
        try {
          const parsed = JSON.parse(s.innerText || s.textContent || "");
          const item = parsed["@type"] === "JobPosting" ? parsed : (Array.isArray(parsed["@graph"]) ? parsed["@graph"].find(g => g["@type"] === "JobPosting") : null);
          if (item) {
            if (item.title && !jobTitle) jobTitle = cleanText(item.title);
            if (item.hiringOrganization?.name && !company) company = cleanText(item.hiringOrganization.name);
            if (item.jobLocation?.address) {
              const addr = item.jobLocation.address;
              location = [addr.addressLocality, addr.addressRegion, addr.addressCountry].filter(Boolean).join(", ");
            }
            if (item.identifier?.value) reqId = String(item.identifier.value);
            if (item.description && !descriptionText) {
              const tmp = doc.createElement("div");
              tmp.innerHTML = item.description;
              descriptionText = cleanText(tmp.innerText || tmp.textContent);
            }
          }
        } catch (e) {}
      }
    } catch (e) {}

    // 1. Portal-Specific Extraction
    // --- LinkedIn ---
    if (hostname.includes("linkedin.com")) {
      const titleEl = doc.querySelector(".job-details-jobs-unified-top-card__job-title, .jobs-unified-top-card__job-title, h1");
      if (titleEl && !jobTitle) jobTitle = cleanText(titleEl.innerText);

      const compEl = doc.querySelector(".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, [class*='company-name']");
      if (compEl && !company) company = cleanText(compEl.innerText);

      const locEl = doc.querySelector(".job-details-jobs-unified-top-card__bullet, [class*='workplace-type'], [class*='job-details-jobs-unified-top-card__primary-description-container']");
      if (locEl && !location) location = cleanText(locEl.innerText);

      const descEl = doc.querySelector("#job-details, .jobs-description__content, .jobs-box__html-content");
      if (descEl && !descriptionText) descriptionText = cleanText(descEl.innerText);
    }

    // --- StepStone ---
    else if (hostname.includes("stepstone.de") || hostname.includes("stepstone.")) {
      const titleEl = doc.querySelector("[data-genesis-element='HEADER_TITLE'], h1");
      if (titleEl && !jobTitle) jobTitle = cleanText(titleEl.innerText);

      const compEl = doc.querySelector("[data-genesis-element='COMPANY_NAME'], [class*='company-name']");
      if (compEl && !company) company = cleanText(compEl.innerText);

      const locEl = doc.querySelector("[data-genesis-element='LOCATION'], [class*='location']");
      if (locEl && !location) location = cleanText(locEl.innerText);

      const descEl = doc.querySelector("[data-genesis-element='JOB_DESCRIPTION'], .job-description, article");
      if (descEl && !descriptionText) descriptionText = cleanText(descEl.innerText);
    }

    // --- Indeed ---
    else if (hostname.includes("indeed.com") || hostname.includes("indeed.de")) {
      const titleEl = doc.querySelector("h1, [class*='jobsearch-JobInfoHeader-title']");
      if (titleEl && !jobTitle) jobTitle = cleanText(titleEl.innerText);

      const compEl = doc.querySelector("[data-company-name='true'], [class*='companyName']");
      if (compEl && !company) company = cleanText(compEl.innerText);

      const locEl = doc.querySelector("[class*='companyLocation'], [data-testid='inlineHeader-companyLocation']");
      if (locEl && !location) location = cleanText(locEl.innerText);

      const descEl = doc.querySelector("#jobDescriptionText, .jobsearch-JobComponent-description");
      if (descEl && !descriptionText) descriptionText = cleanText(descEl.innerText);
    }

    // --- Personio Job View ---
    else if (hostname.includes("personio.de") || hostname.includes("personio.com")) {
      const titleEl = doc.querySelector("h1, .job-title");
      if (titleEl && !jobTitle) jobTitle = cleanText(titleEl.innerText);

      const compEl = doc.querySelector(".header-company-name, [class*='company'], [class*='logo-wrapper']");
      if (compEl && !company) company = cleanText(compEl.innerText);

      const locEl = doc.querySelector(".job-location, [class*='location']");
      if (locEl && !location) location = cleanText(locEl.innerText);

      const descEl = doc.querySelector(".job-description, .job-posting, article, main");
      if (descEl && !descriptionText) descriptionText = cleanText(descEl.innerText);
    }

    // 2. Generic / Enterprise Careers Fallback
    if (!jobTitle) {
      const h1 = doc.querySelector("h1");
      if (h1 && h1.innerText && h1.innerText.length > 3) {
        jobTitle = cleanText(h1.innerText);
      } else if (doc.title) {
        jobTitle = cleanText(doc.title.split("|")[0].split("•")[0].split("-")[0]);
      }
    }

    if (!company) {
      const compEl = doc.querySelector("[class*='company'], [class*='employer'], [class*='organization'], [data-company-name]");
      if (compEl && compEl.innerText) {
        company = cleanText(compEl.innerText).split("\n")[0];
      } else {
        const parts = hostname.replace(/^(www\.|jobs\.|careers\.|apply\.)/, "").split(".");
        if (parts.length > 0 && parts[0].length > 2) {
          company = parts[0].charAt(0).toUpperCase() + parts[0].slice(1);
        }
      }
    }

    if (!location) {
      const locEl = doc.querySelector("[class*='location'], [class*='city'], [class*='address'], [class*='standort']");
      if (locEl && locEl.innerText) {
        location = cleanText(locEl.innerText).split("\n")[0];
      }
    }

    if (!descriptionText) {
      // Find candidate content containers (article, main, or largest text block)
      const candidateEls = Array.from(doc.querySelectorAll("article, main, [class*='description'], [class*='job-detail'], [class*='posting'], [id*='description'], .content"));
      let bestEl = null;
      let maxLen = 0;

      for (const el of candidateEls) {
        if (el.tagName === "NAV" || el.tagName === "HEADER" || el.tagName === "FOOTER") continue;
        const txt = el.innerText || "";
        if (txt.length > maxLen) {
          maxLen = txt.length;
          bestEl = el;
        }
      }

      if (bestEl && maxLen > 150) {
        descriptionText = cleanText(bestEl.innerText);
      } else if (doc.body && doc.body.innerText.length > 300) {
        const paras = Array.from(doc.querySelectorAll("p, ul, ol, h2, h3, h4"))
          .map(el => cleanText(el.innerText))
          .filter(t => t.length > 25);
        descriptionText = paras.join("\n\n");
      }
    }

    const agency = detectRecruitingAgency(hostname);
    if (!reqId) {
      reqId = extractRequisitionId(url, descriptionText);
    }

    const now = new Date();
    const dateStamp = `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}_${String(now.getHours()).padStart(2, '0')}${String(now.getMinutes()).padStart(2, '0')}`;
    const dateFormatted = `${String(now.getDate()).padStart(2, '0')}.${String(now.getMonth() + 1).padStart(2, '0')}.${now.getFullYear()}`;

    const appId = `${slugify(company || 'company')}--${slugify(jobTitle || 'job')}--${dateStamp}`;

    return {
      applicationId: appId,
      jobTitle: jobTitle || "Software Engineer",
      company: company || "Company",
      targetCompany: company || "Company",
      recruitingAgency: agency,
      location: location || "",
      requisitionId: reqId || null,
      jobUrl: url,
      jobDescriptionRaw: descriptionText || "",
      capturedDate: dateFormatted,
      capturedTimestamp: Date.now(),
      status: "CAPTURED",
      platform: platformName,
      language: isDe ? "de" : "en"
    };
  }

  const JobExtractor = {
    extractJobPosting,
    extractFromDoc: extractJobPosting,
    detectRecruitingAgency,
    extractRequisitionId,
    slugify,
    cleanText
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = JobExtractor;
  } else {
    root.JobExtractor = JobExtractor;
  }
})(typeof window !== "undefined" ? window : globalThis);
