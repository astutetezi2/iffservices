#!/usr/bin/env python3
"""
Simplified run script for the Communities Backend API
"""

import subprocess
import sys
import os
import time
import signal
import asyncio
from pathlib import Path

def check_requirements():
    """Check if required services are available"""
    print("🔍 Checking requirements...")
    
    # Check if MongoDB is running
    try:
        import pymongo
        client = pymongo.MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000)
        client.server_info()
        print("✅ MongoDB is running")
    except Exception:
        print("❌ MongoDB not found. Please install and start MongoDB:")
        print("   sudo apt install mongodb && sudo systemctl start mongodb")
        print("   Or use Docker: docker run -d -p 27017:27017 mongo:latest")
        return False
    
    # Check if Redis is running
    try:
        import redis
        r = redis.Redis(host='localhost', port=6379, socket_timeout=2)
        r.ping()
        print("✅ Redis is running")
    except Exception:
        print("❌ Redis not found. Please install and start Redis:")
        print("   sudo apt install redis-server && sudo systemctl start redis-server")
        print("   Or use Docker: docker run -d -p 6379:6379 redis:latest")
        return False
    
    return True

def install_dependencies():
    """Install Python dependencies"""
    print("📦 Installing Python dependencies...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                      check=True, capture_output=True)
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        return False

def run_server():
    """Run the FastAPI server"""
    print("🚀 Starting Communities Backend API on http://localhost:5001")
    print("📚 API Documentation: http://localhost:5001/docs")
    print("🔗 WebSocket endpoint: ws://localhost:5001/ws/{user_id}")
    print()
    print("Press Ctrl+C to stop the server")
    print("-" * 50)
    
    try:
        # Change to script directory
        os.chdir(Path(__file__).parent)
        
        # Run the server
        subprocess.run([sys.executable, "main.py"], check=True)
    except KeyboardInterrupt:
        print("\n👋 Server stopped")
    except subprocess.CalledProcessError as e:
        print(f"❌ Server failed to start: {e}")
        return False
    
    return True

def run_with_docker():
    """Run the entire stack with Docker Compose"""
    print("🐳 Starting with Docker Compose...")
    try:
        subprocess.run(["docker-compose", "up", "--build"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"❌ Docker Compose failed: {e}")
        return False
    except KeyboardInterrupt:
        print("\n🛑 Stopping Docker services...")
        subprocess.run(["docker-compose", "down"])
    
    return True

def main():
    """Main entry point"""
    print("🏠 Communities Backend API")
    print("=" * 40)
    
    # Check command line arguments
    if len(sys.argv) > 1:
        if sys.argv[1] == "--docker":
            return run_with_docker()
        elif sys.argv[1] == "--install":
            return install_dependencies()
        elif sys.argv[1] == "--help":
            print_help()
            return True
    
    # Regular startup process
    if not check_requirements():
        print("\n💡 Alternatively, run with Docker: python run.py --docker")
        return False
    
    if not install_dependencies():
        return False
    
    return run_server()

def print_help():
    """Print help message"""
    print("""
Usage: python run.py [option]

Options:
  --docker    Run the entire stack with Docker Compose
  --install   Install Python dependencies only
  --help      Show this help message

Default (no option): Check requirements, install dependencies, and run server

Examples:
  python run.py              # Normal startup
  python run.py --docker     # Run with Docker
  python run.py --install    # Install dependencies only
    """)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
