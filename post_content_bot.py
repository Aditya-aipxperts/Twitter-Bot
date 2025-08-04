import os
import time
import json
from datetime import datetime
from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import tweepy
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Configure Gemini AI
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-2.5-flash')

# Configure Twitter API client
client = tweepy.Client(
    bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
    consumer_key=os.getenv("TWITTER_API_KEY"),
    consumer_secret=os.getenv("TWITTER_API_SECRET_KEY"),
    access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
    access_token_secret=os.getenv("TWITTER_ACCESS_SECRET")
)

# File paths
POST_LOG_FILE = "post_log.json"

# Initialize FastAPI app
app = FastAPI(title="Content Bot", description="AI-powered Twitter content bot for surfGeo and GEO")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load or initialize data
def load_data():
    """Load existing log data"""
    global posted_log
    
    # Load post log
    if os.path.exists(POST_LOG_FILE):
        with open(POST_LOG_FILE, "r") as f:
            posted_log = json.load(f)
    else:
        posted_log = []

# Initialize data
load_data()

def save_log(entry):
    """Save a log entry to file"""
    posted_log.append(entry)
    with open(POST_LOG_FILE, "w") as f:
        json.dump(posted_log, f, indent=2)

def generate_tweet_content(topic: str) -> str:
    """Generate original tweet content about surfGeo and GEO"""
    try:
        prompt = f"""
You are a knowledgeable expert in Generative Engine Optimization (GEO) and the founder of surfGeo, a platform focused on optimizing content for AI search engines and generative AI systems.

Topic: {topic}

Create an engaging, informative tweet (max 280 characters) that:

CONTENT RULES:
1. Provides valuable insights about GEO, AI search, or content optimization
2. Mentions surfGeo naturally and authentically
3. Uses a conversational, expert tone
4. Includes relevant hashtags (max 2-3)
5. Encourages engagement without being overly promotional
6. Focuses on education and thought leadership

TOPIC IDEAS:
- Generative Engine Optimization (GEO) insights
- AI search engine optimization tips
- Content strategies for AI systems
- surfGeo platform features and benefits
- Industry trends in AI-powered search
- Case studies and success stories

TONE EXAMPLES:
- "Just discovered something fascinating about how AI processes content..."
- "The future of SEO isn't about keywords anymore..."
- "Here's what most people miss about AI search optimization..."
- "surfGeo has been helping creators optimize for..."

Keep it under 280 characters and make it genuinely valuable to the audience.
"""
        
        response = model.generate_content(prompt)
        tweet_content = response.text.strip()
        
        # Ensure it's within Twitter's character limit
        if len(tweet_content) > 280:
            tweet_content = tweet_content[:277] + "..."
        
        return tweet_content
    except Exception as e:
        print(f"❌ Error generating tweet content: {e}")
        # Fallback tweet
        return f"Excited to share insights about Generative Engine Optimization (GEO) and how surfGeo is revolutionizing content optimization for AI search engines! #GEO #surfGeo #AIsearch"

def post_tweet(topic: str):
    """Post a single tweet about the given topic"""
    results = []
    
    try:
        # Generate tweet content
        tweet_content = generate_tweet_content(topic)
        print(f"🤖 Generated tweet: {tweet_content}")
        
        # Post the tweet
        response = client.create_tweet(text=tweet_content)
        
        if response.data:
            tweet_id = response.data["id"]
            
            log_entry = {
                "type": "post",
                "id": tweet_id,
                "content": tweet_content,
                "topic": topic,
                "url": f"https://twitter.com/user/status/{tweet_id}",
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
            save_log(log_entry)
            results.append(log_entry)
            print(f"✅ Posted tweet: {tweet_id}")
            
        return results
        
    except tweepy.TooManyRequests as e:
        print("⏳ Rate limit hit. Waiting for reset...")
        handle_rate_limit(e.response.headers)
        return results
    except Exception as e:
        print(f"❌ Error posting tweet: {e}")
        return results

def handle_rate_limit(response_headers):
    """Handle Twitter API rate limits"""
    if "x-rate-limit-reset" in response_headers:
        reset_time = int(response_headers["x-rate-limit-reset"])
        now = int(time.time())
        wait_time = reset_time - now
        print(f"⏳ Rate limit hit. Wait for {wait_time} seconds.")
        time.sleep(max(wait_time, 0))
        print("✅ Rate limit window passed. Resuming...")

def post_multiple_tweets(topics: List[str]):
    """Post multiple tweets with delays between them"""
    all_results = []
    
    for topic in topics:
        print(f"📝 Posting about: '{topic}'")
        
        results = post_tweet(topic)
        all_results.extend(results)
        
        if results:  # If tweet was posted successfully
            print("⏳ Waiting 10 minutes before next post...")
            time.sleep(600)  # Wait 10 minutes between posts
        else:
            print("❌ Failed to post tweet, stopping...")
            break
    
    return all_results

# Pydantic model for API requests
class PostRequest(BaseModel):
    topics: List[str]

@app.get("/")
def root():
    """Root endpoint"""
    return {
        "message": "surfGeo Content Bot is live. Use POST /post to create AI-powered tweets about surfGeo and GEO.",
        "status": "Ready to post tweets"
    }

@app.post("/post")
def post_single_tweet(request: PostRequest):
    """Post a single tweet about the first topic"""
    if not request.topics:
        raise HTTPException(status_code=400, detail="Topics are required.")
    
    results = post_tweet(request.topics[0])
    return {
        "message": f"✅ Posted tweet about '{request.topics[0]}'.",
        "log": results
    }

@app.post("/post-multiple")
def post_multiple_tweets_endpoint(request: PostRequest):
    """Post multiple tweets with delays"""
    if not request.topics:
        raise HTTPException(status_code=400, detail="Topics are required.")
    
    results = post_multiple_tweets(request.topics)
    return {
        "message": f"✅ Posted {len(results)} tweets about surfGeo and GEO.",
        "log": results
    }

@app.post("/post-continuous")
def post_continuous(request: PostRequest):
    """Post tweets continuously with delays"""
    if not request.topics:
        raise HTTPException(status_code=400, detail="Topics are required.")
    
    all_results = []
    topic_index = 0
    
    while True:
        try:
            # Get current topic
            topic = request.topics[topic_index % len(request.topics)]
            
            results = post_tweet(topic)
            all_results.extend(results)
            
            if results:  # If tweet was posted successfully
                topic_index += 1
                print("⏳ Waiting 15 minutes before next post...")
                time.sleep(900)  # Wait 15 minutes
            else:
                print("❌ Failed to post tweet, stopping...")
                break
                
        except KeyboardInterrupt:
            print("⏹️ Bot stopped by user")
            break
        except Exception as e:
            print(f"❌ Error in continuous mode: {e}")
            time.sleep(60)  # Wait 1 minute before retry
            continue
    
    return {
        "message": f"✅ Continuous posting completed. {len(all_results)} total tweets posted.",
        "log": all_results
    }
