#!/usr/bin/env python3
import asyncio
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Add epc path
sys.path.insert(0, str(Path.home() / "epc"))

async def pull_indeed_leads():
    """Click Indeed dashboard, extract applicants, post to Telegram"""
    
    try:
        from rawcdp import RawCDP
    except ImportError:
        print("❌ RawCDP not found")
        return
    
    # Telegram config
    cfg_path = Path.home() / "epc-webhook" / "config.json"
    token = ""
    if cfg_path.exists():
        try:
            cfg = json.load(open(cfg_path))
            token = cfg.get("TG_BOT_TOKEN", "")
        except:
            pass
    
    if not token:
        print("❌ No token")
        return
    
    chat_id = "-5306696575"
    
    print("[indeed] Opening Chrome tab...")
    
    cdp = await RawCDP.new_tab()
    async with cdp:
        # Navigate to Indeed
        print("[indeed] Loading Indeed dashboard...")
        await cdp.goto(
            "https://employers.indeed.com/candidates?id=6186a8e3e50c&tab=manage",
            wait_ms=5000
        )
        
        # Get page content
        print("[indeed] Extracting applicants...")
        page_text = await cdp.text()
        
        # Parse applicants using JS
        result = await cdp.cmd("Runtime.evaluate", expression="""
        (() => {
            let applicants = [];
            let rows = document.querySelectorAll('[data-testid="candidate-row"]');
            
            if (rows.length === 0) {
                // Fallback: get all text sections
                let cells = document.querySelectorAll('td, li, div[role="button"]');
                let current = {};
                
                cells.forEach(cell => {
                    let text = cell.innerText.trim();
                    if (!text) return;
                    
                    // Detect field type by context
                    if (text.includes('@')) {
                        current.email = text;
                    } else if (text.match(/\\d{3}-\\d{3}-\\d{4}/)) {
                        current.phone = text;
                    } else if (text.match(/applied|applied|today|yesterday/i)) {
                        current.applied = text;
                        if (current.email || current.phone) {
                            applicants.push(current);
                            current = {};
                        }
                    } else if (text.length < 50 && !text.includes(' ')) {
                        // Likely a name
                        if (!current.name) current.name = text;
                    }
                });
                
                return applicants;
            }
            
            // Standard parsing if rows found
            rows.forEach(row => {
                try {
                    let text = row.innerText;
                    let name = row.querySelector('[data-testid*="name"]')?.innerText || 'Unknown';
                    let email = (text.match(/[a-z0-9._%+-]+@[a-z0-9.-]+\\.[a-z]{2,}/i) || [''])[0];
                    let phone = (text.match(/\\(?\\d{3}\\)?[\\s.-]?\\d{3}[\\s.-]?\\d{4}/) || [''])[0];
                    let applied = (text.match(/applied.{0,30}(today|yesterday|\\d+\\s*\\w+|[A-Z][a-z]{2})/) || ['Unknown'])[0];
                    
                    applicants.push({name, email, phone, applied});
                } catch(e) {}
            });
            
            return applicants;
        })()
        """)
        
        applicants = result.get("value", [])
        
        if not applicants:
            print("[indeed] No applicants found")
            return
        
        print(f"[indeed] Found {len(applicants)} applicants. Posting...\n")
        
        # Send each to Telegram
        for app in applicants:
            name = app.get("name", "Unknown")
            email = app.get("email", "")
            phone = app.get("phone", "")
            applied = app.get("applied", "Unknown")
            
            if not name or (not email and not phone):
                continue
            
            msg = f"🎯 **INDEED APPLICANT**\n"
            msg += f"`{name}`\n"
            if email:
                msg += f"📧 {email}\n"
            if phone:
                msg += f"📞 {phone}\n"
            msg += f"📅 {applied}"
            
            cmd = [
                "curl", "-s", "-X", "POST",
                f"https://api.telegram.org/bot{token}/sendMessage",
                "-d", f"chat_id={chat_id}",
                "-d", f"text={msg}",
                "-d", "parse_mode=Markdown"
            ]
            
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=10)
                if b'"ok":true' in result.stdout:
                    print(f"✅ {name}")
                else:
                    print(f"❌ {name} (Telegram error)")
            except:
                print(f"❌ {name} (timeout)")
        
        print("\n[indeed] Done")

if __name__ == "__main__":
    asyncio.run(pull_indeed_leads())
