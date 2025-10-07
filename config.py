import os
from dotenv import load_dotenv
load_dotenv()  

#TOKEN = '8098563516:AAGETMTZnjzS1uSoEyCLS5A64Bb55sD5Fj4'

TOKEN = os.getenv("BOT_TOKEN", "8098563516:AAGETMTZnjzS1uSoEyCLS5A64Bb55sD5Fj4")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./app.db")
QWEN_API_KEY = 'Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6Ijk1YjBhOTg5LTNlMzItNDM2NC05YTZjLTk1ZWE1MTJiMzFiNCIsImxhc3RfcGFzc3dvcmRfY2hhbmdlIjoxNzU0NzcyMzAxLCJleHAiOjE3NTczNjQzMDR9.aB-ECrhNOgf6wKvYvENx31ynFLTyLvrjQSMIDb3mvAo'


REFERRAL_BONUS_INVITED = int(os.getenv("REFERRAL_BONUS_INVITED", "10"))    # новичку по приглашению
REFERRAL_BONUS_REFERRER = int(os.getenv("REFERRAL_BONUS_REFERRER", "10"))  # пригласившему
DEFAULT_FREE_CREDITS     = int(os.getenv("DEFAULT_FREE_CREDITS", "0"))     # на старт без промо/приглашения
PROMO_DEFAULT_CREDITS    = int(os.getenv("PROMO_DEFAULT_CREDITS", "10"))   # если промокод маркетинговый без своих настроек
BOT_USERNAME             = os.getenv("BOT_USERNAME", "kartataro1_bot") 

ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")

ADVICE_BASIC_PRICE = int(os.getenv("ADVICE_BASIC_PRICE", "4900"))  # мин. единицы (копейки)
ADVICE_CURRENCY    = os.getenv("ADVICE_CURRENCY", "RUB")

DEFAULT_FREE_CREDITS = 2
