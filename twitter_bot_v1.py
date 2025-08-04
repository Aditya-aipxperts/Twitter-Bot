import os
import time
import json
from datetime import datetime
from typing import List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
import tweepy

# Load environment variables
load_dotenv()

client = tweepy.Client(
    bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
    consumer_key=os.getenv("TWITTER_API_KEY"),
    consumer_secret=os.getenv("TWITTER_API_SECRET_KEY"),
    access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
    access_token_secret=os.getenv("TWITTER_ACCESS_SECRET")
)

LOG_FILE = "twitter_log.json"

# Initialize FastAPI app
app = FastAPI()

# Load or initialize log
if os.path.exists(LOG_FILE):
    with open(LOG_FILE, "r") as f:
        replied_log = json.load(f)
else:
    replied_log = []

def save_log(entry):
    replied_log.append(entry)
    with open(LOG_FILE, "w") as f:
        json.dump(replied_log, f, indent=2)

def already_replied(tweet_id):
    return any(entry["id"] == tweet_id for entry in replied_log)

def handle_rate_limit(response_headers):
    if "x-rate-limit-reset" in response_headers:
        reset_time = int(response_headers["x-rate-limit-reset"])
        now = int(time.time())
        wait_time = reset_time - now
        print(f"⏳ Rate limit hit. Wait for {wait_time} seconds.")
        time.sleep(max(wait_time, 0))
        print("✅ Rate limit window passed. Resuming...")

def search_and_reply(keywords: List[str], reply_text: str):
    results = []
    for keyword in keywords:
        print(f"🔍 Searching for: '{keyword}'")
        try:
            response = client.search_recent_tweets(
                query=keyword,
                max_results=10,
                expansions=["author_id"],
                tweet_fields=["created_at"],
                user_fields=["username"]
            )

            if not response.data:
                print(f"⚠️ No tweets found for '{keyword}'")
                continue

            users = {u["id"]: u for u in response.includes["users"]}

            for tweet in response.data:
                tweet_id = tweet.id
                if already_replied(tweet_id):
                    continue

                author_id = tweet.author_id
                username = users.get(author_id, {}).get("username", "unknown")

                try:
                    full_response = reply_text.replace("{keyword}", keyword).replace("{username}", username)
                    client.create_tweet(in_reply_to_tweet_id=tweet_id, text=full_response)

                    log_entry = {
                        "type": "tweet",
                        "id": tweet_id,
                        "author_id": author_id,
                        "author_username": username,
                        "text": tweet.text,
                        "keyword": keyword,
                        "url": f"https://twitter.com/{username}/status/{tweet_id}",
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    }
                    save_log(log_entry)
                    results.append(log_entry)
                    print(f"✅ Replied to tweet: {tweet_id}")
                    time.sleep(10)

                except tweepy.TooManyRequests as e:
                    handle_rate_limit(e.response.headers)
                    return results

        except tweepy.TooManyRequests as e:
            handle_rate_limit(e.response.headers)
            return results
        except Exception as e:
            print(f"❌ Error for keyword '{keyword}': {e}")

        time.sleep(5)

    return results

# Input schema
class BotRequest(BaseModel):
    keywords: List[str]
    response_text: str  # you can include {keyword} and {username} as placeholders

@app.get("/")
def root():
    return {"message": "Twitter Bot is live. Use POST /run with keywords and response_text."}

@app.post("/run")
def run_bot(request: BotRequest):
    if not request.keywords or not request.response_text:
        raise HTTPException(status_code=400, detail="Both keywords and response_text are required.")
    
    results = search_and_reply(request.keywords, request.response_text)
    return {
        "message": f"✅ Completed. {len(results)} tweets replied.",
        "log": results
    }
