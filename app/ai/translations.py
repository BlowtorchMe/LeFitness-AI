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
        "booking_intro": lambda name, link, gym_name=None: (
            f"Perfect, {name}! Now let's get you booked for your free {settings.free_trial_days}-day trial at {gym_name or settings.gym_name}!\n\n"
            "You'll get: Full gym access, all equipment, group training classes, personal gym tour.\n\n"
            f"Please book your appointment at a time that works best for you using this link:\n{link}\n\n"
            "Once you've booked, I'll confirm everything for you!"
        ),
        "booking_follow_up": lambda name, link, gym_name=None: (
            f"Hi {name}, just checking in. If you'd still like to try {gym_name or settings.gym_name}, you can book your free {settings.free_trial_days}-day trial here:\n{link}\n\n"
            "If you have any other questions first, just send them here."
        ),
        "booking_confirmed_webhook": lambda dt: f"I can see you've booked your trial for {dt}! We're looking forward to seeing you. You should also receive a confirmation email from Google Calendar.",
        "book_link_once": lambda link: f"Great! Please use this link to book your appointment at a time that works best for you:\n{link}\n\nOnce you've booked, I'll confirm everything for you!",
        "service_overview_prompt": "Of course. Ask anything you want. If helpful, you can ask about opening hours, prices, classes, equipment, parking, or personal training.",
        "select_gym_booking": "Perfect. Which gym would you like to book for?",
        "select_gym_question": "Which gym are you asking about?",
        "gym_phone": lambda gym_name, phone: f"The phone number for {gym_name} is {phone}.",
        "gym_phone_missing": "not available right now",
        "gym_location": lambda gym_name, location: f"{gym_name} is located at {location}.",
        "no_gyms_available": "No gyms are available right now. Please try again later.",
    },
    "sv": {
        "welcome": lambda: f"Hej! Kul att du är intresserad av {settings.free_trial_days} dagars gratis träning hos oss på {settings.gym_name}!\n\nNär vill du komma för att aktivera din provperiod och få en rundtur i gymmet?",
        "welcome_hi": lambda name: f"Hej {name}! Kul att du är intresserad av {settings.free_trial_days} dagars gratis träning hos oss på {settings.gym_name}!\n\nNär vill du komma för att aktivera din provperiod och få en rundtur i gymmet?",
        "please_enter_name": "Ange ditt namn:",
        "please_enter_email": "Ange din e-postadress:",
        "please_enter_phone": "Ange ditt telefonnummer:",
        "enter_info_above": "Ange den information som begärts ovan.",
        "booking_intro": lambda name, link, gym_name=None: (
            f"Perfekt, {name}! Nu bokar vi in dig för din gratis {settings.free_trial_days}-dagars provperiod på {gym_name or settings.gym_name}!\n\n"
            "Du får: Full tillgång till gymmet, all utrustning, gruppträning, personlig gymrundtur.\n\n"
            f"Boka din tid när det passar dig bäst via denna länk:\n{link}\n\n"
            "När du bokat bekräftar jag allt!"
        ),
        "booking_follow_up": lambda name, link, gym_name=None: (
            f"Hej {name}, jag ville bara följa upp. Om du fortfarande vill prova {gym_name or settings.gym_name} kan du boka din gratis {settings.free_trial_days}-dagars provperiod här:\n{link}\n\n"
            "Om du vill fråga något mer först är det bara att skriva här."
        ),
        "booking_confirmed_webhook": lambda dt: f"Jag ser att du har bokat din provperiod {dt}! Vi ser fram emot att träffa dig. Du borde också ha fått en bekräftelse via e-post från Google Calendar.",
        "book_link_once": lambda link: f"Bra! Använd denna länk för att boka din tid när det passar dig:\n{link}\n\nNär du bokat bekräftar jag allt!",
        "service_overview_prompt": "Självklart. Fråga vad du vill. Om det hjälper kan du fråga om öppettider, priser, klasser, utrustning, parkering eller personlig träning.",
        "select_gym_booking": "Perfekt. Vilket gym vill du boka för?",
        "select_gym_question": "Vilket gym menar du?",
        "gym_phone": lambda gym_name, phone: f"Telefonnumret till {gym_name} är {phone}.",
        "gym_phone_missing": "inte tillgängligt just nu",
        "gym_location": lambda gym_name, location: f"{gym_name} ligger på {location}.",
        "no_gyms_available": "Inga gym är tillgängliga just nu. Försök igen senare.",
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

