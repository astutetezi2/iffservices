# Communities Backend API

A scalable real-time communities platform built with FastAPI, MongoDB, and Redis.

## Features

- **Communities Management**: Create, join, and manage communities
- **Threaded Discussions**: Organize conversations with threaded discussions
- **Real-time Messaging**: Live chat with WebSocket support
- **Broker-Consumer Model**: Redis pub/sub for scalable real-time updates
- **Scalable Database**: MongoDB with optimized indexes
- **RESTful API**: Complete CRUD operations for all entities

## Architecture

### Three-Column Layout
1. **Communities Column**: List all communities from database
2. **Threads Column**: Threads created by members in selected community
3. **Discussion Column**: Real-time chat messages for selected thread

### Tech Stack
- **Backend**: FastAPI (Python)
- **Database**: MongoDB with Motor (async driver)
- **Real-time**: WebSockets + Redis pub/sub
- **Message Broker**: Redis for broker-consumer pattern

## Installation

### Prerequisites
- Python 3.8+
- MongoDB
- Redis

### 1. Install Dependencies
```bash
cd python-backend
pip install -r requirements.txt
```

### 2. Setup MongoDB
```bash
# Install MongoDB (Ubuntu/Debian)
sudo apt install mongodb

# Start MongoDB service
sudo systemctl start mongodb
sudo systemctl enable mongodb

# Or using Docker
docker run -d -p 27017:27017 --name mongodb mongo:latest
```

### 3. Setup Redis
```bash
# Install Redis (Ubuntu/Debian)
sudo apt install redis-server

# Start Redis service
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Or using Docker
docker run -d -p 6379:6379 --name redis redis:latest
```

### 4. Environment Configuration
```bash
cp .env.example .env
# Edit .env with your configurations
```

### 5. Run the Server
```bash
python main.py
```

The server will start on `http://localhost:5001`

## API Documentation

Once the server is running, visit:
- **API Docs**: http://localhost:5001/docs
- **ReDoc**: http://localhost:5001/redoc

## API Endpoints

### Communities
- `GET /api/communities/` - List all communities
- `POST /api/communities/` - Create new community
- `GET /api/communities/{id}` - Get community details
- `PUT /api/communities/{id}` - Update community
- `DELETE /api/communities/{id}` - Delete community
- `POST /api/communities/{id}/join` - Join community
- `POST /api/communities/{id}/leave` - Leave community
- `GET /api/communities/{id}/members` - Get community members

### Threads
- `GET /api/threads/community/{community_id}` - Get threads in community
- `POST /api/threads/community/{community_id}` - Create new thread
- `GET /api/threads/{id}` - Get thread details
- `PUT /api/threads/{id}` - Update thread
- `DELETE /api/threads/{id}` - Delete thread
- `POST /api/threads/{id}/pin` - Pin/unpin thread
- `GET /api/threads/search` - Search threads

### Messages
- `GET /api/messages/thread/{thread_id}` - Get messages in thread
- `POST /api/messages/thread/{thread_id}` - Create new message
- `GET /api/messages/{id}` - Get message details
- `PUT /api/messages/{id}` - Update message
- `DELETE /api/messages/{id}` - Delete message
- `GET /api/messages/search` - Search messages
- `GET /api/messages/thread/{thread_id}/replies/{message_id}` - Get replies

### Members
- `GET /api/members/` - List all members
- `POST /api/members/` - Create new member
- `GET /api/members/{id}` - Get member details
- `GET /api/members/username/{username}` - Get member by username
- `PUT /api/members/{id}` - Update member
- `DELETE /api/members/{id}` - Delete/deactivate member
- `GET /api/members/{id}/communities` - Get member communities
- `GET /api/members/{id}/activity` - Get member activity stats

## WebSocket Connection

### Connect to WebSocket
```javascript
const ws = new WebSocket('ws://localhost:5001/ws/your-user-id');

ws.onopen = function(event) {
    console.log('Connected to WebSocket');
};

ws.onmessage = function(event) {
    const message = JSON.parse(event.data);
    console.log('Received:', message);
};
```

### WebSocket Messages

#### Join Community
```javascript
ws.send(JSON.stringify({
    action: 'join_community',
    community_id: 'community-id-here'
}));
```

#### Join Thread
```javascript
ws.send(JSON.stringify({
    action: 'join_thread',
    thread_id: 'thread-id-here'
}));
```

#### Typing Indicators
```javascript
// Start typing
ws.send(JSON.stringify({
    action: 'typing',
    thread_id: 'thread-id-here',
    user_id: 'your-user-id'
}));

// Stop typing
ws.send(JSON.stringify({
    action: 'stop_typing',
    thread_id: 'thread-id-here',
    user_id: 'your-user-id'
}));
```

## Real-time Events

The system automatically broadcasts the following events:

### Community Events
- `member_joined` - When someone joins a community
- `member_left` - When someone leaves a community
- `new_thread` - When a new thread is created

### Thread Events
- `new_message` - When a new message is posted
- `message_updated` - When a message is edited
- `message_deleted` - When a message is deleted
- `typing` - When someone is typing
- `stop_typing` - When someone stops typing

## Database Schema

### Communities Collection
```javascript
{
  _id: ObjectId,
  name: String,
  description: String,
  created_by: String,
  created_at: Date,
  member_count: Number,
  is_public: Boolean,
  tags: [String],
  avatar_url: String
}
```

### Threads Collection
```javascript
{
  _id: ObjectId,
  community_id: String,
  title: String,
  content: String,
  created_by: String,
  created_at: Date,
  updated_at: Date,
  message_count: Number,
  last_activity: Date,
  is_pinned: Boolean,
  tags: [String]
}
```

### Messages Collection
```javascript
{
  _id: ObjectId,
  thread_id: String,
  content: String,
  author: String,
  created_at: Date,
  edited_at: Date,
  is_edited: Boolean,
  reply_to: String,
  attachments: [String]
}
```

### Members Collection
```javascript
{
  _id: ObjectId,
  username: String,
  email: String,
  full_name: String,
  avatar_url: String,
  bio: String,
  joined_at: Date,
  is_active: Boolean,
  communities: [String]
}
```

## Performance Optimizations

### Database Indexes
- Communities: `name`, `created_by`, `is_public`
- Threads: `community_id`, `created_by`, `last_activity`, `(community_id, last_activity)`
- Messages: `thread_id`, `author`, `created_at`, `(thread_id, created_at)`
- Members: `username` (unique), `email` (unique)

### Redis Pub/Sub Channels
- `community:{community_id}` - Community-level events
- `thread:{thread_id}` - Thread-level events
- `global:notifications` - Global notifications

## Scaling Considerations

1. **Database Sharding**: Shard by community_id for horizontal scaling
2. **Redis Clustering**: Use Redis Cluster for high availability
3. **Load Balancing**: Multiple FastAPI instances behind a load balancer
4. **CDN**: Use CDN for file attachments and avatars
5. **Caching**: Implement Redis caching for frequently accessed data

## Development

### Running Tests
```bash
pytest tests/
```

### Code Formatting
```bash
black .
isort .
```

### Type Checking
```bash
mypy .
```

## TODO / Future Enhancements

- [ ] User authentication and authorization (JWT)
- [ ] File upload support for attachments
- [ ] Message reactions and emojis
- [ ] Push notifications
- [ ] Rate limiting
- [ ] Content moderation
- [ ] Search with Elasticsearch
- [ ] Message encryption
- [ ] Voice/video chat integration

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License
