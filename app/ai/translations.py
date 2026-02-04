"""
Fixed chat strings in English and Swedish.
"""
from app.config import settings

TEXTS = {
    "en": {
        "welcome": lambda: f"Hi! How cool that you're interested in {settings.free_trial_days} days of free training with us at {settings.gym_name}!\n\nWhen would you like to come to activate your trial period and get a tour of the gym?",
        "welcome_hi": lambda name: f"Hi {name}! How cool that you're interested in {settings.free_trial_days} days of free training with us at {settings.gym_name}!\n\nWhen would you like to come to activate your trial period and get a tour of the gym?",
        "please_enter_name": "Please enter your name:",
        "please_enter_email": "Please enter your email address:",
        "please_enter_phone": "Please enter your phone number:",
        "enter_info_above": "Please enter the information requested above.",
        "booking_intro": lambda name, link: (
            f"Perfect, {name}! Now let's get you booked for your free {settings.free_trial_days}-day trial at {settings.gym_name}!\n\n"
            "You'll get: Full gym access, all equipment, group training classes, personal gym tour.\n\n"
            f"Please book your appointment at a time that works best for you using this link:\n{link}\n\n"
            "Once you've booked, I'll confirm everything for you!"
        ),
        "booking_confirm_calendar": "Great! I'll check the calendar and confirm your booking. You should receive a confirmation email shortly!",
        "book_link_once": lambda link: f"Great! Please use this link to book your appointment at a time that works best for you:\n{link}\n\nOnce you've booked, I'll confirm everything for you!",
    },
    "sv": {
        "welcome": lambda: f"Hej! Kul att du är intresserad av {settings.free_trial_days} dagars gratis träning hos oss på {settings.gym_name}!\n\nNär vill du komma för att aktivera din provperiod och få en rundtur i gymmet?",
        "welcome_hi": lambda name: f"Hej {name}! Kul att du är intresserad av {settings.free_trial_days} dagars gratis träning hos oss på {settings.gym_name}!\n\nNär vill du komma för att aktivera din provperiod och få en rundtur i gymmet?",
        "please_enter_name": "Ange ditt namn:",
        "please_enter_email": "Ange din e-postadress:",
        "please_enter_phone": "Ange ditt telefonnummer:",
        "enter_info_above": "Ange den information som begärts ovan.",
        "booking_intro": lambda name, link: (
            f"Perfekt, {name}! Nu bokar vi in dig för din gratis {settings.free_trial_days}-dagars provperiod på {settings.gym_name}!\n\n"
            "Du får: Full tillgång till gymmet, all utrustning, gruppträning, personlig gymrundtur.\n\n"
            f"Boka din tid när det passar dig bäst via denna länk:\n{link}\n\n"
            "När du bokat bekräftar jag allt!"
        ),
        "booking_confirm_calendar": "Bra! Jag kollar kalendern och bekräftar din bokning. Du får en bekräftelse via e-post snart!",
        "book_link_once": lambda link: f"Bra! Använd denna länk för att boka din tid när det passar dig:\n{link}\n\nNär du bokat bekräftar jag allt!",
    },
}


def get(lang: str, key: str, **kwargs) -> str:
    """Get translated string. lang in ('en', 'sv'), falls back to 'en'."""
    locale = "sv" if lang == "sv" else "en"
    val = TEXTS[locale].get(key, TEXTS["en"].get(key, key))
    if callable(val):
        return val(**kwargs)
    if isinstance(val, str) and kwargs:
        return val.format(**kwargs)
    return val
