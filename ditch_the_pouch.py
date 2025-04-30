from flask import Flask, request
import requests
import json
import os
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = "627034663828010"
RECIPIENT_PHONE = "447946560381"

user_data = {
    "current_day_snus": 0,
    "yesterday_total": None,
    "limit": None,
    "snus_mg": [],
    "min_limit": 3,
    "target_mg": 3,
    "current_mg": None,
    "initial_mg": None,
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

def send_mg_list():
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
            "type": "list",
            "body": {
                "text": "Welcome! Please select the strength (mg) of your current snus:"
            },
            "action": {
                "button": "Choose mg",
                "sections": [
                    {
                        "title": "Snus Strength",
                        "rows": [
                            {"id": "mg_50", "title": "50mg"},
                            {"id": "mg_40", "title": "40mg"},
                            {"id": "mg_30", "title": "30mg"},
                            {"id": "mg_20", "title": "20mg"},
                            {"id": "mg_10", "title": "10mg"},
                            {"id": "mg_5",  "title": "5mg"},
                            {"id": "mg_3",  "title": "3mg"}
                        ]
                    }
                ]
            }
        }
    }

    response = requests.post(url, headers=headers, json=data)
    print("Sent mg list:", response.status_code)

@app.route('/webhook', methods=['GET'])
def verify():
    VERIFY_TOKEN = "snusquit123"
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        if user_data["current_mg"] is None:
            send_mg_list()
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

            # Reset trigger
            if message.get("type") == "text":
                text = message["text"]["body"].strip().lower()
                if text == "reset me":
                    user_data.update({
                        "current_day_snus": 0,
                        "yesterday_total": None,
                        "limit": None,
                        "snus_mg": [],
                        "current_mg": None,
                        "initial_mg": None,
                        "failed": False
                    })
                    send_whatsapp_message("User data reset. Re-sending mg selector.")
                    send_mg_list()
                    return "ok", 200

            # Handle mg list reply
            if message.get("type") == "interactive" and message.get("interactive", {}).get("type") == "list_reply":
                selection = message["interactive"]["list_reply"]["id"]
                mg = int(selection.replace("mg_", ""))
                user_data["current_mg"] = mg
                user_data["initial_mg"] = mg
                send_whatsapp_message(
                    f"Got it! Your starting snus strength is {mg}mg. "
                    f"Please press the button when you take a snus."
                )
                send_button_message()
                return "ok", 200

            # Handle buttons
            if message.get("type") == "interactive" and message.get("interactive", {}).get("type") == "button_reply":
                button_id = message["interactive"]["button_reply"]["id"]

                if button_id == "snus_taken":
                    user_data["current_day_snus"] += 1
                    send_whatsapp_message(
                        f"You logged a snus at {user_data['current_mg']}mg. "
                        f"You've taken {user_data['current_day_snus']} today."
                    )
                elif button_id == "snus_failed":
                    user_data["failed"] = True
                    send_whatsapp_message("You pressed 'I failed'. No worries — try again tomorrow!")

    except Exception as e:
        print("Error handling webhook:", e)

    return "ok", 200

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
    print("Sent interactive button:", response.status_code)

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

scheduler = BackgroundScheduler()
scheduler.add_job(midnight_reset, 'cron', hour=0, minute=0)
scheduler.start()

# (No __main__ block since we're using gunicorn on Render)
