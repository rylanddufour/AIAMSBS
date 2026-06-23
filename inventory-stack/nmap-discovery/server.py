import uvicorn
from fastapi import FastAPI
app = FastAPI()

@app.get("/scan")
def scan(target: str = "192.168.0.0/24"):
    result = nmap_discovery(target)
    return {
        "target": target,
        "output": result.stdout,
        "error": result.stderr,
        "code": result.returncode
    }

def nmap_discovery(target):
    import subprocess
    cmd = ["nmap", "-sn", "-PR", "-O", "--top-ports", "1000", "-oX", "-", target]
    return subprocess.run(cmd, capture_output=True, text=True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)