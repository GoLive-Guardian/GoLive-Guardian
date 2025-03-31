from dotenv import load_dotenv
import os

load_dotenv()


bot_token = os.getenv("BOT_TOKEN")
mongo_uri = os.getenv("MONGO_URI")