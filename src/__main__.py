import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # src/ on path so bare `api` imports resolve at runtime

import uvicorn

if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=False)
