from flask import Flask, request
import requests
import json
import os
from apscheduler.schedulers.background import BackgroundScheduler
from tinydb import TinyDB, Query
from tinydb.storages import MemoryStorage

app = Flask(__name__)

ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
PHONE_NUMBER_ID = "627034663828010"
RECIPIENT_PHONE = "447946560381"

db = TinyDB(storage=MemoryStorage)
user_table = db.table("users")
User = Query()

# Initial default data
default_data = {
    "current_day_snus": 0,
    "yesterday_total": None,
    "limit": None,
    "snus_mg": [],
    "min_limit": 3,
    "target_mg": 3,
    "current_mg": None,
    "initial_mg": None,
    "failed": False,
    "zero_snus_days": 0,
    "graduated": False
}

def get_user_data():
    result = user_table.get(User.phone == RECIPIENT_PHONE)
    return result["data"] if result else default_data.copy()

def save_user_data(data):
    user_table.upsert({"phone": RECIPIENT_PHONE, "data": data}, User.phone == RECIPIENT_PHONE)
    print("User data saved.")

user_data = get_user_data()

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
    requests.post(url, headers=headers, json=data)
    print("Sent:", message)

def send_mg_list(unlock=False):
    mg_options = []
    if unlock:
        for mg in [50, 40, 30, 25, 20, 15, 10, 5, 3]:
            if mg < user_data["current_mg"]:
                mg_options.append({"id": f"mg_{mg}", "title": f"{mg}mg"})
    else:
        mg_options = [{"id": f"mg_{mg}", "title": f"{mg}mg"} for mg in [50, 40, 30, 25, 20, 10, 5, 3]]

    data = {
        "messaging_product": "whatsapp",
        "to": RECIPIENT_PHONE,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {
                "text": "Select your starting snus strength:" if not unlock else "You’ve unlocked weaker snus options!"
            },
            "action": {
                "button": "Choose mg",
                "sections": [{
                    "title": "Snus Strength",
                    "rows": mg_options
                }]
            }
        }
    }
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    requests.post(f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages", headers=headers, json=data)

def send_button_message():
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
                    {"type": "reply", "reply": {"id": "snus_taken", "title": "I took a snus"}},
                    {"type": "reply", "reply": {"id": "snus_failed", "title": "I failed"}}
                ]
            }
        }
    }
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }
    requests.post(f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages", headers=headers, json=data)

@app.route('/webhook', methods=['GET'])
def verify():
    VERIFY_TOKEN = "snusquit123"
    if request.args.get("hub.mode") == "subscribe" and request.args.get("hub.verify_token") == VERIFY_TOKEN:
        if get_user_data()["current_mg"] is None:
            send_mg_list()
        return request.args.get("hub.challenge"), 200
    return "Verification failed", 403

@app.route('/webhook', methods=['POST'])
def webhook():
    global user_data
    data = request.get_json()
    print("Incoming:", json.dumps(data, indent=2))

    try:
        changes = data["entry"][0]["changes"][0]["value"]
        if "messages" in changes:
            message = changes["messages"][0]
            user_data = get_user_data()

            if message.get("type") == "text":
                text = message["text"]["body"].strip().lower()

                # 🧼 Full reset
                if text == "reset me":
                    user_data = default_data.copy()
                    send_whatsapp_message("User data reset. Re-sending mg selector.")
                    send_mg_list()
                    save_user_data(user_data)
                    return "ok", 200

                # 🕛 Simulate midnight
                if text == "midnight":
                    send_whatsapp_message("⏳ Simulating midnight reset...")
                    midnight_reset()
                    return "ok", 200

                # 🔻 Force 3 snus limit
                if text == "three snus":
                    user_data["limit"] = 3
                    send_whatsapp_message("🔻 Daily limit set to 3 snus.")
                    save_user_data(user_data)
                    return "ok", 200

                # 🧪 Trigger weaker unlock manually
                if text == "weaker unlock":
                    if user_data["current_mg"] and user_data["current_mg"] > 3:
                        send_whatsapp_message("🔓 Triggering weaker snus list manually...")
                        send_mg_list(unlock=True)
                    else:
                        send_whatsapp_message("❌ Already on 3mg or no mg set.")
                    return "ok", 200

                # 🎓 Force graduation state
                if text == "graduate me":
                    user_data["current_mg"] = 3
                    user_data["current_day_snus"] = 0
                    user_data["zero_snus_days"] = 3
                    midnight_reset()
                    return "ok", 200

                # 🧾 Print current state
                if text == "status":
                    msg = (
                        f"📊 Current Status:\n"
                        f"- MG: {user_data['current_mg']}mg\n"
                        f"- Snus today: {user_data['current_day_snus']}\n"
                        f"- Limit: {user_data['limit']}\n"
                        f"- Failed today: {user_data['failed']}\n"
                        f"- Zero-snuse days: {user_data['zero_snus_days']}\n"
                        f"- Graduated: {'✅' if user_data.get('graduated') else '❌'}"
                    )
                    send_whatsapp_message(msg)
                    return "ok", 200

            # MG selection
            if message.get("type") == "interactive" and message["interactive"]["type"] == "list_reply":
                mg = int(message["interactive"]["list_reply"]["id"].replace("mg_", ""))
                user_data["current_mg"] = mg
                user_data["initial_mg"] = mg
                send_whatsapp_message(
                    f"Got it! Your starting snus strength is {mg}mg.\nPress a button to log usage."
                )
                send_button_message()
                save_user_data(user_data)
                return "ok", 200

            # Button presses
            if message.get("type") == "interactive" and message["interactive"]["type"] == "button_reply":
                button_id = message["interactive"]["button_reply"]["id"]

                if button_id == "snus_taken":
                    user_data["current_day_snus"] += 1
                    send_whatsapp_message(
                        f"Logged snus at {user_data['current_mg']}mg. "
                        f"You’ve taken {user_data['current_day_snus']} today."
                    )
                    send_button_message()

                elif button_id == "snus_failed":
                    user_data["failed"] = True
                    send_whatsapp_message("You pressed 'I failed'. Try again tomorrow!")
                    send_button_message()

                save_user_data(user_data)

    except Exception as e:
        print("Webhook error:", e)

    return "ok", 200

def midnight_reset():
    global user_data
    user_data = get_user_data()

    # Daily summary
    if user_data["yesterday_total"] is not None and not user_data.get("graduated", False):
        send_whatsapp_message(
            f"📊 Yesterday: {user_data['yesterday_total']} snus at {user_data['current_mg']}mg.\n"
            f"Today’s limit: {max(user_data['yesterday_total'] - 1, user_data['min_limit'])}."
        )

    # Graduation condition
    if user_data["current_mg"] == 3 and user_data["current_day_snus"] == 0:
        user_data["zero_snus_days"] += 1
        if user_data["zero_snus_days"] >= 3:
            send_whatsapp_message("🎉 You’ve gone 3 days with 0 snus at 3mg — you’ve quit! Amazing work! 💪")
            user_data["graduated"] = True
    else:
        user_data["zero_snus_days"] = 0

    # Weaker snus unlock
    if user_data["limit"] == 3 and user_data["current_mg"] > 3:
        send_whatsapp_message("🚨 You’ve hit 3/day. You can now choose a weaker snus level.")
        send_mg_list(unlock=True)

    # Update for new day
    user_data["yesterday_total"] = user_data["current_day_snus"]
    user_data["limit"] = max(user_data["yesterday_total"] - 1, user_data["min_limit"])
    user_data["current_day_snus"] = 0
    user_data["snus_mg"] = []
    user_data["failed"] = False

    if not user_data.get("graduated", False):
        send_button_message()

    save_user_data(user_data)

# Load and schedule
user_data = get_user_data()
scheduler = BackgroundScheduler()
scheduler.add_job(midnight_reset, 'cron', hour=0, minute=0)
scheduler.start()
