"""Run the dashboard adapter: python -m synthetix_alpha.api"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run("synthetix_alpha.api.app:app", host="127.0.0.1", port=8000, reload=False)
