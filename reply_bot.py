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
LOG_FILE = "twitter_log.json"

# Initialize FastAPI app
app = FastAPI(title="Reply Bot", description="AI-powered Twitter engagement bot")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# Load or initialize data
def load_data():
    """Load existing log data"""
    global replied_log
    
    # Load reply log
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, "r") as f:
            replied_log = json.load(f)
    else:
        replied_log = []

# Initialize data
load_data()

def save_log(entry):
    """Save a log entry to file"""
    replied_log.append(entry)
    with open(LOG_FILE, "w") as f:
        json.dump(replied_log, f, indent=2)

def already_replied(tweet_id):
    """Check if we've already replied to a tweet"""
    return any(entry["id"] == tweet_id for entry in replied_log)

def handle_rate_limit(response_headers):
    """Handle Twitter API rate limits"""
    if "x-rate-limit-reset" in response_headers:
        reset_time = int(response_headers["x-rate-limit-reset"])
        now = int(time.time())
        wait_time = reset_time - now
        print(f"⏳ Rate limit hit. Wait for {wait_time} seconds.")
        time.sleep(max(wait_time, 0))
        print("✅ Rate limit window passed. Resuming...")

def generate_comment(tweet_text: str, username: str, keyword: str) -> str:
    """Generate a human-like comment using Gemini Flash 2.5"""
    try:
        prompt = f"""
You are a friendly, witty, and authentic Twitter user who replies like a blend of @levelsio (Pieter Levels) and @TheBoringMarketer. You show genuine interest, often reply quickly, casually, and add value in a human and sometimes playful way.
INPUT:

Tweet content: "{tweet_text}"
Author: @{username}
Topic/keyword: {keyword}

VOICE & PERSONALITY:

@levelsio style: Direct, slightly nerdy, drops casual insights, uses emojis sparingly but effectively, sometimes brutally honest
@TheBoringMarketer style: Observant, dry humor, calls out obvious things everyone thinks but doesn't say, marketing-aware but not salesy
Overall vibe: That friend who always has interesting takes and isn't trying too hard

ENGAGEMENT FRAMEWORK:

Hook with authenticity - React genuinely, not performatively
Add micro-value - One small insight, connection, or "aha" moment
Keep it conversational - Like you're continuing a chat, not starting a presentation
Timing matters - Reply like you saw this while scrolling, not like you're crafting content

REPLY STYLES (mix these up):

The "same here": Personal experience that relates
The "actually...": Gentle correction or addition with new info
The "wait, but...": Pointing out an interesting contradiction or edge case
The "reminds me of": Drawing unexpected but relevant connections
The "lol yeah": Simple agreement with a twist or observation

STRICT RULES:

Max 280 characters (check your count!)
NO hashtags, NO calls-to-action, NO obvious self-promotion
NO starting with "Great point!" or similar corporate speak
NO emoji overload (1-2 max, often none)
NO questions unless they feel natural in conversation
Avoid being the "well actually" person unless it's genuinely helpful

TONE CALIBRATION:

Too polished: "This is an excellent observation about market dynamics!"
Just right: "yeah this is why I stopped checking analytics daily, was driving me nuts"
Too casual: "lmaooo fr tho 💯💯💯"

CONTEXT AWARENESS:

If it's a complaint/vent: Empathize briefly, maybe share similar experience
If it's a win/achievement: Quick congrats, maybe relate to your own journey
If it's a hot take: Either build on it or offer a different angle (respectfully)
If it's asking for help: Give actual actionable advice, not generic encouragement

QUALITY CHECK:
Before submitting, ask: "Would I actually send this reply if I saw this tweet while scrolling at 11pm?" If no, revise.
Generate a short, natural, and engaging reply that sounds like it came from a real person who just happened to have something interesting to add.        
"""
        
        response = model.generate_content(prompt)
        comment = response.text.strip()
        
        # Ensure it's within Twitter's character limit
        if len(comment) > 280:
            comment = comment[:277] + "..."
        
        return comment
    except Exception as e:
        print(f"❌ Error generating comment: {e}")
        # Fallback to a simple comment
        return f"Interesting take on {keyword}! Thanks for sharing @{username}"

def search_and_reply(keywords: List[str]):
    """Search for tweets with keywords and reply to them"""
    results = []
    
    for keyword in keywords:
        print(f"🔍 Searching for: '{keyword}'")
        
        try:
            response = client.search_recent_tweets(
                query=keyword,
                max_results=10,
                expansions=["author_id"],
                tweet_fields=["created_at", "text"],
                user_fields=["username"]
            )

            if not response.data:
                print(f"⚠️ No tweets found for '{keyword}'")
                continue

            users = {u["id"]: u for u in response.includes["users"]}

            for tweet in response.data:
                tweet_id = tweet.id
                if already_replied(tweet_id):
                    print(f"⏭️ Already replied to tweet: {tweet_id}")
                    continue

                author_id = tweet.author_id
                username = users.get(author_id, {}).get("username", "unknown")
                tweet_text = tweet.text

                try:
                    # Generate a human-like comment
                    generated_comment = generate_comment(tweet_text, username, keyword)
                    print(f"🤖 Generated comment: {generated_comment}")
                    
                    # Post the reply
                    client.create_tweet(in_reply_to_tweet_id=tweet_id, text=generated_comment)

                    log_entry = {
                        "type": "tweet",
                        "id": tweet_id,
                        "author_id": author_id,
                        "author_username": username,
                        "original_tweet_text": tweet_text,
                        "generated_comment": generated_comment,
                        "keyword": keyword,
                        "url": f"https://twitter.com/{username}/status/{tweet_id}",
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    }
                    save_log(log_entry)
                    results.append(log_entry)
                    print(f"✅ Replied to tweet: {tweet_id}")
                    time.sleep(300)  # Wait 5 minutes between posts

                except tweepy.TooManyRequests as e:
                    print("⏳ Rate limit hit. Waiting for reset...")
                    handle_rate_limit(e.response.headers)
                    return results

        except tweepy.TooManyRequests as e:
            print("⏳ Rate limit hit. Waiting for reset...")
            handle_rate_limit(e.response.headers)
            return results
        except Exception as e:
            print(f"❌ Error for keyword '{keyword}': {e}")

        time.sleep(30)  # Wait 30 seconds between keywords

    return results

# Pydantic model for API requests
class BotRequest(BaseModel):
    keywords: List[str]

@app.get("/")
def root():
    """Root endpoint"""
    return {
        "message": "surfGeo Reply Bot is live. Use POST /run to start engaging with tweets.",
        "status": "Ready to reply to tweets"
    }

@app.post("/run")
def run_bot(request: BotRequest):
    """Run bot once with given keywords"""
    if not request.keywords:
        raise HTTPException(status_code=400, detail="Keywords are required.")
    
    results = search_and_reply(request.keywords)
    return {
        "message": f"✅ Completed. {len(results)} tweets replied with AI-generated comments.",
        "log": results
    }

@app.post("/run-continuous")
def run_bot_continuous(request: BotRequest):
    """Run bot continuously, auto-resuming after rate limits"""
    if not request.keywords:
        raise HTTPException(status_code=400, detail="Keywords are required.")
    
    all_results = []
    while True:
        try:
            results = search_and_reply(request.keywords)
            all_results.extend(results)
            
            if not results:  # No tweets found or limits reached
                print("🔄 No more tweets to process, waiting 15 minutes before next search...")
                time.sleep(900)  # Wait 15 minutes
                continue
                
        except KeyboardInterrupt:
            print("⏹️ Bot stopped by user")
            break
        except Exception as e:
            print(f"❌ Error in continuous mode: {e}")
            time.sleep(60)  # Wait 1 minute before retry
            continue
    
    return {
        "message": f"✅ Continuous mode completed. {len(all_results)} total tweets replied.",
        "log": all_results
    }
