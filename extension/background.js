// JobAgent Copilot - Manifest V3 Background Service Worker
// Provides continuous background bridge between content scripts and local gateway (127.0.0.1:8765)

const DEFAULT_GATEWAY_URL = "http://127.0.0.1:8765";

async function getGatewayUrl() {
  try {
    const data = await chrome.storage.sync.get({ gatewayUrl: DEFAULT_GATEWAY_URL });
    return data.gatewayUrl || DEFAULT_GATEWAY_URL;
  } catch (e) {
    return DEFAULT_GATEWAY_URL;
  }
}

async function getAuthToken(gatewayUrl) {
  try {
    const data = await chrome.storage.local.get(["jobagent_token"]);
    if (data?.jobagent_token) {
      return data.jobagent_token;
    }
    // Auto-pair on loopback if token is missing
    const pairRes = await fetch(`${gatewayUrl}/api/v1/auth/pair`, { signal: AbortSignal.timeout(1500) });
    if (pairRes.ok) {
      const pairData = await pairRes.json();
      if (pairData?.token) {
        await chrome.storage.local.set({ jobagent_token: pairData.token });
        return pairData.token;
      }
    }
  } catch (e) {
    console.warn("[JobAgent Service Worker] Auto-pair probe failed:", e);
  }
  return "";
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  // 1. Form Reasoning Proxy Bridge
  if (msg.action === "request_gateway_reason") {
    (async () => {
      try {
        const gatewayUrl = await getGatewayUrl();
        const token = await getAuthToken(gatewayUrl);
        const headers = { "Content-Type": "application/json" };
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const res = await fetch(`${gatewayUrl}/api/v1/form/reason`, {
          method: "POST",
          headers: headers,
          body: JSON.stringify(msg.payload),
        });

        if (!res.ok) {
          const errText = await res.text();
          throw new Error(`Gateway returned HTTP ${res.status}: ${errText}`);
        }

        const data = await res.json();
        sendResponse({ ok: true, data: data });
      } catch (err) {
        console.error("[JobAgent Service Worker] Form reasoning proxy error:", err);
        sendResponse({ ok: false, error: err.message });
      }
    })();
    return true; // Keep message channel open for async response
  }

  // 2. Dynamic Cover Letter Generation Bridge
  if (msg.action === "generate_cover_letter") {
    (async () => {
      try {
        const gatewayUrl = await getGatewayUrl();
        const token = await getAuthToken(gatewayUrl);
        const headers = { "Content-Type": "application/json" };
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const res = await fetch(`${gatewayUrl}/api/v1/cover_letter/generate`, {
          method: "POST",
          headers: headers,
          body: JSON.stringify(msg.payload),
        });

        if (!res.ok) {
          const errData = await res.json().catch(() => ({ detail: res.statusText }));
          throw new Error(errData.detail || `HTTP ${res.status}`);
        }

        const data = await res.json();
        sendResponse({ ok: true, data: data });
      } catch (err) {
        console.error("[JobAgent Service Worker] Cover letter proxy error:", err);
        sendResponse({ ok: false, error: err.message });
      }
    })();
    return true;
  }

  // 3. Document Bundle Fetch Bridge
  if (msg.action === "get_documents_bundle") {
    (async () => {
      try {
        const gatewayUrl = await getGatewayUrl();
        const token = await getAuthToken(gatewayUrl);
        const headers = {};
        if (token) headers["Authorization"] = `Bearer ${token}`;

        const res = await fetch(`${gatewayUrl}/api/v1/documents/bundle`, {
          headers: headers,
          signal: AbortSignal.timeout(3000),
        });

        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();
        sendResponse({ ok: true, data: data });
      } catch (err) {
        sendResponse({ ok: false, error: err.message });
      }
    })();
    return true;
  }
});
