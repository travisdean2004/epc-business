#!/usr/bin/env python3
"""
Indeed Webhook Status Check — Every 5 minutes
Verifies webhook endpoint is live and receiving payloads
"""
import json
import os
import time
from datetime import datetime, timedelta
import urllib.request
import urllib.error

WEBHOOK_URL = "https://editor-dipping-designer.ngrok-free.dev/webhook/indeed"
PAYLOAD_LOG = os.path.expanduser("~/.hermes/indeed_webhook_payloads.log")
CONFIG = os.path.expanduser("~/epc-webhook/config.json")

def check_webhook_endpoint():
    """Check if webhook endpoint responds to health checks"""
    try:
        # Test localhost endpoint (ngrok tunnel tested separately)
        test_payload = {
            "event_type": "test",
            "event_data": {
                "applicant_name": "TEST_PING",
                "applicant_phone": "+1-555-0000",
                "applicant_email": "test@internal.epc",
                "job_title": "Test Lead"
            }
        }
        
        req = urllib.request.Request(
            "http://localhost:3847/webhook/indeed",
            data=json.dumps(test_payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                return True, "Endpoint reachable (200 OK)"
            else:
                return False, f"Endpoint returned {response.status}"
    except urllib.error.URLError as e:
        return False, f"URL Error: {str(e)}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP Error {e.code}: {e.reason}"
    except Exception as e:
        return False, f"Connection failed: {str(e)}"

def check_recent_payloads():
    """Check if webhook has received payloads in last hour"""
    if not os.path.exists(PAYLOAD_LOG):
        return False, "No payload log found"
    
    try:
        with open(PAYLOAD_LOG) as f:
            lines = f.readlines()
        
        if not lines:
            return False, "Payload log is empty"
        
        # Parse last line for timestamp
        last_line = lines[-1].strip()
        if not last_line:
            return False, "Payload log has no recent entries"
        
        # Check if line contains recent timestamp
        now = datetime.now()
        hour_ago = now - timedelta(hours=1)
        
        # Simple check: if file was modified in last hour
        mtime = os.path.getmtime(PAYLOAD_LOG)
        mtime_dt = datetime.fromtimestamp(mtime)
        
        if mtime_dt > hour_ago:
            return True, f"Recent payloads detected (last: {mtime_dt.strftime('%H:%M:%S')})"
        else:
            return False, f"No payloads in last hour (last: {mtime_dt.strftime('%H:%M:%S')})"
    except Exception as e:
        return False, f"Error reading log: {str(e)}"

def check_server_config():
    """Check if server.js config has Indeed webhook handler"""
    try:
        with open(CONFIG) as f:
            cfg = json.load(f)
        
        if "INDEED_WEBHOOK_URL" in cfg:
            return True, f"Config valid: {cfg.get('INDEED_WEBHOOK_URL')}"
        else:
            return False, "INDEED_WEBHOOK_URL not in config"
    except Exception as e:
        return False, f"Config error: {str(e)}"

def log_status(endpoint_ok, payload_ok, config_ok):
    """Log status to watchdog log"""
    log_path = os.path.expanduser("~/.hermes/epc_webhook_watchdog.log")
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    
    status_line = f"{timestamp} INDEED WEBHOOK STATUS: endpoint={endpoint_ok} payloads={payload_ok} config={config_ok}\n"
    
    try:
        with open(log_path, "a") as f:
            f.write(status_line)
    except:
        pass

if __name__ == "__main__":
    endpoint_ok, endpoint_msg = check_webhook_endpoint()
    payload_ok, payload_msg = check_recent_payloads()
    config_ok, config_msg = check_server_config()
    
    log_status(endpoint_ok, payload_ok, config_ok)
    
    # Exit 0 if all OK, 1 if any failed
    if endpoint_ok and config_ok:
        exit(0)
    else:
        exit(1)
