from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from concurrent.futures import ProcessPoolExecutor

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse

from app.config import config
from app.db import create_pool
from app.pipeline import run_phase1

_executor: ProcessPoolExecutor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 0.4 lifespan: DB pool, compiled regex, dictionaries, process pool (1-2 OCR workers)
    global _executor
    create_pool()
    _executor = ProcessPoolExecutor(max_workers=2)
    yield
    if _executor:
        _executor.shutdown(wait=True)


app = FastAPI(title="EGCA Phase 1", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "pipeline_version": config.pipeline_version}


@app.post("/phase1")
async def phase1(upload_id: str = Form(...), file: UploadFile = File(...)):
    file_bytes = await file.read()
    filename = file.filename or "upload.pdf"
    loop = asyncio.get_event_loop()
    output = await loop.run_in_executor(_executor, run_phase1, file_bytes, filename, upload_id)
    return JSONResponse(content=output.model_dump())
