# INS-YT Bot - Instagram and YouTube Growth Automation Platform

Production-grade bot for growing Instagram followers and YouTube subscribers.
Features: real account targeting, daily activity filtering, YPP monetization tracking, SaaS web dashboard.

## Features

### Instagram
- Gender Targeting: male/female via gender-skewed hashtags
- City Targeting: 20+ cities built-in (Mumbai, Delhi, London, New York...)
- State Targeting: 15+ states/regions (Maharashtra, California, Texas...)
- Business Niche: 12 industries (Restaurant, Fashion, Fitness, Real Estate, Tech, ...)
- Combined Targeting: stack any criteria (female + mumbai + fashion)
- Activity Filter: skips inactive accounts (30+ days), ghost accounts, bots
- Engage Back (optional): like/comment on followers posts - boosts follow-back 2-3x
- Unfollow non-reciprocals, like by hashtag, follow-back automation

### YouTube Monetization (YPP)
- Real Subscriber Growth: keyword search + bot filter + subscribe to genuine channels only
- Watch Time Accumulation: realistic watch sessions (60-85%) toward 4,000-hour YPP threshold
- YPP Progress Tracker: live progress bars for watch hours and subscribers
- Search and Engage: auto like/comment/subscribe (quota-tracked)
- Engage with Subscribers (optional): like/comment on niche videos - triggers reciprocal watch time

### Magic Mode
Paste YouTube URL + Instagram username -> bot likes, comments, subscribes, finds similar videos,
follows IG users in that niche, and likes their posts. Live terminal progress log.

### Rumble
View generation, auto-like, auto-comment

## Quick Start

    git clone https://github.com/Manash8666/INS-YT_Bot.git
    cd INS-YT_Bot
    pip install -r requirements.txt
    cp .env.example .env  # add your credentials
    python main.py        # API on :8000
    # open http://localhost:8080 (after starting frontend server)

## Tech Stack
FastAPI + Uvicorn, SQLAlchemy, cryptography.Fernet, httpx, google-api-python-client,
Pydantic-Settings, structlog, Vanilla HTML/CSS/JS frontend, Docker + nginx

## Environment Variables
SECRET_KEY, BOT_MASTER_KEY, DATABASE_URL, INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_USER_ID,
YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN, YOUTUBE_CHANNEL_ID
See .env.example for full list.

## Safety Rate Limits
Instagram: 150 follows/day, 300 likes/day, 90-180s delay between actions
YouTube: 50 likes, 20 comments, 30 subscribes per day, 10,000 API quota units/day

## Real Account Filtering
Instagram: account must have 10+ followers, 3+ posts, posted in last 30 days
YouTube: channel must have 1+ videos, 1+ subscribers, 10+ views, non-bot title

## Getting Credentials
Instagram: developers.facebook.com -> App -> Instagram Graph API -> long-lived token
YouTube: console.cloud.google.com -> YouTube Data API v3 -> OAuth2 -> refresh token
Enter all credentials in the Settings page of the dashboard.

## License
MIT