import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import json

# Import database and services
from models.database import database
from services.redis_broker import redis_broker, RedisBroker
from services.websocket_manager import manager, handle_websocket_message

# Import API routers
from api.communities import router as communities_router
from api.threads import router as threads_router
from api.messages import router as messages_router
from api.members import router as members_router

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Background task for Redis message listening
redis_listener_task = None

async def redis_message_handler(channel: str, message_data: dict):
    """Handle Redis pub/sub messages and broadcast via WebSocket"""
    try:
        message_type = message_data.get('type')
        
        if channel.startswith('community:'):
            community_id = channel.split(':', 1)[1]
            await manager.broadcast_to_community(community_id, message_data)
            
        elif channel.startswith('thread:'):
            thread_id = channel.split(':', 1)[1]
            await manager.broadcast_to_thread(thread_id, message_data)
            
        elif channel == 'global:notifications':
            await manager.broadcast_to_all(message_data)
            
        logger.info(f"Broadcasted {message_type} message from channel {channel}")
        
    except Exception as e:
        logger.error(f"Error handling Redis message: {e}")

async def start_redis_listener():
    """Start listening to Redis pub/sub messages"""
    global redis_listener_task
    
    try:
        await redis_broker.connect()
        
        # Subscribe to pattern-based channels
        await redis_broker.subscribe('community:*', redis_message_handler)
        await redis_broker.subscribe('thread:*', redis_message_handler)
        await redis_broker.subscribe('global:*', redis_message_handler)
        
        # Start listening
        redis_listener_task = asyncio.create_task(redis_broker.listen())
        logger.info("Redis listener started successfully")
        
    except Exception as e:
        logger.error(f"Failed to start Redis listener: {e}")

async def stop_redis_listener():
    """Stop Redis listener"""
    global redis_listener_task
    
    if redis_listener_task:
        redis_listener_task.cancel()
        try:
            await redis_listener_task
        except asyncio.CancelledError:
            pass
    
    await redis_broker.disconnect()
    logger.info("Redis listener stopped")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    logger.info("Starting Communities Backend Server...")
    
    try:
        # Connect to MongoDB
        await database.connect_to_mongo()
        logger.info("Connected to MongoDB")
        
        # Start Redis listener
        await start_redis_listener()
        
        logger.info("Communities Backend Server started successfully")
        
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down Communities Backend Server...")
    
    try:
        # Stop Redis listener
        await stop_redis_listener()
        
        # Close MongoDB connection
        await database.close_mongo_connection()
        logger.info("Disconnected from MongoDB")
        
        logger.info("Communities Backend Server shut down successfully")
        
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")

# Create FastAPI application
app = FastAPI(
    title="Communities Backend API",
    description="Backend API for Communities, Threads, and Real-time Messaging",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure this properly for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(communities_router, prefix="/api")
app.include_router(threads_router, prefix="/api")
app.include_router(messages_router, prefix="/api")
app.include_router(members_router, prefix="/api")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Communities Backend API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "communities": "/api/communities",
            "threads": "/api/threads", 
            "messages": "/api/messages",
            "members": "/api/members",
            "websocket": "/ws/{user_id}",
            "docs": "/docs"
        }
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check MongoDB connection
        await database.database.admin.command('ping')
        mongo_status = "healthy"
    except Exception as e:
        mongo_status = f"unhealthy: {str(e)}"
    
    # Check Redis connection
    try:
        if redis_broker.redis_client:
            await redis_broker.redis_client.ping()
            redis_status = "healthy"
        else:
            redis_status = "not connected"
    except Exception as e:
        redis_status = f"unhealthy: {str(e)}"
    
    # Check WebSocket connections
    ws_connections = manager.get_connection_count()
    
    return {
        "status": "running",
        "mongodb": mongo_status,
        "redis": redis_status,
        "websocket_connections": ws_connections,
        "timestamp": datetime.utcnow().isoformat()
    }

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket: WebSocket, user_id: str):
    """WebSocket endpoint for real-time messaging"""
    try:
        await manager.connect(websocket, user_id)
        logger.info(f"WebSocket connected for user: {user_id}")
        
        try:
            while True:
                # Receive message from client
                data = await websocket.receive_text()
                
                try:
                    message = json.loads(data)
                    await handle_websocket_message(websocket, message)
                    
                except json.JSONDecodeError:
                    error_msg = {
                        "type": "error",
                        "message": "Invalid JSON format"
                    }
                    await websocket.send_text(json.dumps(error_msg))
                    
                except Exception as e:
                    logger.error(f"Error processing WebSocket message: {e}")
                    error_msg = {
                        "type": "error", 
                        "message": "Failed to process message"
                    }
                    await websocket.send_text(json.dumps(error_msg))
                    
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for user: {user_id}")
            
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        
    finally:
        manager.disconnect(websocket)

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom HTTP exception handler"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,
            "message": exc.detail,
            "status_code": exc.status_code
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """General exception handler"""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": True,
            "message": "Internal server error",
            "status_code": 500
        }
    )

# Import datetime for health check
from datetime import datetime

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=5001,
        reload=True,
        log_level="info"
    )
