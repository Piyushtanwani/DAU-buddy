import sys
import os
import requests
import threading
from urllib.parse import urljoin

def main():
    if len(sys.argv) < 3:
        print("Usage: python mcp_sse_proxy.py <sse_url> <api_key>", file=sys.stderr)
        sys.exit(1)
        
    sse_url = sys.argv[1]
    api_key = sys.argv[2]
    
    headers = {
        "Authorization": f"Bearer {api_key}"
    }
    
    # Establish SSE Connection
    try:
        response = requests.get(sse_url, headers=headers, stream=True)
        if response.status_code != 200:
            print(f"[Proxy] Connection failed: {response.status_code}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"[Proxy] Connection error: {e}", file=sys.stderr)
        sys.exit(1)
        
    lines_iter = response.iter_lines()
    post_url = None
    
    # Read the first event block to find the messaging endpoint
    current_event = None
    for line in lines_iter:
        if not line:
            if post_url:
                break
            continue
        line_str = line.decode('utf-8').strip()
        if line_str.startswith("event:"):
            current_event = line_str.split(":", 1)[1].strip()
        elif line_str.startswith("data:"):
            data_val = line_str.split(":", 1)[1].strip()
            if current_event == "endpoint":
                post_url = urljoin(sse_url, data_val)
                
    if not post_url:
        print("[Proxy] Failed to receive messaging endpoint from SSE server.", file=sys.stderr)
        sys.exit(1)
        
    print(f"[Proxy] Bridge established. POST endpoint: {post_url}", file=sys.stderr)
    
    # Thread to read standard input (from Claude Desktop) and POST it to the server
    def stdin_reader():
        for line in sys.stdin:
            if not line:
                break
            try:
                r = requests.post(post_url, data=line, headers={
                    "Content-Type": "application/json",
                    **headers
                })
                if r.status_code not in [200, 202]:
                    print(f"[Proxy] POST failed with status: {r.status_code}", file=sys.stderr)
            except Exception as ex:
                print(f"[Proxy] POST error: {ex}", file=sys.stderr)
                
    t = threading.Thread(target=stdin_reader, daemon=True)
    t.start()
    
    # Main thread reads the remaining SSE events and writes them to standard output
    for line in lines_iter:
        if not line:
            sys.stdout.flush()
            continue
            
        line_str = line.decode('utf-8')
        if line_str.startswith("data:"):
            data_val = line_str.split(":", 1)[1].strip()
            sys.stdout.write(data_val + "\n")
            sys.stdout.flush()
                
if __name__ == "__main__":
    main()
