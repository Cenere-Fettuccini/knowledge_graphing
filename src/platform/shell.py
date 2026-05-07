from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

from src.platform.registry import AppRegistry


def build_shell_router(registry: AppRegistry) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    async def platform_home() -> str:
        cards = []
        for app_def in registry.list_apps():
            href = app_def.route_prefix if app_def.status == "active" else "#"
            action = "Open app" if app_def.status == "active" else "Scaffolded"
            cards.append(
                f"""
                <a class="app-card" href="{href}">
                    <div class="app-card__eyebrow">{app_def.icon} / {app_def.status.title()}</div>
                    <h2>{app_def.name}</h2>
                    <p>{app_def.description}</p>
                    <span class="app-card__action">{action}</span>
                </a>
                """
            )

        return f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AIManager Platform</title>
            <style>
                :root {{
                    --bg: #f4efe6;
                    --panel: rgba(255, 252, 247, 0.86);
                    --ink: #1f2b24;
                    --muted: #5a665f;
                    --accent: #58745f;
                    --border: rgba(56, 76, 62, 0.16);
                    --shadow: 0 24px 60px rgba(33, 45, 37, 0.12);
                }}
                * {{ box-sizing: border-box; }}
                body {{
                    margin: 0;
                    min-height: 100vh;
                    font-family: "Segoe UI", Arial, sans-serif;
                    color: var(--ink);
                    background:
                        radial-gradient(circle at top left, rgba(127, 163, 141, 0.35), transparent 34%),
                        radial-gradient(circle at top right, rgba(190, 170, 126, 0.28), transparent 26%),
                        linear-gradient(180deg, #f7f2e8 0%, var(--bg) 100%);
                }}
                main {{
                    max-width: 1180px;
                    margin: 0 auto;
                    padding: 56px 24px 72px;
                }}
                .hero {{
                    display: grid;
                    gap: 18px;
                    margin-bottom: 32px;
                }}
                .hero__tag {{
                    width: fit-content;
                    padding: 8px 12px;
                    border-radius: 999px;
                    letter-spacing: 0.08em;
                    text-transform: uppercase;
                    font-size: 12px;
                    background: rgba(255, 255, 255, 0.55);
                    border: 1px solid var(--border);
                }}
                h1 {{
                    margin: 0;
                    font-size: clamp(38px, 6vw, 74px);
                    line-height: 0.96;
                    max-width: 880px;
                }}
                .hero p {{
                    margin: 0;
                    max-width: 760px;
                    font-size: 18px;
                    line-height: 1.65;
                    color: var(--muted);
                }}
                .app-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                    gap: 18px;
                }}
                .app-card {{
                    display: grid;
                    gap: 12px;
                    padding: 22px;
                    text-decoration: none;
                    color: inherit;
                    border-radius: 24px;
                    background: var(--panel);
                    border: 1px solid var(--border);
                    box-shadow: var(--shadow);
                    backdrop-filter: blur(8px);
                    transition: transform 140ms ease, border-color 140ms ease;
                }}
                .app-card:hover {{
                    transform: translateY(-3px);
                    border-color: rgba(88, 116, 95, 0.4);
                }}
                .app-card__eyebrow {{
                    font-size: 11px;
                    letter-spacing: 0.08em;
                    text-transform: uppercase;
                    color: var(--muted);
                }}
                .app-card h2 {{
                    margin: 0;
                    font-size: 24px;
                }}
                .app-card p {{
                    margin: 0;
                    min-height: 66px;
                    color: var(--muted);
                    line-height: 1.55;
                }}
                .app-card__action {{
                    color: var(--accent);
                    font-weight: 600;
                }}
            </style>
        </head>
        <body>
            <main>
                <section class="hero">
                    <span class="hero__tag">Platform Shell</span>
                    <h1>AIManager is now structured as an app platform.</h1>
                    <p>
                        Each app gets its own isolated surface, while the shared agent platform
                        handles autonomous reasoning, tool use, memory, model routing, and credits.
                    </p>
                </section>
                <section class="app-grid">
                    {''.join(cards)}
                </section>
            </main>
        </body>
        </html>
        """

    @router.get("/platform/apps")
    async def list_platform_apps() -> JSONResponse:
        payload = [
            {
                "id": app_def.id,
                "name": app_def.name,
                "description": app_def.description,
                "route_prefix": app_def.route_prefix,
                "api_prefix": app_def.api_prefix,
                "status": app_def.status,
            }
            for app_def in registry.list_apps()
        ]
        return JSONResponse({"apps": payload})

    return router
