#!/usr/bin/env python3
import asyncio
import json
import websockets
import subprocess

class RawCDP:
    """Direct WebSocket CDP — no Playwright, pure protocol"""
    
    def __init__(self, ws_url):
        self.ws = None
        self.ws_url = ws_url
        self._id = 0
    
    async def connect(self):
        if not self.ws:
            self.ws = await websockets.connect(self.ws_url, max_size=10_000_000, ping_interval=30)
    
    async def cmd(self, method, **params):
        """Send CDP command"""
        if not self.ws:
            await self.connect()
        
        self._id += 1
        msg_id = self._id
        await self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        
        while True:
            try:
                resp = json.loads(await asyncio.wait_for(self.ws.recv(), timeout=30))
                if resp.get("id") == msg_id:
                    if resp.get("error"):
                        raise Exception(f"CDP: {resp['error']}")
                    return resp.get("result", {})
            except asyncio.TimeoutError:
                return {}
    
    async def goto(self, url, wait_ms=3000):
        await self.cmd("Page.enable")
        await self.cmd("Page.navigate", url=url)
        await asyncio.sleep(wait_ms / 1000)
    
    async def click_text(self, text):
        """Find and click element by text"""
        result = await self.cmd("Runtime.evaluate", expression=f"""
        (()=>{{
            let el = Array.from(document.querySelectorAll('*')).find(e => 
                e.innerText && e.innerText.trim() === '{text}');
            if (!el) return null;
            let r = el.getBoundingClientRect();
            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
        }})()
        """)
        if result.get("value"):
            await self.click_xy(result["value"]["x"], result["value"]["y"])
            return True
        return False
    
    async def click_xy(self, x, y):
        """Click at coordinates"""
        await self.cmd("Input.dispatchMouseEvent", type="mouseMoved", x=x, y=y)
        await self.cmd("Input.dispatchMouseEvent", type="mousePressed", x=x, y=y, button="left", clickCount=1)
        await self.cmd("Input.dispatchMouseEvent", type="mouseReleased", x=x, y=y, button="left")
        await asyncio.sleep(0.5)
    
    async def type_text(self, text):
        """Type text character by character"""
        for char in text:
            await self.cmd("Input.insertText", text=char)
            await asyncio.sleep(0.02)
    
    async def text(self):
        """Get page text"""
        result = await self.cmd("Runtime.evaluate", expression="document.body.innerText")
        return result.get("value", "")
    
    async def close(self):
        if self.ws:
            await self.ws.close()
    
    @classmethod
    async def new_tab(cls):
        """Open new tab and connect"""
        result = subprocess.check_output(
            'curl -s -X PUT "http://localhost:9222/json/new?about:blank"',
            shell=True
        )
        ws_url = json.loads(result)["webSocketDebuggerUrl"]
        return cls(ws_url)
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, *args):
        await self.close()

# Usage example:
# async with RawCDP.new_tab() as cdp:
#     await cdp.goto("https://example.com")
#     await cdp.click_text("Button")
#     text = await cdp.text()
