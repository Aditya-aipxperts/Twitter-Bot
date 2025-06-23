import os
import time
import tweepy
import json
from datetime import datetime
from dotenv import load_dotenv


load_dotenv()
client = tweepy.Client(
    bearer_token=os.getenv("TWITTER_BEARER_TOKEN"),
    consumer_key=os.getenv("TWITTER_API_KEY"),
    consumer_secret=os.getenv("TWITTER_API_SECRET_KEY"),
    access_token=os.getenv("TWITTER_ACCESS_TOKEN"),
    access_token_secret=os.getenv("TWITTER_ACCESS_SECRET")
)

# Keywords to search
KEYWORDS = ["ai agent", "automate with ai", "autonomous agent"]
LOG_FILE = "twitter_log.json"

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

def format_time(seconds_left):
    mins, secs = divmod(int(seconds_left), 60)
    return f"{mins}:{secs:02d}"

def handle_rate_limit(response_headers):
    if "x-rate-limit-reset" in response_headers:
        reset_time = int(response_headers["x-rate-limit-reset"])
        while True:
            now = int(time.time())
            wait_time = reset_time - now
            if wait_time <= 0:
                print("✅ Rate limit window passed. Resuming...")
                break
            mins, secs = divmod(wait_time, 60)
            print(f"\r⏳ Rate limit hit. Time left: {mins:02d}:{secs:02d}", end="")
            time.sleep(1)
        print()

def search_and_reply():
    for keyword in KEYWORDS:
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
                    response_text = f"Hey! 👋 If you're exploring {keyword}, check this out 👉 [insert your link or CTA here]"
                    client.create_tweet(in_reply_to_tweet_id=tweet_id, text=response_text)

                    print(f"✅ Replied to tweet: {tweet_id}")
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
                    time.sleep(10)

                except tweepy.TooManyRequests as e:
                    handle_rate_limit(e.response.headers)
                    return

        except tweepy.TooManyRequests as e:
            handle_rate_limit(e.response.headers)
            return
        except Exception as e:
            print(f"❌ Search failed for keyword '{keyword}': {e}")

        time.sleep(60)

def main():
    while True:
        search_and_reply()
        print("🔁 Sleeping 15 minutes before next round...")
        time.sleep(15 * 60)

if __name__ == "__main__":
    main()


# For Posting Tweets
# tweeted = client.create_tweet(text=" YO00")
# print(tweeted)

# FOR LIKING 
# client.like(tweet_id=1935947530438598922)

# FOR DELETING TWEETS
# client.delete_tweet(id=1935946376426205607)
# print("Tweet Deleted")

# FOR SEARCHING KEYWORDS
# query = "AI Agents"
# response = client.search_recent_tweets(query=query,max_results=10)

# if response.data:
#     for tweet in response.data:
#             print(f"Tweet ID: {tweet.id} | Text: {tweet.text}")
# else:
#       print("No Matching tweets found.")