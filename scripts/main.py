from fastapi import FastAPI
from api.routes import router as ingest_router
from config import TEMP_DIR, API_HOST, API_PORT
import os

# Ensure temp directory exists
os.makedirs(TEMP_DIR, exist_ok=True)

# Initialize FastAPI app
app = FastAPI(title="Content -> Wiki raw/ Capture")

# Include routers
app.include_router(ingest_router)


@app.get("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
