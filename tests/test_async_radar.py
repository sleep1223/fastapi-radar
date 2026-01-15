from fastapi import FastAPI
from fastapi_radar import Radar

from tortoise import fields, models
from tortoise.contrib.fastapi import register_tortoise

app = FastAPI()


# Test Model
class User(models.Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=50)

    class Meta:
        table = "users"


# Setup Radar
radar = Radar(app)

# Register Tortoise
register_tortoise(
    app,
    db_url="sqlite://:memory:",
    modules={"models": ["__main__", "fastapi_radar.models"]},
    generate_schemas=True,
    add_exception_handlers=True,
)


@app.on_event("startup")
async def on_startup() -> None:
    """Add sample data on startup."""
    if await User.all().count() == 0:
        await User.create(name="Alice")
        await User.create(name="Bob")
        await User.create(name="Carol")


# Your routes work unchanged
@app.get("/users")
async def get_users():
    users = await User.all()
    return {"users": users}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
