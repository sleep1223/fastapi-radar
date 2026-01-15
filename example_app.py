"""Example FastAPI application with Radar integration."""

import asyncio
from datetime import datetime
from typing import List, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi_radar import Radar, track_background_task
from pydantic import BaseModel

from tortoise import fields, models
from tortoise.contrib.fastapi import register_tortoise
from tortoise.expressions import Q

# Models


class Product(models.Model):
    id = fields.IntField(pk=True)
    name = fields.CharField(max_length=100, index=True)
    description = fields.CharField(max_length=500, null=True)
    price = fields.FloatField()
    in_stock = fields.BooleanField(default=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "products"


class User(models.Model):
    id = fields.IntField(pk=True)
    username = fields.CharField(max_length=50, unique=True, index=True)
    email = fields.CharField(max_length=100, unique=True)
    full_name = fields.CharField(max_length=100, null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "users"


# Pydantic models
class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    in_stock: bool = True


class ProductResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    price: float
    in_stock: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UserCreate(BaseModel):
    username: str
    email: str
    full_name: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    username: str
    email: str
    full_name: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# FastAPI app
app = FastAPI(
    title="Example App with Radar",
    description="Demonstration of FastAPI Radar debugging dashboard",
    version="1.0.0",
)

# Initialize Radar
# We set db_path to radar.sqlite.
# We expect Tortoise to be initialized by register_tortoise below.
radar = Radar(
    app,
    dashboard_path="/__radar",
    slow_query_threshold=50,
    theme="auto",
)

# Register Tortoise
# We include both app models and radar models
register_tortoise(
    app,
    db_url="sqlite://example.db",
    modules={"models": ["__main__", "fastapi_radar.models"]},
    generate_schemas=True,
    add_exception_handlers=True,
)


# Routes


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Welcome to the Example API",
        "dashboard": "Visit /__radar to see the debugging dashboard",
    }


@app.get("/products", response_model=List[ProductResponse])
async def list_products(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
    in_stock_only: bool = False,
):
    """List all products with pagination."""
    query = Product.all()
    if in_stock_only:
        query = query.filter(in_stock=True)

    products = await query.offset(skip).limit(limit)
    return products


@app.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(product_id: int):
    """Get a specific product by ID."""
    product = await Product.filter(id=product_id).first()

    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    return product


@app.post("/products", response_model=ProductResponse, status_code=201)
async def create_product(product: ProductCreate):
    """Create a new product."""
    db_product = await Product.create(**product.model_dump())
    return db_product


@app.put("/products/{product_id}", response_model=ProductResponse)
async def update_product(product_id: int, product: ProductCreate):
    """Update an existing product."""
    db_product = await Product.filter(id=product_id).first()

    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")

    await db_product.update_from_dict(product.model_dump())
    await db_product.save()
    return db_product


@app.delete("/products/{product_id}")
async def delete_product(product_id: int):
    """Delete a product."""
    deleted_count = await Product.filter(id=product_id).delete()

    if not deleted_count:
        raise HTTPException(status_code=404, detail="Product not found")

    return {"message": "Product deleted successfully"}


@app.get("/users", response_model=List[UserResponse])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=100),
):
    """List all users with pagination."""
    users = await User.all().offset(skip).limit(limit)
    return users


@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int):
    """Get a specific user by ID."""
    user = await User.filter(id=user_id).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user


@app.post("/users", response_model=UserResponse, status_code=201)
async def create_user(user: UserCreate):
    """Create a new user."""
    existing_user = await User.filter(Q(username=user.username) | Q(email=user.email)).first()

    if existing_user:
        raise HTTPException(status_code=400, detail="User with this username or email already exists")

    db_user = await User.create(**user.model_dump())
    return db_user


@app.get("/slow-query")
async def slow_query_example():
    """Example endpoint that performs a slow query."""
    # Simulate a slow query
    products = await Product.all()
    await asyncio.sleep(0.2)  # Simulate slow processing

    # Multiple queries
    for product in products[:3]:
        _ = await User.filter(id=1).first()

    return {
        "message": "This endpoint performs slow queries",
        "product_count": len(products),
    }


@app.get("/error")
async def trigger_error():
    """Example endpoint that raises an exception."""
    raise ValueError("This is an example error for demonstration purposes")


# Background Tasks


@track_background_task()
async def send_email_task(email: str, subject: str):
    """Simulated background task for sending emails."""
    await asyncio.sleep(2)
    return f"Email sent to {email}"


@track_background_task()
async def process_report(user_id: int):
    """Simulated background task for processing reports."""
    await asyncio.sleep(3)
    return f"Report processed for user {user_id}"


@track_background_task()
async def generate_analytics(days: int = 7):
    """Simulated background task for generating analytics."""
    await asyncio.sleep(1.5)
    return f"Analytics generated for last {days} days"


@track_background_task()
async def sync_inventory_task():
    """Simulated synchronous background task (converted to async)."""
    await asyncio.sleep(1)
    return "Inventory synchronized"


@track_background_task()
async def failing_task():
    """Example task that fails."""
    await asyncio.sleep(0.5)
    raise Exception("Simulated task failure for testing")


@app.post("/send-email")
async def send_email(email: str, subject: str, background_tasks: BackgroundTasks):
    """Example endpoint that triggers a background task."""
    background_tasks.add_task(send_email_task, email, subject)
    return {"message": "Email will be sent in the background"}


@app.post("/process-report/{user_id}")
async def process_user_report(user_id: int, background_tasks: BackgroundTasks):
    """Example endpoint that triggers a long-running background task."""
    background_tasks.add_task(process_report, user_id)
    return {"message": "Report processing started"}


@app.post("/generate-analytics")
async def generate_analytics_endpoint(background_tasks: BackgroundTasks, days: int = Query(7, ge=1, le=365)):
    """Generate analytics for the specified number of days."""
    background_tasks.add_task(generate_analytics, days)
    return {"message": f"Analytics generation started for last {days} days"}


@app.post("/sync-inventory")
async def sync_inventory(background_tasks: BackgroundTasks):
    """Synchronize inventory (sync task example)."""
    background_tasks.add_task(sync_inventory_task)
    return {"message": "Inventory sync started"}


@app.post("/test-failure")
async def test_task_failure(background_tasks: BackgroundTasks):
    """Test a failing background task."""
    background_tasks.add_task(failing_task)
    return {"message": "Failing task started (check background tasks page)"}


@app.get("/health")
async def health_check():
    """Health check endpoint (excluded from Radar by default)."""
    return {"status": "healthy"}


# Seed data
@app.on_event("startup")
async def startup_event():
    # Check if dashboard is built
    dashboard_dist = Path(__file__).parent / "fastapi_radar" / "dashboard" / "dist"
    if not dashboard_dist.exists():
        print("⚠️  Dashboard not built yet! Please run npm run build in fastapi_radar/dashboard")

    # Add sample data if empty
    if await Product.all().count() == 0:
        sample_products = [
            Product(
                name="Laptop",
                description="High-performance laptop",
                price=999.99,
                in_stock=True,
            ),
            Product(
                name="Mouse",
                description="Wireless mouse",
                price=29.99,
                in_stock=True,
            ),
            Product(
                name="Keyboard",
                description="Mechanical keyboard",
                price=149.99,
                in_stock=False,
            ),
            Product(
                name="Monitor",
                description="4K display",
                price=499.99,
                in_stock=True,
            ),
            Product(
                name="Headphones",
                description="Noise-cancelling",
                price=199.99,
                in_stock=True,
            ),
        ]
        # Bulk create not always supported for all backends, but iterate is fine
        for p in sample_products:
            await p.save()

        sample_users = [
            User(username="johndoe", email="john@example.com", full_name="John Doe"),
            User(username="janedoe", email="jane@example.com", full_name="Jane Doe"),
            User(username="admin", email="admin@example.com", full_name="Admin User"),
        ]
        for u in sample_users:
            await u.save()

        print("Sample data added to database")

    # Ensure Radar tables are created (redundant if generate_schemas=True in register_tortoise)
    # But useful to call explicit method
    await radar.create_tables()

    print("\n" + "=" * 60)
    print("🚀 FastAPI Radar Example App (Tortoise ORM)")
    print("=" * 60)
    print("\nEndpoints:")
    print("  API:       http://localhost:8000")
    print("  Docs:      http://localhost:8000/docs")
    print("  Dashboard: http://localhost:8000/__radar")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    from pathlib import Path

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
