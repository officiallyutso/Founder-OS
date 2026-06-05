from config import config

def is_authorized(user_id: int) -> bool:
    return user_id == config.my_telegram_user_id
