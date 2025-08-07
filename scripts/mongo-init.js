// MongoDB initialization script
// This script runs when the container is first created

db = db.getSiblingDB('communities_db');

// Create collections with validation
db.createCollection('communities', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['name', 'description', 'created_by', 'created_at'],
      properties: {
        name: {
          bsonType: 'string',
          minLength: 1,
          maxLength: 100
        },
        description: {
          bsonType: 'string',
          maxLength: 1000
        },
        created_by: {
          bsonType: 'string',
          minLength: 1
        },
        created_at: {
          bsonType: 'date'
        },
        member_count: {
          bsonType: 'int',
          minimum: 0
        },
        is_public: {
          bsonType: 'bool'
        },
        tags: {
          bsonType: 'array',
          items: {
            bsonType: 'string'
          }
        }
      }
    }
  }
});

db.createCollection('threads', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['community_id', 'title', 'content', 'created_by', 'created_at'],
      properties: {
        community_id: {
          bsonType: 'string',
          minLength: 1
        },
        title: {
          bsonType: 'string',
          minLength: 1,
          maxLength: 200
        },
        content: {
          bsonType: 'string',
          minLength: 1
        },
        created_by: {
          bsonType: 'string',
          minLength: 1
        },
        created_at: {
          bsonType: 'date'
        },
        message_count: {
          bsonType: 'int',
          minimum: 0
        },
        is_pinned: {
          bsonType: 'bool'
        }
      }
    }
  }
});

db.createCollection('messages', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['thread_id', 'content', 'author', 'created_at'],
      properties: {
        thread_id: {
          bsonType: 'string',
          minLength: 1
        },
        content: {
          bsonType: 'string',
          minLength: 1,
          maxLength: 5000
        },
        author: {
          bsonType: 'string',
          minLength: 1
        },
        created_at: {
          bsonType: 'date'
        },
        is_edited: {
          bsonType: 'bool'
        }
      }
    }
  }
});

db.createCollection('members', {
  validator: {
    $jsonSchema: {
      bsonType: 'object',
      required: ['username', 'email', 'full_name', 'joined_at'],
      properties: {
        username: {
          bsonType: 'string',
          minLength: 3,
          maxLength: 30
        },
        email: {
          bsonType: 'string',
          pattern: '^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        },
        full_name: {
          bsonType: 'string',
          minLength: 1,
          maxLength: 100
        },
        joined_at: {
          bsonType: 'date'
        },
        is_active: {
          bsonType: 'bool'
        },
        communities: {
          bsonType: 'array',
          items: {
            bsonType: 'string'
          }
        }
      }
    }
  }
});

// Create indexes for better performance
// Communities indexes
db.communities.createIndex({ 'name': 1 }, { unique: true });
db.communities.createIndex({ 'created_by': 1 });
db.communities.createIndex({ 'is_public': 1 });
db.communities.createIndex({ 'created_at': -1 });

// Threads indexes
db.threads.createIndex({ 'community_id': 1 });
db.threads.createIndex({ 'created_by': 1 });
db.threads.createIndex({ 'last_activity': -1 });
db.threads.createIndex({ 'community_id': 1, 'last_activity': -1 });
db.threads.createIndex({ 'community_id': 1, 'is_pinned': -1, 'last_activity': -1 });

// Messages indexes
db.messages.createIndex({ 'thread_id': 1 });
db.messages.createIndex({ 'author': 1 });
db.messages.createIndex({ 'created_at': 1 });
db.messages.createIndex({ 'thread_id': 1, 'created_at': 1 });
db.messages.createIndex({ 'reply_to': 1 });

// Members indexes
db.members.createIndex({ 'username': 1 }, { unique: true });
db.members.createIndex({ 'email': 1 }, { unique: true });
db.members.createIndex({ 'communities': 1 });
db.members.createIndex({ 'is_active': 1 });

// Insert sample data
var adminUser = db.members.insertOne({
  username: 'admin',
  email: 'admin@communities.com',
  full_name: 'System Administrator',
  bio: 'System administrator and community manager',
  joined_at: new Date(),
  is_active: true,
  communities: []
});

var sampleUser = db.members.insertOne({
  username: 'john_doe',
  email: 'john@example.com',
  full_name: 'John Doe',
  bio: 'Software developer and tech enthusiast',
  joined_at: new Date(),
  is_active: true,
  communities: []
});

// Create sample community
var community = db.communities.insertOne({
  name: 'General Discussion',
  description: 'A place for general discussions and announcements',
  created_by: 'admin',
  created_at: new Date(),
  member_count: 2,
  is_public: true,
  tags: ['general', 'announcements']
});

// Update members to include the community
db.members.updateMany(
  { username: { $in: ['admin', 'john_doe'] } },
  { $push: { communities: community.insertedId.toString() } }
);

// Create sample thread
var thread = db.threads.insertOne({
  community_id: community.insertedId.toString(),
  title: 'Welcome to the Community!',
  content: 'Welcome everyone! This is our first thread. Feel free to introduce yourselves and start discussions.',
  created_by: 'admin',
  created_at: new Date(),
  updated_at: new Date(),
  message_count: 1,
  last_activity: new Date(),
  is_pinned: true,
  tags: ['welcome', 'introduction']
});

// Create sample message
db.messages.insertOne({
  thread_id: thread.insertedId.toString(),
  content: 'Hello everyone! Excited to be part of this community. Looking forward to great discussions!',
  author: 'john_doe',
  created_at: new Date(),
  is_edited: false,
  attachments: []
});

// Update thread message count
db.threads.updateOne(
  { _id: thread.insertedId },
  { $inc: { message_count: 1 }, $set: { last_activity: new Date() } }
);

print('Database initialized successfully with sample data!');
