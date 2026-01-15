<div align="center">
	<img src="./public/favicon.svg" width="160" />
	<h1>FastAPI Radar（Tortoise ORM 适配版）</h1>
  <span>中文 | <a href="./README.en_US.md">English</a></span>
</div>


本仓库是 fastapi-radar 的 Tortoise ORM 适配版

默认访问地址：http://localhost:8000/__radar

## 安装

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

## 使用

最小可用示例（集成 Tortoise ORM）：

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

启动应用后，访问：
- API: http://localhost:8000
- 文档: http://localhost:8000/docs
- 调试面板: http://localhost:8000/__radar

## 运行测试

1. 安装开发依赖：

```bash
uv add pytest
```

2. 在项目根目录运行全部测试：

```bash
uv run pytest
```

3. 如果只想运行标记为集成测试的用例：

```bash
uv run pytest -m integration
```
