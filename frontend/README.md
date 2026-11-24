# YouTube-Instagram Bot - SaaS Frontend

A modern web interface for managing YouTube, Instagram, and Rumble automation.

## Features

- **Dashboard**: Real-time statistics and activity monitoring
- **YouTube Management**: Upload videos and Shorts
- **Instagram Management**: Post images and reels, grow followers
- **Rumble Automation**: View generation and engagement
- **Engagement Tools**: Follow, unfollow, like automation
- **Batch Automation**: Schedule batch uploads
- **Scheduler**: Job queue and scheduling

## Installation

### Prerequisites

- Python 3.8+
- Node.js 16+ (optional, for development)

### Setup

1. Clone the repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the bot:
```bash
python main.py
```

4. Run the API server:
```bash
python api_server.py
```

5. Open the frontend:
```bash
# Open frontend/index.html in your browser
# Or use a simple HTTP server:
python -m http.server 8080
```

## Configuration

Environment variables:

```env
BOT_MASTER_KEY=your_fernet_key_here
LOG_LEVEL=INFO
```

## API Endpoints

### Dashboard
```
GET /api/dashboard
```

### Rate Limits
```
GET /api/rate-limits
```

### System Status
```
GET /api/status
```

### Upload Video
```
POST /api/youtube/upload
Content-Type: application/json

{
    "title": "Video Title",
    "description": "Video description",
    "type": "short"
}
```

### Post Content
```
POST /api/instagram/post
Content-Type: application/json

{
    "content_id": "content_123",
    "caption": "Post caption"
}
```

### Generate Views
```
POST /api/rumble/views
Content-Type: application/json

{
    "video_url": "https://rumble.com/video",
    "views": 1000
}
```

## Safety Limits

The bot includes conservative rate limits to prevent account bans:

- **Instagram**: 15 follows/hour, 300 actions/day
- **YouTube**: 10 uploads/day, 50 views/hour
- **Rumble**: 50 views/day

## Development

### Frontend Development

The frontend is built with:
- HTML5
- CSS3 (with custom properties)
- Vanilla JavaScript
- FontAwesome icons

### Backend Development

The backend includes:
- Python 3.11+
- SQLite for storage
- SQLAlchemy ORM
- cryptography for encryption

## Deployment

### Production

1. Set up environment variables
2. Run migrations (if any)
3. Start the API server
4. Deploy the frontend to a static host

### Docker (optional)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

## Support

For issues and questions, please contact support.

## License

Proprietary - YouTube-Instagram Bot SaaS Platform
