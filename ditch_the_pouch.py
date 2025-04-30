from flask import Flask, request
import requests
import json
import datetime
import os
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

# Load sensitive info from environment variables
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = "627034663828010"
RECIPIENT_PHONE = "447946560381"  # e.g., "447911123456"

# Simple in-memory store
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

def send_button_message():
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_PHONE,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": "Please press a button when you take a snus or need help."
            },
            "action": {
                "buttons": [
                    {
                        "type": "reply",
                        "reply": {
                            "id": "snus_taken",
                            "title": "I took a snus"
                        }
                    },
                    {
                        "type": "reply",
                        "reply": {
                            "id": "snus_failed",
                            "title": "I failed"
                        }
                    }
                ]
            }
        }
    }
    response = requests.post(url, headers=headers, json=data)
    print("Sent interactive message:", response.status_code)

@app.route('/webhook', methods=['GET'])
def verify():
    VERIFY_TOKEN = "snusquit123"
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        # Send button message as part of verification
        send_button_message()
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("Incoming:", json.dumps(data, indent=2))

    try:
        changes = data["entry"][0]["changes"][0]["value"]

        if "messages" in changes:
            message = changes["messages"][0]

            # Handle button replies
            if message.get("type") == "button":
                button_id = message["button"]["payload"]

                if button_id == "snus_taken":
                    user_data["current_day_snus"] += 1
                    send_whatsapp_message(f"You logged a snus. You've taken {user_data['current_day_snus']} today.")
                elif button_id == "snus_failed":
                    user_data["failed"] = True
                    send_whatsapp_message("You pressed 'I failed'. No worries — try again tomorrow!")

            # Handle plain text messages
            elif message.get("type") == "text":
                text = message["text"]["body"]
                try:
                    mg = int(text.strip())
                    user_data["current_day_snus"] += 1
                    user_data["snus_mg"].append(mg)
                    user_data["current_mg"] = mg
                    send_whatsapp_message(f"Logged {mg}mg. You've taken {user_data['current_day_snus']} snus today.")
                except ValueError:
                    send_whatsapp_message("Please reply with a number like '50', or use the button.")
        else:
            print("Received non-message event (status update, etc.)")

    except Exception as e:
        print("Error handling webhook:", e)

    return "ok", 200

def midnight_reset():
    user_data["yesterday_total"] = user_data["current_day_snus"]
    if user_data["yesterday_total"] is not None:
        user_data["limit"] = max(user_data["yesterday_total"] - 1, user_data["min_limit"])

    user_data["current_day_snus"] = 0
    user_data["snus_mg"] = []
    user_data["failed"] = False

    if user_data["current_mg"] is not None and user_data["current_mg"] <= user_data["target_mg"]:
        send_whatsapp_message("You’ve worked down to 3mg snus or below. You’re nearly done! Keep it up 💪")
    elif user_data["limit"] == user_data["min_limit"]:
        send_whatsapp_message(
            f"You have worked down to 3 snus per day, great job! "
            f"You have unlocked: weaker snus ({user_data['current_mg'] - 5}mg)."
        )
    else:
        send_whatsapp_message(
            f"Your limit for today is: {user_data['limit']}. "
            f"Please press the button when you have taken a snus or need help."
        )
        send_button_message()

# Midnight reset
scheduler = BackgroundScheduler()
scheduler.add_job(midnight_reset, 'cron', hour=0, minute=0)
scheduler.start()

# Run app
if __name__ == '__main__':
    send_button_message()  # For initial test — remove this later if needed
    app.run(host="0.0.0.0", port=10000)
