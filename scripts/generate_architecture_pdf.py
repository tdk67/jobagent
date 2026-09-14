import asyncio
from playwright.async_api import async_playwright
import os

mermaid_code = """
graph TD
    classDef default fill:#1E293B,stroke:#38BDF8,stroke-width:2px,color:#F8FAFC,font-family:Inter;
    classDef local fill:#064E3B,stroke:#10B981,stroke-width:2px,color:#ECFDF5;
    classDef external fill:#7F1D1D,stroke:#EF4444,stroke-width:2px,color:#FEF2F2;
    classDef agent fill:#312E81,stroke:#818CF8,stroke-width:2px,color:#EEF2FF;

    subgraph User Environment
        Browser[Chrome Copilot Ext.<br/>1-Click Archive & Autofill]
        Inbox[Email Inbox<br/>Outlook / Gmail / IMAP]
    end

    subgraph JobAgent Local System
        Gateway[FastAPI / MCP Gateway<br/>Agent-to-Agent REST]:::agent
        Coordinator[Strands Agent Coordinator<br/>AWS SDK + Local Routing]:::agent
        
        subgraph Tools
            EmailTool[Email Ingest Tool<br/>3-Tier Classifier]
            ArchiveTool[Job Archive Tool<br/>Markdown & PDF]
            ReportTool[Report Render Tool<br/>Agentur für Arbeit PDF]
        end
        
        Storage[(Local SQLite CRM<br/>Zero Cloud PII Leakage)]:::local
    end

    subgraph External Models
        Gemini[Google Gemini Flash<br/>Cloud Reasoning]:::external
        Ollama[Ollama<br/>True Local Execution]:::external
    end

    ParentAgent[Parent Personal Agent<br/>Claude Desktop / Cursor]

    %% Connections
    ParentAgent <-->|MCP / REST| Gateway
    Browser <-->|REST API| Gateway
    Inbox -->|MAPI / IMAP| EmailTool

    Gateway --> Coordinator
    Coordinator --> EmailTool
    Coordinator --> ArchiveTool
    Coordinator --> ReportTool

    EmailTool --> Storage
    ArchiveTool --> Storage
    ReportTool --> Storage

    Coordinator <--> Gemini
    Coordinator <--> Ollama
"""

html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{ 
            startOnLoad: true, 
            theme: 'dark',
            securityLevel: 'loose',
            fontFamily: 'Inter, sans-serif'
        }});
    </script>
    <style>
        body {{ background-color: #0f172a; margin: 0; padding: 40px; display: flex; justify-content: center; align-items: center; height: 100vh; }}
        .mermaid {{ width: 100%; max-width: 1200px; text-align: center; }}
    </style>
</head>
<body>
    <div class="mermaid">
        {mermaid_code}
    </div>
</body>
</html>
"""

async def generate_pdf():
    os.makedirs("output", exist_ok=True)
    html_path = os.path.abspath("output/temp_arch.html")
    pdf_path = os.path.abspath("output/architecture_diagram.pdf")
    
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            device_scale_factor=2,
            viewport={"width": 1200, "height": 800}
        )
        await page.goto(f"file:///{html_path}")
        # Wait for mermaid to render
        await page.wait_for_selector("svg")
        # Give it a tiny bit more time just in case fonts load
        await asyncio.sleep(1)
        
        # We can either screenshot or PDF
        await page.pdf(path=pdf_path, format="A4", landscape=True, print_background=True)
        await browser.close()
        
    os.remove(html_path)
    print(f"Successfully generated {pdf_path}")

if __name__ == "__main__":
    asyncio.run(generate_pdf())
