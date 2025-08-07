import os
import time
import json
import threading
from datetime import datetime, time as dt_time
from typing import List
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import tweepy
import google.generativeai as genai
import schedule
import warnings

# Suppress Tweepy syntax warnings for Python 3.13
warnings.filterwarnings("ignore", category=SyntaxWarning)

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

# Global variables for scheduled tasks
scheduled_keywords = []
scheduled_topics = []
scheduled_times = []
reply_index = 0
post_index = 0
task_counter = 0  # Track completed tasks
total_daily_tasks = 6  # 3 replies + 3 posts per day
scheduler_running = False  # Track if scheduler is running
scheduler_thread = None  # Store scheduler thread

# Initialize FastAPI app
app = FastAPI(title="Twitter Bot")
app.mount("/static", StaticFiles(directory="static"), name="static")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/dashboard", include_in_schema=False)
def serve_index():
    return FileResponse("static/index.html")

# Load or initialize data
def load_data():
    """Load existing log data"""
    global replied_log, posted_log
    print(f"📂 Checking if files exist: {REPLY_LOG_FILE}, {POST_LOG_FILE}")
    print(f"📂 REPLY_LOG_FILE exists: {os.path.exists(REPLY_LOG_FILE)}")
    print(f"📂 POST_LOG_FILE exists: {os.path.exists(POST_LOG_FILE)}")
    
    if os.path.exists(REPLY_LOG_FILE):
        try:
            with open(REPLY_LOG_FILE, "r") as f:
                replied_log = json.load(f)
        except Exception as e:
            print(f"❌ Error loading reply log: {e}")
            replied_log = []
    else:
        replied_log = []
    
    if os.path.exists(POST_LOG_FILE):
        try:
            with open(POST_LOG_FILE, "r") as f:
                posted_log = json.load(f)
        except Exception as e:
            print(f"❌ Error loading post log: {e}")
            posted_log = []
    else:
        posted_log = []

# Initialize data
load_data()

def save_reply_log(entry):
    """Save a reply log entry to file"""
    try:
        replied_log.append(entry)
        with open(REPLY_LOG_FILE, "w") as f:
            json.dump(replied_log, f, indent=2)
    except Exception as e:
        print(f"❌ Error saving reply log: {e}")

def save_post_log(entry):
    """Save a post log entry to file"""
    try:
        posted_log.append(entry)
        with open(POST_LOG_FILE, "w") as f:
            json.dump(posted_log, f, indent=2)
    except Exception as e:
        print(f"❌ Error saving post log: {e}")

def already_replied(tweet_id):
    """Check if we've already replied to a tweet"""
    if not os.path.exists(REPLY_LOG_FILE):
        print(f"⚠️ Reply log file missing: {REPLY_LOG_FILE}")
        return False
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
        if len(comment) > 280:
            comment = comment[:277] + "..."
        return comment
    except Exception as e:
        print(f"❌ Error generating comment: {e}")
        return f"Interesting take on {keyword}! Thanks for sharing @{username}"

def search_and_reply(keywords: List[str], max_replies: int = 3):
    """Search for tweets with keywords and reply to up to max_replies"""
    results = []
    replies_count = 0
    
    if keywords:
        keyword = keywords[0]
        print(f"🔍 Searching for: '{keyword}' (using first keyword only)")
        
        for attempt in range(3):  # Retry up to 3 times
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
                    return results

                users = {u["id"]: u for u in response.includes["users"]}

                for tweet in response.data:
                    if replies_count >= max_replies:
                        break
                    tweet_id = tweet.id
                    if already_replied(tweet_id):
                        print(f"⏭️ Already replied to tweet: {tweet_id}")
                        continue

                    author_id = tweet.author_id
                    username = users.get(author_id, {}).get("username", "unknown")
                    tweet_text = tweet.text

                    try:
                        generated_comment = generate_comment(tweet_text, username, keyword)
                        print(f"🤖 Generated comment: {generated_comment}")
                        response = client.create_tweet(in_reply_to_tweet_id=tweet_id, text=generated_comment)

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
                        replies_count += 1
                        time.sleep(60)  # Increased delay to avoid rate limits

                    except tweepy.TooManyRequests as e:
                        handle_rate_limit(e.response.headers)
                        continue
                    except Exception as e:
                        print(f"❌ Error replying to tweet {tweet_id}: {str(e)} - Response: {getattr(e, 'response', 'No response')}")
                        continue

                return results

            except tweepy.TooManyRequests as e:
                handle_rate_limit(e.response.headers)
                continue
            except Exception as e:
                print(f"❌ Error for keyword '{keyword}' (attempt {attempt + 1}): {str(e)} - Response: {getattr(e, 'response', 'No response')}")
                time.sleep(10)
                continue
        print(f"❌ Failed to search and reply for '{keyword}' after 3 attempts")
    return results

# ===== POST CONTENT BOT FUNCTIONS =====

def generate_tweet_content(topic: str) -> str:
    """Generate original tweet content"""
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

Max 300 characters for single tweets 
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

DO not use * in the tweet content.
"""
        response = model.generate_content(prompt)
        tweet_content = response.text.strip()
        if len(tweet_content) > 280:
            tweet_content = tweet_content[:277] + "..."
        return tweet_content
    except Exception as e:
        print(f"❌ Error generating tweet content: {e}")
        return f"been diving deep into {topic} lately... the rabbit hole goes deeper than most people realize"

def post_tweet(topic: str):
    """Post a single tweet about the given topic"""
    results = []
    
    for attempt in range(3):  # Retry up to 3 times
        try:
            tweet_content = generate_tweet_content(topic)
            print(f"🤖 Generated tweet: {tweet_content}")
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
            else:
                print(f"⚠️ No data in Twitter response: {response}")
                
        except tweepy.TooManyRequests as e:
            handle_rate_limit(e.response.headers)
            continue
        except Exception as e:
            print(f"❌ Error posting tweet (attempt {attempt + 1}): {str(e)} - Response: {getattr(e, 'response', 'No response')}")
            time.sleep(10)
            continue
    print(f"❌ Failed to post tweet for topic '{topic}' after 3 attempts")
    return results

def post_multiple_tweets(topics: List[str], max_posts: int = 3):
    """Post up to max_posts tweets with delays"""
    results = []
    posts_count = 0
    
    for topic in topics:
        if posts_count >= max_posts:
            break
        print(f"📝 Posting about: '{topic}'")
        results.extend(post_tweet(topic))
        posts_count += 1
        time.sleep(300)
    
    return results

# ===== SCHEDULING FUNCTIONS =====

def schedule_tasks(keywords: List[str], topics: List[str], times: List[str]):
    """Schedule reply and post tasks for user-provided times"""
    global scheduled_keywords, scheduled_topics, scheduled_times, task_counter, scheduler_running, scheduler_thread
    
    # Clear any existing schedules
    schedule.clear()
    
    # Clear logs when scheduling
    clear_logs()
    
    # Store keywords, topics, and times globally
    scheduled_keywords = keywords
    scheduled_topics = topics
    scheduled_times = times
    task_counter = 0  # Reset task counter for new schedule
    
    # Validate times
    try:
        for t in times:
            datetime.strptime(t, "%H:%M")
    except ValueError:
        raise HTTPException(status_code=400, detail="Times must be in HH:MM format (24-hour clock).")
    
    # Schedule tasks (alternating reply and post)
    for i, t in enumerate(times):
        if i % 2 == 0:
            schedule.every().day.at(t).do(scheduled_reply_task)
        else:
            schedule.every().day.at(t).do(scheduled_post_task)
    
    print(f"✅ Scheduled tasks for keywords: {keywords}")
    print(f"✅ Scheduled tasks for topics: {topics}")
    print(f"✅ Scheduled tasks at times: {times}")
    print("🧹 Log files cleared for fresh start")
    
    # Start scheduler if not already running
    if not scheduler_running:
        scheduler_running = True
        scheduler_thread = threading.Thread(target=run_scheduler)
        scheduler_thread.daemon = True
        scheduler_thread.start()
        print("🚀 Scheduler started successfully")

def scheduled_reply_task():
    """Scheduled task for replying to tweets"""
    global scheduled_keywords, reply_index, task_counter
    print(f"⏰ Reply task triggered at {datetime.now().strftime('%H:%M:%S')}")
    print(f"🔍 Keywords: {scheduled_keywords}, Index: {reply_index}, Counter: {task_counter}")
    
    if scheduled_keywords:
        current_keyword = scheduled_keywords[reply_index % len(scheduled_keywords)]
        print(f"🔍 Using keyword: '{current_keyword}' (index {reply_index})")
        try:
            results = search_and_reply([current_keyword], max_replies=3)
            print(f"✅ Reply task completed: {results}")
        except Exception as e:
            print(f"❌ Reply task failed: {str(e)}")
        reply_index += 1
        task_counter += 1
        
        if task_counter >= total_daily_tasks:
            print("🎉 All daily tasks completed! Stopping bot automatically...")
            schedule.clear()
            global scheduler_running
            scheduler_running = False
            print("✅ Bot stopped automatically after completing all scheduled tasks")
            print("🔄 Ready for new schedule tomorrow")
    else:
        print("⚠️ No keywords available for replying")

def scheduled_post_task():
    """Scheduled task for posting tweets"""
    global scheduled_topics, post_index, task_counter
    print(f"⏰ Post task triggered at {datetime.now().strftime('%H:%M:%S')}")
    print(f"📝 Topics: {scheduled_topics}, Index: {post_index}, Counter: {task_counter}")
    
    if scheduled_topics:
        current_topic = scheduled_topics[post_index % len(scheduled_topics)]
        print(f"📝 Using topic: '{current_topic}' (index {post_index})")
        try:
            results = post_multiple_tweets([current_topic], max_posts=1)
            print(f"✅ Post task completed: {results}")
        except Exception as e:
            print(f"❌ Post task failed: {str(e)}")
        post_index += 1
        task_counter += 1
        
        if task_counter >= total_daily_tasks:
            print("🎉 All daily tasks completed! Stopping bot automatically...")
            schedule.clear()
            global scheduler_running
            scheduler_running = False
            print("✅ Bot stopped automatically after completing all scheduled tasks")
            print("🔄 Ready for new schedule tomorrow")
    else:
        print("⚠️ No topics available for posting")

def clear_logs():
    """Clear log files daily"""
    global replied_log, posted_log
    
    try:
        replied_log.clear()
        posted_log.clear()
        
        with open(REPLY_LOG_FILE, "w") as f:
            json.dump([], f)
        with open(POST_LOG_FILE, "w") as f:
            json.dump([], f)
        
        print("🧹 Daily log files cleared successfully")
    except Exception as e:
        print(f"❌ Error clearing logs: {e}")

def run_scheduler():
    """Run the scheduler"""
    global scheduler_running
    print("🔄 Scheduler thread started")
    while scheduler_running:
        try:
            print(f"🔄 Checking pending tasks at {datetime.now().strftime('%H:%M:%S')}")
            schedule.run_pending()
            time.sleep(60)
        except Exception as e:
            print(f"❌ Scheduler error: {str(e)}")
            time.sleep(60)
    print("⏹️ Scheduler stopped")

# ===== PYDANTIC MODELS =====

class BotRequest(BaseModel):
    keywords: List[str]
    topics: List[str]
    times: List[str]

# ===== API ENDPOINTS =====

@app.get("/")
def root():
    """Root endpoint"""
    return {
        "message": "Twitter Bot is live!",
        "endpoints": {
            "schedule": "POST /schedule - Schedule reply and post tasks with custom times",
            "logs": "GET /logs - Get reply and post logs",
            "clear_logs": "POST /clear_logs - Clear all logs",
            "stop": "POST /stop - Stop the bot and clear scheduled tasks"
        },
        "status": "Ready to schedule tasks"
    }

@app.post("/schedule")
def schedule_bot(request: BotRequest):
    """Schedule bot tasks with given keywords, topics, and times"""
    if not request.keywords or not request.topics or not request.times:
        raise HTTPException(status_code=400, detail="Keywords, topics, and times are required.")
    
    if len(request.times) < total_daily_tasks:
        raise HTTPException(status_code=400, detail=f"At least {total_daily_tasks} times are required for {total_daily_tasks} tasks (3 replies + 3 posts).")
    
    schedule_tasks(request.keywords, request.topics, request.times)
    return {
        "message": f"✅ Bot scheduled to reply to 3 tweets and post 3 tweets at specified times: {request.times}",
        "keywords": request.keywords,
        "topics": request.topics,
        "times": request.times
    }

@app.get("/logs")
def get_logs():
    """Get reply and post logs"""
    return {
        "reply_log": replied_log,
        "post_log": posted_log,
        "task_counter": task_counter,
        "total_tasks": total_daily_tasks,
        "is_completed": task_counter >= total_daily_tasks
    }

@app.post("/clear_logs")
def clear_logs_endpoint():
    """Clear all logs"""
    try:
        clear_logs()
        return {"message": "Logs cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing logs: {str(e)}")

@app.post("/stop")
def stop_bot():
    """Stop the bot and clear all scheduled tasks"""
    try:
        global scheduler_running, task_counter
        scheduler_running = False
        schedule.clear()
        task_counter = 0
        return {"message": "Bot stopped successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error stopping bot: {str(e)}")


# import os
# import time
# import json
# import threading
# from datetime import datetime, time as dt_time
# from typing import List
# from fastapi import FastAPI, HTTPException
# from fastapi.staticfiles import StaticFiles
# from fastapi.responses import FileResponse
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel
# from dotenv import load_dotenv
# import tweepy
# import google.generativeai as genai
# import schedule

# # Load environment variables
# load_dotenv()

# # Configure Gemini AI
# genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
# model = genai.GenerativeModel('gemini-2.5-flash')

# # Configure Twitter API client
# client = tweepy.Client(
#     bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
#     consumer_key=os.getenv("TWITTER_API_KEY"),
#     consumer_secret=os.getenv("TWITTER_API_SECRET_KEY"),
#     access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
#     access_token_secret=os.getenv("TWITTER_ACCESS_SECRET")
# )

# # File paths
# REPLY_LOG_FILE = "reply_log.json"
# POST_LOG_FILE = "post_log.json"

# # Global variables for scheduled tasks
# scheduled_keywords = []
# scheduled_topics = []
# scheduled_times = []
# reply_index = 0
# post_index = 0
# task_counter = 0  # Track completed tasks
# total_daily_tasks = 6  # 3 replies + 3 posts per day
# scheduler_running = False  # Track if scheduler is running
# scheduler_thread = None  # Store scheduler thread

# # Initialize FastAPI app
# app = FastAPI(title="Twitter Bot")
# app.mount("/static", StaticFiles(directory="static"), name="static")

# # Add CORS middleware
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# @app.get("/dashboard", include_in_schema=False)
# def serve_index():
#     return FileResponse("static/index.html")

# # Load or initialize data
# def load_data():
#     """Load existing log data"""
#     global replied_log, posted_log
    
#     if os.path.exists(REPLY_LOG_FILE):
#         with open(REPLY_LOG_FILE, "r") as f:
#             replied_log = json.load(f)
#     else:
#         replied_log = []
    
#     if os.path.exists(POST_LOG_FILE):
#         with open(POST_LOG_FILE, "r") as f:
#             posted_log = json.load(f)
#     else:
#         posted_log = []

# # Initialize data
# load_data()

# def save_reply_log(entry):
#     """Save a reply log entry to file"""
#     replied_log.append(entry)
#     with open(REPLY_LOG_FILE, "w") as f:
#         json.dump(replied_log, f, indent=2)

# def save_post_log(entry):
#     """Save a post log entry to file"""
#     posted_log.append(entry)
#     with open(POST_LOG_FILE, "w") as f:
#         json.dump(posted_log, f, indent=2)

# def already_replied(tweet_id):
#     """Check if we've already replied to a tweet"""
#     return any(entry["id"] == tweet_id for entry in replied_log)

# def handle_rate_limit(response_headers):
#     """Handle Twitter API rate limits"""
#     if "x-rate-limit-reset" in response_headers:
#         reset_time = int(response_headers["x-rate-limit-reset"])
#         now = int(time.time())
#         wait_time = reset_time - now
#         print(f"⏳ Rate limit hit. Wait for {wait_time} seconds.")
#         time.sleep(max(wait_time, 0))
#         print("✅ Rate limit window passed. Resuming...")

# # ===== REPLY BOT FUNCTIONS =====

# def generate_comment(tweet_text: str, username: str, keyword: str) -> str:
#     """Generate a human-like comment using Gemini Flash 2.5"""
#     try:
#         prompt = f"""
# You are a friendly, witty, and authentic Twitter user who replies like a blend of @levelsio (Pieter Levels) and @TheBoringMarketer. You show genuine interest, often reply quickly, casually, and add value in a human and sometimes playful way.
# INPUT:

# Tweet content: "{tweet_text}"
# Author: @{username}
# Topic/keyword: {keyword}

# VOICE & PERSONALITY:

# @levelsio style: Direct, slightly nerdy, drops casual insights, uses emojis sparingly but effectively, sometimes brutally honest
# @TheBoringMarketer style: Observant, dry humor, calls out obvious things everyone thinks but doesn't say, marketing-aware but not salesy
# Overall vibe: That friend who always has interesting takes and isn't trying too hard

# ENGAGEMENT FRAMEWORK:

# Hook with authenticity - React genuinely, not performatively
# Add micro-value - One small insight, connection, or "aha" moment
# Keep it conversational - Like you're continuing a chat, not starting a presentation
# Timing matters - Reply like you saw this while scrolling, not like you're crafting content

# REPLY STYLES (mix these up):

# The "same here": Personal experience that relates
# The "actually...": Gentle correction or addition with new info
# The "wait, but...": Pointing out an interesting contradiction or edge case
# The "reminds me of": Drawing unexpected but relevant connections
# The "lol yeah": Simple agreement with a twist or observation

# STRICT RULES:

# Max 280 characters (check your count!)
# NO hashtags, NO calls-to-action, NO obvious self-promotion
# NO starting with "Great point!" or similar corporate speak
# NO emoji overload (1-2 max, often none)
# NO questions unless they feel natural in conversation
# Avoid being the "well actually" person unless it's genuinely helpful

# TONE CALIBRATION:

# Too polished: "This is an excellent observation about market dynamics!"
# Just right: "yeah this is why I stopped checking analytics daily, was driving me nuts"
# Too casual: "lmaooo fr tho 💯💯💯"

# CONTEXT AWARENESS:

# If it's a complaint/vent: Empathize briefly, maybe share similar experience
# If it's a win/achievement: Quick congrats, maybe relate to your own journey
# If it's a hot take: Either build on it or offer a different angle (respectfully)
# If it's asking for help: Give actual actionable advice, not generic encouragement

# QUALITY CHECK:
# Before submitting, ask: "Would I actually send this reply if I saw this tweet while scrolling at 11pm?" If no, revise.
# Generate a short, natural, and engaging reply that sounds like it came from a real person who just happened to have something interesting to add.        
# """
#         response = model.generate_content(prompt)
#         comment = response.text.strip()
#         if len(comment) > 280:
#             comment = comment[:277] + "..."
#         return comment
#     except Exception as e:
#         print(f"❌ Error generating comment: {e}")
#         return f"Interesting take on {keyword}! Thanks for sharing @{username}"

# def search_and_reply(keywords: List[str], max_replies: int = 3):
#     """Search for tweets with keywords and reply to up to max_replies"""
#     results = []
#     replies_count = 0
    
#     # Use only the first keyword to avoid rate limits
#     if keywords:
#         keyword = keywords[0]  # Take only the first keyword
#         print(f"🔍 Searching for: '{keyword}' (using first keyword only)")
        
#         try:
#             response = client.search_recent_tweets(
#                 query=keyword,
#                 max_results=10,  # Search for more tweets to find 3 good ones
#                 expansions=["author_id"],
#                 tweet_fields=["created_at", "text"],
#                 user_fields=["username"]
#             )

#             if not response.data:
#                 print(f"⚠️ No tweets found for '{keyword}'")
#                 return results

#             users = {u["id"]: u for u in response.includes["users"]}

#             for tweet in response.data:
#                 if replies_count >= max_replies:
#                     break
#                 tweet_id = tweet.id
#                 if already_replied(tweet_id):
#                     print(f"⏭️ Already replied to tweet: {tweet_id}")
#                     continue

#                 author_id = tweet.author_id
#                 username = users.get(author_id, {}).get("username", "unknown")
#                 tweet_text = tweet.text

#                 try:
#                     generated_comment = generate_comment(tweet_text, username, keyword)
#                     print(f"🤖 Generated comment: {generated_comment}")
#                     client.create_tweet(in_reply_to_tweet_id=tweet_id, text=generated_comment)

#                     log_entry = {
#                         "type": "reply",
#                         "id": tweet_id,
#                         "author_id": author_id,
#                         "author_username": username,
#                         "original_tweet_text": tweet_text,
#                         "generated_comment": generated_comment,
#                         "keyword": keyword,
#                         "url": f"https://twitter.com/{username}/status/{tweet_id}",
#                         "timestamp": datetime.utcnow().isoformat() + "Z"
#                     }
#                     save_reply_log(log_entry)
#                     results.append(log_entry)
#                     print(f"✅ Replied to tweet: {tweet_id}")
#                     replies_count += 1
#                     time.sleep(30)

#                 except tweepy.TooManyRequests as e:
#                     handle_rate_limit(e.response.headers)
#                     # Continue with the next tweet instead of returning
#                     continue

#         except tweepy.TooManyRequests as e:
#             handle_rate_limit(e.response.headers)
#             # Try again with the same keyword instead of returning
#             return search_and_reply(keywords, max_replies)
#         except Exception as e:
#             print(f"❌ Error for keyword '{keyword}': {e}")

#     return results

# # ===== POST CONTENT BOT FUNCTIONS =====

# def generate_tweet_content(topic: str) -> str:
#     """Generate original tweet content"""
#     try:
#         prompt = f"""
# You are a friendly, witty, and authentic Twitter user who creates content like a blend of @levelsio (Pieter Levels) and @TheBoringMarketer. You craft original tweets that feel genuine, valuable, and scroll-stopping without trying too hard.

# INPUT:

# Keyword: {topic}
# VOICE & PERSONALITY:

# @levelsio style: Direct, slightly nerdy, drops casual insights, uses emojis sparingly but effectively, sometimes brutally honest, shares personal experiences and metrics
# @TheBoringMarketer style: Observant, dry humor, calls out obvious things everyone thinks but doesn't say, marketing-aware but not salesy, cuts through BS
# Overall vibe: That friend who always has interesting takes, shares real experiences, and isn't trying too hard to impress
# MAGNETIC TWEET FRAMEWORK:

# 1. HOOK PATTERNS (choose one that fits the keyword):

# Shock Reality: "95% of founders do this backwards..."
# Contrarian Take: "Everyone says X, but I've seen Y work better..."
# Fortune Teller: "In 12 months, this will be irrelevant..."
# Personal Confession: "Made this $10k mistake so you don't have to..."
# Pattern Recognition: "Same thing that killed Blockbuster is happening to..."
# Insider Secret: "Industry won't tell you this but..."
# 2. POWER LANGUAGE:

# Use action-packed openers: "Tested", "Discovered", "Built", "Learned", "Noticed"
# Replace weak words: "think" → "realized", "good" → "game-changing", "try" → "tested"
# Include specific numbers when possible: "$47k", "3.2x", "73%", "Day 47"
# 3. MICRO SOCIAL PROOF (when natural):

# Personal credibility: "after building 3 companies", "learned from 500+ customer calls"
# Metrics that matter: "$0 to $50k MRR", "10 failed projects before this one"
# Industry experience: "spent 5 years in VC", "hired 100+ people"
# 4. NARRATIVE STRUCTURES:

# Thread Starter (if multi-tweet):

# Problem → Solution Arc: Pain point → surprising solution → result
# Timeline Story: "6 months ago I was X... today I'm Y... here's what changed"
# Mistake → Learning: "Biggest mistake: X... What I learned: Y... New approach: Z"
# Single Tweet:

# Observation → Insight: "Noticed X... realized Y"
# Contrarian → Evidence: "Everyone does X... but data shows Y"
# Personal → Universal: "My experience: X... applies everywhere because Y"
# 5. CONTENT PILLARS (mix these based on keyword):

# Behind-the-scenes: Real numbers, failures, lessons learned
# Contrarian takes: Challenge common wisdom with experience
# Pattern spotting: Connect dots others miss
# Tool/resource shares: What actually works (with context)
# Industry observations: Call out obvious things people don't say
# Personal experiments: "Tested this for 30 days, here's what happened"
# STRICT CONTENT RULES:

# Max 300 characters for single tweets 
# For threads: Each tweet must be valuable standalone
# NO obvious self-promotion or sales pitches
# NO corporate speak or buzzwords
# NO emoji overload (1-2 max, strategic placement)
# NO generic motivational quotes
# Start with impact, not setup ("Here's what I learned about X")
# TONE CALIBRATION:

# Too corporate: "Implementing strategic initiatives to optimize our customer acquisition funnel"
# Just right: "spent $3k on ads, got 2 customers. switched to cold email, got 47. sometimes simple wins"
# Too casual: "omggg this hack is absolutely insane you guys 🔥🔥🔥"
# CONTENT QUALITY MATRIX:

# High Value Posts:

# Share specific numbers/results
# Challenge conventional wisdom with experience
# Reveal non-obvious insights
# Tell relatable failure stories with lessons
# Avoid:

# Generic advice everyone gives
# Humble brags disguised as lessons
# Obvious observations without insight
# Content that sounds like a LinkedIn post
# FINAL QUALITY CHECKS:

# Scroll Test: Would this make someone stop scrolling?
# Value Test: What specific thing does someone learn/gain?
# Authenticity Test: Does this sound like something I'd actually say?
# Engagement Test: Would I want to reply to this?
# Uniqueness Test: Have I seen this exact take 100 times before?
# OUTPUT REQUIREMENTS: Generate an original tweet that:

# Hooks attention in the first 7 words
# Delivers genuine value or insight
# Feels conversational and authentic
# Could spark meaningful replies
# Relates directly to the keyword/topic
# Sounds like it came from real experience
# Remember: The best tweets feel like overheard conversations from someone who actually knows what they're talking about.

# DO not use * in the tweet content.
# """
#         response = model.generate_content(prompt)
#         tweet_content = response.text.strip()
#         if len(tweet_content) > 280:
#             tweet_content = tweet_content[:277] + "..."
#         return tweet_content
#     except Exception as e:
#         print(f"❌ Error generating tweet content: {e}")
#         return f"been diving deep into {topic} lately... the rabbit hole goes deeper than most people realize"

# def post_tweet(topic: str):
#     """Post a single tweet about the given topic"""
#     results = []
    
#     try:
#         tweet_content = generate_tweet_content(topic)
#         print(f"🤖 Generated tweet: {tweet_content}")
#         response = client.create_tweet(text=tweet_content)
        
#         if response.data:
#             tweet_id = response.data["id"]
#             log_entry = {
#                 "type": "post",
#                 "id": tweet_id,
#                 "content": tweet_content,
#                 "topic": topic,
#                 "url": f"https://twitter.com/user/status/{tweet_id}",
#                 "timestamp": datetime.utcnow().isoformat() + "Z"
#             }
#             save_post_log(log_entry)
#             results.append(log_entry)
#             print(f"✅ Posted tweet: {tweet_id}")
            
#         return results
        
#     except tweepy.TooManyRequests as e:
#         handle_rate_limit(e.response.headers)
#         return results
#     except Exception as e:
#         print(f"❌ Error posting tweet: {e}")
#         return results

# def post_multiple_tweets(topics: List[str], max_posts: int = 3):
#     """Post up to max_posts tweets with delays"""
#     results = []
#     posts_count = 0
    
#     for topic in topics:
#         if posts_count >= max_posts:
#             break
#         print(f"📝 Posting about: '{topic}'")
#         results.extend(post_tweet(topic))
#         posts_count += 1
#         time.sleep(300)
    
#     return results

# # ===== SCHEDULING FUNCTIONS =====

# def schedule_tasks(keywords: List[str], topics: List[str], times: List[str]):
#     """Schedule reply and post tasks for user-provided times"""
#     global scheduled_keywords, scheduled_topics, scheduled_times, task_counter, scheduler_running, scheduler_thread
    
#     # Clear any existing schedules
#     schedule.clear()
    
#     # Clear logs when scheduling
#     clear_logs()
    
#     # Store keywords, topics, and times globally
#     scheduled_keywords = keywords
#     scheduled_topics = topics
#     scheduled_times = times
#     task_counter = 0  # Reset task counter for new schedule
    
#     # Validate times
#     try:
#         for t in times:
#             datetime.strptime(t, "%H:%M")
#     except ValueError:
#         raise HTTPException(status_code=400, detail="Times must be in HH:MM format (24-hour clock).")
    
#     # Schedule tasks (alternating reply and post)
#     for i, t in enumerate(times):
#         if i % 2 == 0:
#             schedule.every().day.at(t).do(scheduled_reply_task)
#         else:
#             schedule.every().day.at(t).do(scheduled_post_task)
    
#     print(f"✅ Scheduled tasks for keywords: {keywords}")
#     print(f"✅ Scheduled tasks for topics: {topics}")
#     print(f"✅ Scheduled tasks at times: {times}")
#     print("🧹 Log files cleared for fresh start")
    
#     # Start scheduler if not already running
#     if not scheduler_running:
#         scheduler_running = True
#         scheduler_thread = threading.Thread(target=run_scheduler)
#         scheduler_thread.daemon = True  # Make it a daemon thread
#         scheduler_thread.start()
#         print("🚀 Scheduler started successfully")

# def scheduled_reply_task():
#     """Scheduled task for replying to tweets"""
#     global scheduled_keywords, reply_index, task_counter
#     print(f"⏰ Executing scheduled reply task at {datetime.now().strftime('%H:%M')}")
    
#     # Cycle through keywords
#     if scheduled_keywords:
#         current_keyword = scheduled_keywords[reply_index % len(scheduled_keywords)]
#         print(f"🔍 Using keyword: '{current_keyword}' (index {reply_index})")
#         search_and_reply([current_keyword], max_replies=3)
#         reply_index += 1
#         task_counter += 1
        
#         # Check if all tasks completed
#         if task_counter >= total_daily_tasks:
#             print("🎉 All daily tasks completed! Stopping bot automatically...")
#             schedule.clear()
#             print("✅ Bot stopped automatically after completing all scheduled tasks")
#             print("🔄 Ready for new schedule tomorrow")

# def scheduled_post_task():
#     """Scheduled task for posting tweets"""
#     global scheduled_topics, post_index, task_counter
#     print(f"⏰ Executing scheduled post task at {datetime.now().strftime('%H:%M')}")
    
#     # Cycle through topics
#     if scheduled_topics:
#         current_topic = scheduled_topics[post_index % len(scheduled_topics)]
#         print(f"📝 Using topic: '{current_topic}' (index {post_index})")
#         post_multiple_tweets([current_topic], max_posts=1)  # Post 1 tweet per topic
#         post_index += 1
#         task_counter += 1
        
#         # Check if all tasks completed
#         if task_counter >= total_daily_tasks:
#             print("🎉 All daily tasks completed! Stopping bot automatically...")
#             schedule.clear()
#             print("✅ Bot stopped automatically after completing all scheduled tasks")
#             print("🔄 Ready for new schedule tomorrow")

# def clear_logs():
#     """Clear log files daily"""
#     global replied_log, posted_log
    
#     try:
#         # Clear the log lists
#         replied_log.clear()
#         posted_log.clear()
        
#         # Clear the JSON files
#         with open(REPLY_LOG_FILE, "w") as f:
#             json.dump([], f)
#         with open(POST_LOG_FILE, "w") as f:
#             json.dump([], f)
        
#         print("🧹 Daily log files cleared successfully")
#     except Exception as e:
#         print(f"❌ Error clearing logs: {e}")

# def run_scheduler():
#     """Run the scheduler"""
#     global scheduler_running
#     while scheduler_running:
#         try:
#             schedule.run_pending()
#             time.sleep(60)
#         except Exception as e:
#             print(f"❌ Scheduler error: {e}")
#             time.sleep(60)
#     print("⏹️ Scheduler stopped")

# # ===== PYDANTIC MODELS =====

# class BotRequest(BaseModel):
#     keywords: List[str]
#     topics: List[str]
#     times: List[str]  # New field for user-specified times in HH:MM format

# # ===== API ENDPOINTS =====

# @app.get("/")
# def root():
#     """Root endpoint"""
#     return {
#         "message": "Twitter Bot is live!",
#         "endpoints": {
#             "schedule": "POST /schedule - Schedule reply and post tasks with custom times",
#             "logs": "GET /logs - Get reply and post logs",
#             "clear_logs": "POST /clear_logs - Clear all logs",
#             "stop": "POST /stop - Stop the bot and clear scheduled tasks"
#         },
#         "status": "Ready to schedule tasks"
#     }

# @app.post("/schedule")
# def schedule_bot(request: BotRequest):
#     """Schedule bot tasks with given keywords, topics, and times"""
#     if not request.keywords or not request.topics or not request.times:
#         raise HTTPException(status_code=400, detail="Keywords, topics, and times are required.")
    
#     if len(request.times) < total_daily_tasks:
#         raise HTTPException(status_code=400, detail=f"At least {total_daily_tasks} times are required for {total_daily_tasks} tasks (3 replies + 3 posts).")
    
#     schedule_tasks(request.keywords, request.topics, request.times)
#     return {
#         "message": f"✅ Bot scheduled to reply to 3 tweets and post 3 tweets at specified times: {request.times}",
#         "keywords": request.keywords,
#         "topics": request.topics,
#         "times": request.times
#     }

# @app.get("/logs")
# def get_logs():
#     """Get reply and post logs"""
#     return {
#         "reply_log": replied_log,
#         "post_log": posted_log,
#         "task_counter": task_counter,
#         "total_tasks": total_daily_tasks,
#         "is_completed": task_counter >= total_daily_tasks
#     }

# @app.post("/clear_logs")
# def clear_logs_endpoint():
#     """Clear all logs"""
#     try:
#         clear_logs()
#         return {"message": "Logs cleared successfully"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error clearing logs: {str(e)}")

# @app.post("/stop")
# def stop_bot():
#     """Stop the bot and clear all scheduled tasks"""
#     try:
#         global scheduler_running, task_counter
#         # Stop the scheduler
#         scheduler_running = False
#         # Clear all scheduled tasks
#         schedule.clear()
#         # Reset task counter
#         task_counter = 0
#         return {"message": "Bot stopped successfully"}
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Error stopping bot: {str(e)}")


