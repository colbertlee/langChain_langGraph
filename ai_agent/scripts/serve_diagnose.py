"""独立 uvicorn 启动：只暴露 /api/doctor + /api/health + /api/evals。

用于 production：
- 公开 HTTP 服务里只暴露诊断面（doctor / health / evals history），不暴露 agent 工具调用面
- 在 8088 端口跑；与主 app 的 8000 端口解耦
- 通过环境变量``DOCTOR_PORT`` 改默认端口

启动::

    python scripts/serve_diagnose.py

默认::
    http://0.0.0.0:8088/web/doctor
    http://0.0.0.0:8088/api/doctor
    http://0.0.0.0:8088/api/health
    http://0.0.0.0:8088/api/evals/history
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def build_app():
    """只挑诊断用 endpoint，避免把 agent runtime 暴露到公开端口。"""
    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse

    from doctor import run_doctor

    from schemas import (
        DoctorResponse,
        DoctorCheckItem,
        DoctorSummary,
        HealthResponse,
        EvalsHistoryResponse,
        EvalsHistoryItem,
    )

    app = FastAPI(
        title="AI Agent Doctor (Diagnostic Only)",
        version="2.1",
        description="诊断端点；不暴露任何 agent runtime。",
    )

    web = ROOT / "web"
    doctor_html = web / "doctor.html"

    @app.get("/api/doctor", response_model=DoctorResponse, response_model_by_alias=False)
    async def doctor_check():
        checks = run_doctor()
        items = [
            DoctorCheckItem(
                name=c.name,
                status=c.status,
                message=c.message,
                fix=c.fix,
                details=c.details,
            ).model_dump()
            for c in checks
        ]
        return {
            "exit_code": 1 if any(c.status == "fail" for c in checks) else 0,
            "checks": items,
            "summary": {
                "ok": sum(1 for c in checks if c.status == "ok"),
                "warn": sum(1 for c in checks if c.status == "warn"),
                "fail": sum(1 for c in checks if c.status == "fail"),
            },
        }

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "version": "2.1",
            "uptimeSeconds": 0.0,
            "components": {
                "doctor": "ok",
                "evals_history": "ok",
            },
        }

    @app.get("/api/evals/history", response_model=EvalsHistoryResponse)
    async def evals_history(limit: int = 10):
        from evals.runner import RUNS_DIR
        if not RUNS_DIR.exists():
            return {"runs": []}
        import json
        runs = []
        sub = sorted([d for d in RUNS_DIR.iterdir() if d.is_dir()], reverse=True)
        for r in sub[:limit]:
            s = r / "summary.json"
            if not s.exists():
                continue
            try:
                data = json.loads(s.read_text(encoding="utf-8"))
                runs.append(
                    EvalsHistoryItem(
                        id=r.name,
                        started_at=data.get("started_at"),
                        finished_at=data.get("finished_at"),
                        total=data.get("cases_total", 0),
                        passed=data.get("cases_passed", 0),
                        failed=data.get("cases_failed", 0),
                    )
                )
            except Exception:
                continue
        return {"runs": [r.model_dump() for r in runs]}

    @app.get("/")
    async def index():
        # 直接跳到 doctor.html
        return JSONResponse(
            {
                "title": "AI Agent Doctor",
                "ui_url": "/web/doctor",
                "api_url": "/api/doctor",
                "health_url": "/api/health",
                "history_url": "/api/evals/history",
            }
        )

    @app.get("/web/doctor")
    async def doctor_page():
        if doctor_html.exists():
            return FileResponse(str(doctor_html))
        return JSONResponse(
            {"detail": "doctor.html not found"},
            status_code=404,
        )

    @app.get("/diagnose")
    async def diagnose():
        return await doctor_page()

    return app


def main() -> None:
    import uvicorn

    port = int(os.environ.get("DOCTOR_PORT", "8088"))
    host = os.environ.get("DOCTOR_HOST", "0.0.0.0")
    print(f"[serve_diagnose] listening on http://{host}:{port}/web/doctor")
    uvicorn.run(build_app(), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
