<div align="center">
    <img src="./public/favicon.svg" width="160" />
    <h1>FastAPI Radar (Tortoise ORM Adaptation)</h1>
  <span><a href="./README.md">中文</a> | English</span>
</div>


This repository adapts fastapi-radar for Tortoise ORM

Default dashboard: http://localhost:8000/__radar

### Installation

Install from GitHub repository:

```bash
pip install git+https://github.com/sleep1223/fastapi-radar.git
```

Install with uv:

```bash
uv add git+https://github.com/sleep1223/fastapi-radar.git
```

```bash
uv run pip install git+https://github.com/sleep1223/fastapi-radar.git
```

Install from local source:

```bash
uv run pip install .
```

Dev install:

```bash
uv run pip install -e ".[dev]"
```

## 使用

Minimal example (with Tortoise ORM):

```python
from fastapi import FastAPI
from fastapi_radar import Radar
from tortoise.contrib.fastapi import register_tortoise

app = FastAPI()

radar = Radar(app)

register_tortoise(
    app,
    db_url="sqlite://example.db",
    modules={"models": ["your_app.models", "fastapi_radar.models"]},
    generate_schemas=True,
    add_exception_handlers=True,
)

@app.get("/")
async def index():
    return {"message": "ok"}
```

After starting:
- API: http://localhost:8000
- Docs: http://localhost:8000/docs
- Dashboard: http://localhost:8000/__radar

### Testing

Replace with:

1. Install dev dependencies:

```bash
uv add pytest
```

2. Run all tests:

```bash
uv run pytest
```

3. Run only integration tests:

```bash
uv run pytest -m integration
```

