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
REPLY_LOG_FILE = "reply_log.json"
POST_LOG_FILE = "post_log.json"

# Initialize FastAPI app
app = FastAPI(title="Twitter Bot")

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
    global replied_log, posted_log
    
    # Load reply log
    if os.path.exists(REPLY_LOG_FILE):
        with open(REPLY_LOG_FILE, "r") as f:
            replied_log = json.load(f)
    else:
        replied_log = []
    
    # Load post log
    if os.path.exists(POST_LOG_FILE):
        with open(POST_LOG_FILE, "r") as f:
            posted_log = json.load(f)
    else:
        posted_log = []

# Initialize data
load_data()

def save_reply_log(entry):
    """Save a reply log entry to file"""
    replied_log.append(entry)
    with open(REPLY_LOG_FILE, "w") as f:
        json.dump(replied_log, f, indent=2)

def save_post_log(entry):
    """Save a post log entry to file"""
    posted_log.append(entry)
    with open(POST_LOG_FILE, "w") as f:
        json.dump(posted_log, f, indent=2)

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

# ===== REPLY BOT FUNCTIONS =====

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
                        "type": "reply",
                        "id": tweet_id,
                        "author_id": author_id,
                        "author_username": username,
                        "original_tweet_text": tweet_text,
                        "generated_comment": generated_comment,
                        "keyword": keyword,
                        "url": f"https://twitter.com/{username}/status/{tweet_id}",
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    }
                    save_reply_log(log_entry)
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

        time.sleep(30)  

    return results

# ===== POST CONTENT BOT FUNCTIONS =====

def generate_tweet_content(topic: str) -> str:
    """Generate original tweet content about surfGeo and GEO"""
    try:
        prompt = f"""
You are a friendly, witty, and authentic Twitter user who creates content like a blend of @levelsio (Pieter Levels) and @TheBoringMarketer. You craft original tweets that feel genuine, valuable, and scroll-stopping without trying too hard.

INPUT:

Keyword: {topic}
VOICE & PERSONALITY:

@levelsio style: Direct, slightly nerdy, drops casual insights, uses emojis sparingly but effectively, sometimes brutally honest, shares personal experiences and metrics
@TheBoringMarketer style: Observant, dry humor, calls out obvious things everyone thinks but doesn't say, marketing-aware but not salesy, cuts through BS
Overall vibe: That friend who always has interesting takes, shares real experiences, and isn't trying too hard to impress
MAGNETIC TWEET FRAMEWORK:

1. HOOK PATTERNS (choose one that fits the keyword):

Shock Reality: "95% of founders do this backwards..."
Contrarian Take: "Everyone says X, but I've seen Y work better..."
Fortune Teller: "In 12 months, this will be irrelevant..."
Personal Confession: "Made this $10k mistake so you don't have to..."
Pattern Recognition: "Same thing that killed Blockbuster is happening to..."
Insider Secret: "Industry won't tell you this but..."
2. POWER LANGUAGE:

Use action-packed openers: "Tested", "Discovered", "Built", "Learned", "Noticed"
Replace weak words: "think" → "realized", "good" → "game-changing", "try" → "tested"
Include specific numbers when possible: "$47k", "3.2x", "73%", "Day 47"
3. MICRO SOCIAL PROOF (when natural):

Personal credibility: "after building 3 companies", "learned from 500+ customer calls"
Metrics that matter: "$0 to $50k MRR", "10 failed projects before this one"
Industry experience: "spent 5 years in VC", "hired 100+ people"
4. NARRATIVE STRUCTURES:

Thread Starter (if multi-tweet):

Problem → Solution Arc: Pain point → surprising solution → result
Timeline Story: "6 months ago I was X... today I'm Y... here's what changed"
Mistake → Learning: "Biggest mistake: X... What I learned: Y... New approach: Z"
Single Tweet:

Observation → Insight: "Noticed X... realized Y"
Contrarian → Evidence: "Everyone does X... but data shows Y"
Personal → Universal: "My experience: X... applies everywhere because Y"
5. CONTENT PILLARS (mix these based on keyword):

Behind-the-scenes: Real numbers, failures, lessons learned
Contrarian takes: Challenge common wisdom with experience
Pattern spotting: Connect dots others miss
Tool/resource shares: What actually works (with context)
Industry observations: Call out obvious things people don't say
Personal experiments: "Tested this for 30 days, here's what happened"
STRICT CONTENT RULES:

Max 280 characters for single tweets (check your count!)
For threads: Each tweet must be valuable standalone
NO obvious self-promotion or sales pitches
NO corporate speak or buzzwords
NO emoji overload (1-2 max, strategic placement)
NO generic motivational quotes
Start with impact, not setup ("Here's what I learned about X")
TONE CALIBRATION:

Too corporate: "Implementing strategic initiatives to optimize our customer acquisition funnel"
Just right: "spent $3k on ads, got 2 customers. switched to cold email, got 47. sometimes simple wins"
Too casual: "omggg this hack is absolutely insane you guys 🔥🔥🔥"
CONTENT QUALITY MATRIX:

High Value Posts:

Share specific numbers/results
Challenge conventional wisdom with experience
Reveal non-obvious insights
Tell relatable failure stories with lessons
Avoid:

Generic advice everyone gives
Humble brags disguised as lessons
Obvious observations without insight
Content that sounds like a LinkedIn post
FINAL QUALITY CHECKS:

Scroll Test: Would this make someone stop scrolling?
Value Test: What specific thing does someone learn/gain?
Authenticity Test: Does this sound like something I'd actually say?
Engagement Test: Would I want to reply to this?
Uniqueness Test: Have I seen this exact take 100 times before?
OUTPUT REQUIREMENTS: Generate an original tweet that:

Hooks attention in the first 7 words
Delivers genuine value or insight
Feels conversational and authentic
Could spark meaningful replies
Relates directly to the keyword/topic
Sounds like it came from real experience
Remember: The best tweets feel like overheard conversations from someone who actually knows what they're talking about.
"""
        
        response = model.generate_content(prompt)
        tweet_content = response.text.strip()
        
        # Ensure it's within Twitter's character limit
        if len(tweet_content) > 280:
            tweet_content = tweet_content[:277] + "..."
        
        return tweet_content
    except Exception as e:
        print(f"❌ Error generating tweet content: {e}")
    return f"been diving deep into {topic} lately... the rabbit hole goes deeper than most people realize"


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
            save_post_log(log_entry)
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

# ===== PYDANTIC MODELS =====

class ReplyRequest(BaseModel):
    keywords: List[str]

class PostRequest(BaseModel):
    topics: List[str]

# ===== API ENDPOINTS =====

@app.get("/")
def root():
    """Root endpoint"""
    return {
        "message": "Unified surfGeo Twitter Bot is live!",
        "endpoints": {
            "reply": "POST /reply - Reply to tweets with keywords",
            "reply-continuous": "POST /reply-continuous - Reply continuously",
            "post": "POST /post - Post single tweet",
            "post-multiple": "POST /post-multiple - Post multiple tweets",
            "post-continuous": "POST /post-continuous - Post continuously"
        },
        "status": "Ready to post and reply to tweets"
    }

# Reply Bot Endpoints
@app.post("/reply")
def run_reply_bot(request: ReplyRequest):
    """Run reply bot once with given keywords"""
    if not request.keywords:
        raise HTTPException(status_code=400, detail="Keywords are required.")
    
    results = search_and_reply(request.keywords)
    return {
        "message": f"✅ Reply bot completed. {len(results)} tweets replied with AI-generated comments.",
        "log": results
    }

@app.post("/reply-continuous")
def run_reply_bot_continuous(request: ReplyRequest):
    """Run reply bot continuously, auto-resuming after rate limits"""
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
            print("⏹️ Reply bot stopped by user")
            break
        except Exception as e:
            print(f"❌ Error in continuous reply mode: {e}")
            time.sleep(60)  # Wait 1 minute before retry
            continue
    
    return {
        "message": f"✅ Continuous reply mode completed. {len(all_results)} total tweets replied.",
        "log": all_results
    }

# Post Content Bot Endpoints
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
            print("⏹️ Post bot stopped by user")
            break
        except Exception as e:
            print(f"❌ Error in continuous post mode: {e}")
            time.sleep(60)  # Wait 1 minute before retry
            continue
    
    return {
        "message": f"✅ Continuous posting completed. {len(all_results)} total tweets posted.",
        "log": all_results
    }
