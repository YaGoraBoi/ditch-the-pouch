from flask import Flask, request
import requests
import json
import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import os

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = "627034663828010"
RECIPIENT_PHONE = "447946560381"

app = Flask(__name__)

# In-memory data store (use JSON or SQLite for persistence)
user_data = {
    "current_day_snus": 0,
    "yesterday_total": None,
    "limit": None,
    "snus_mg": [],
    "min_limit": 3,
    "target_mg": 3,
    "current_mg": None,
    "failed": False
}

def send_whatsapp_message(message):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_PHONE,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(url, headers=headers, json=data)
    print("Sent:", message)
    return response.json()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("Incoming:", json.dumps(data, indent=2))

    # Check if there's a message from the user
    if 'messages' in data['entry'][0]['changes'][0]['value']:
        message = data['entry'][0]['changes'][0]['value']['messages'][0]
        text = message.get('text', {}).get('body', '')
        
        if text.lower() == "i failed":
            user_data['failed'] = True
            send_whatsapp_message("Don't worry, setbacks happen. Tomorrow is a new day!")
            return "ok", 200

        try:
            mg = int(text.strip())
            user_data["current_day_snus"] += 1
            user_data["snus_mg"].append(mg)
            user_data["current_mg"] = mg
            send_whatsapp_message(f"Logged {mg}mg. You've taken {user_data['current_day_snus']} snus today.")
        except ValueError:
            send_whatsapp_message("Please reply with just the number of mg, e.g. '50', or say 'I failed'.")

    return "ok", 200

def midnight_reset():
    # Save yesterday's total
    user_data["yesterday_total"] = user_data["current_day_snus"]

    if user_data["yesterday_total"] is not None:
        user_data["limit"] = max(user_data["yesterday_total"] - 1, user_data["min_limit"])

    # Reset daily values
    user_data["current_day_snus"] = 0
    user_data["snus_mg"] = []
    user_data["failed"] = False

    # Check if reached target mg
    if user_data["current_mg"] is not None and user_data["current_mg"] <= user_data["target_mg"]:
        send_whatsapp_message("You’ve worked down to 3mg snus or below. You’re nearly done! Keep it up 💪")
    elif user_data["limit"] == user_data["min_limit"]:
        send_whatsapp_message(
            f"You have worked down to 3 snus per day, great job! "
            f"You have unlocked: weaker snus ({user_data['current_mg'] - 5}mg). "
            f"Please press the button when you have taken a snus."
        )
    else:
        send_whatsapp_message(
            f"Your limit for today is: {user_data['limit']}. "
            f"Please press the button when you have taken a snus and reply with its mg."
        )

# Schedule daily reset at midnight
scheduler = BackgroundScheduler()
scheduler.add_job(midnight_reset, 'cron', hour=0, minute=0)
scheduler.start()

# Meta Webhook Verification
@app.route('/webhook', methods=['GET'])
def verify():
    VERIFY_TOKEN = "snusquit123"
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403

if __name__ == '__main__':
    app.run(port=5000)
