"""
Instagram targeting engine.

Converts high-level targeting criteria (gender, city, state, business type)
into the most effective hashtag pools that attract real accounts matching
those criteria.  Then drives the existing EngagementManager.follow_by_tag
loop with those hashtags — no unofficial API, no scraping, 100% Graph API.

Why hashtags?
  The public Instagram Graph API (Business Discovery + Hashtag Search) does
  not expose gender / location fields on arbitrary users.  The proven
  workaround used by every major growth tool is *proxy targeting*:
    - Gender    → hashtags whose audience skews heavily toward that gender
    - City/State�� city name + popular local hashtags + city-specific accounts
    - Business  → industry hashtags + business-related bio keywords
  Accounts found via those hashtags are far more likely to match the target
  profile than a random follow pool, and they follow back at higher rates.
"""

from __future__ import annotations
import logging
from typing import Optional

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  Hashtag maps
# ─────────────────────────────────────────────────────────────────────────────

GENDER_HASHTAGS: dict[str, list[str]] = {
    "male": [
        "mensfashion", "mensstyle", "menwithstyle", "beardgang", "fitnessmen",
        "menshair", "mensgrooming", "menstyle", "guystyle", "malefitness",
        "brotips", "menswear", "dadlife", "gymlife", "menshealth",
    ],
    "female": [
        "womensfashion", "girlboss", "womenempowerment", "ladiesfashion",
        "makeupartist", "beautyinfluencer", "womeninbusiness", "selfcare",
        "womanmotivation", "girlstyle", "bossbabe", "femalefitness",
        "momblog", "womenofinstagram", "fashionista",
    ],
    "any": [
        "lifestyle", "motivation", "inspiration", "dailylife", "photography",
    ],
}

CITY_HASHTAGS: dict[str, list[str]] = {
    # India
    "mumbai":       ["mumbai", "mumbaiinstagram", "mumbaifoodie", "mumbaifashion", "nammumhai"],
    "delhi":        ["delhi", "delhigram", "delhifoodie", "delhifashion", "delhidiaries"],
    "bangalore":    ["bangalore", "bangalorediaries", "nammabengaluru", "bangalorefoodie", "bengaluru"],
    "hyderabad":    ["hyderabad", "hyderabaddiaries", "hyderabadifoodie", "cyberabad", "nawabcity"],
    "chennai":      ["chennai", "chennaidiaries", "chennaifoodie", "madras", "nammachennai"],
    "kolkata":      ["kolkata", "kolkatadiaries", "kolkatafoodie", "cityofjoy", "bengal"],
    "pune":         ["pune", "punediaries", "punefoodie", "punegram", "puneinstagram"],
    "ahmedabad":    ["ahmedabad", "amdavad", "ahmedabadfoodie", "gujaratfoodie", "ahmedabaddiaries"],
    "jaipur":       ["jaipur", "jaipurdiaries", "pinkcity", "rajasthan", "jaipurfoodie"],
    # USA
    "newyork":      ["newyork", "nyc", "nyclife", "newyorkcity", "nycfoodie", "brooklynlife"],
    "losangeles":   ["losangeles", "la", "lalife", "losangelesfoodie", "ellay", "socal"],
    "chicago":      ["chicago", "chicagolife", "windycity", "chicagofood", "chicagogram"],
    "houston":      ["houston", "houstonlife", "houstontexas", "htx", "houstonfood"],
    "miami":        ["miami", "miamilife", "miamibeach", "miamifoodie", "305"],
    # UK
    "london":       ["london", "londonlife", "londondiaries", "londonfoodie", "thisislondon"],
    # Generic fallback
    "default":      ["citylife", "urbanlife", "cityvibes", "cityphotography"],
}

STATE_HASHTAGS: dict[str, list[str]] = {
    # India states
    "maharashtra":  ["maharashtra", "mumbai", "pune", "nashik", "maharashtratourism"],
    "karnataka":    ["karnataka", "bangalore", "mysore", "karnatakagram", "incrediblekarnataka"],
    "tamilnadu":    ["tamilnadu", "chennai", "coimbatore", "madurai", "tamilnadudiaries"],
    "gujarat":      ["gujarat", "ahmedabad", "surat", "gujaratdiaries", "gujaratfoodie"],
    "rajasthan":    ["rajasthan", "jaipur", "udaipur", "jodhpur", "royalrajasthan"],
    "westbengal":   ["westbengal", "kolkata", "bengal", "bengalidiaries"],
    "delhi":        ["delhi", "ncr", "delhincr", "newdelhi"],
    # USA states
    "california":   ["california", "cali", "socal", "norcal", "visitcalifornia"],
    "texas":        ["texas", "texaslife", "texan", "lonestarstate", "everythingisbiggerintexas"],
    "florida":      ["florida", "floridaLife", "floridaliving", "sunshine_state", "visitflorida"],
    "newyorkstate": ["newyork", "nystate", "empirestateofmind", "upstateny"],
    # Generic
    "default":      ["travel", "explore", "wanderlust", "locallife"],
}

BUSINESS_HASHTAGS: dict[str, list[str]] = {
    "restaurant":    ["restaurant", "foodie", "instafood", "restaurantowner", "cheflife",
                      "foodbusiness", "cafestagram", "streetfood", "foodentrepreneur"],
    "fashion":       ["fashionbrand", "fashiondesigner", "fashionblogger", "ootd",
                      "fashionbusiness", "clothingbrand", "boutique", "styleinfluencer"],
    "fitness":       ["fitnessbusiness", "personaltrainer", "gymowner", "fitnesscoach",
                      "fitnessstudio", "healthcoach", "wellnesscoach", "fitfam"],
    "beauty":        ["beautybusiness", "makeupartist", "beautycoach", "salonowner",
                      "beautysalon", "skincarecoach", "nailart", "beautyentrepreneur"],
    "realestate":    ["realestate", "realestateagent", "realtorlife", "propertyinvestor",
                      "realestatemarketing", "luxuryhomes", "realestateentrepreneur"],
    "ecommerce":     ["ecommerce", "onlinebusiness", "dropshipping", "smallbusiness",
                      "shopify", "etsy", "onlineshopping", "ecommercebusiness"],
    "tech":          ["techstartup", "softwareengineering", "techfounder", "saas",
                      "startup", "entrepreneur", "innovation", "techindustry"],
    "photography":   ["photographer", "photographybusiness", "weddingphotographer",
                      "commercialphotography", "portraitphotography", "photographylovers"],
    "coaching":      ["lifecoach", "businesscoach", "mindsetcoach", "motivationalspeaker",
                      "coachingbusiness", "onlinecoach", "successcoach"],
    "healthcare":    ["healthcareworker", "doctor", "nurse", "medicallife", "healthcare",
                      "physicaltherapy", "mentalhealth", "wellnessjourney"],
    "education":     ["teacher", "educator", "onlinelearning", "edtech", "tutoring",
                      "educationbusiness", "studygram", "learnwithme"],
    "travel":        ["travelblogger", "travelbusiness", "travelagent", "touroperator",
                      "travelinfluencer", "wanderlust", "exploretheworld"],
    "default":       ["entrepreneur", "smallbusiness", "businessowner", "startup",
                      "hustleculture", "businessmindset", "growthmindset"],
}


def get_gender_hashtags(gender: str) -> list[str]:
    """Return targeting hashtags for a gender."""
    g = gender.lower().strip()
    if g in ("male", "man", "men", "boy", "m"):
        return GENDER_HASHTAGS["male"]
    if g in ("female", "woman", "women", "girl", "f"):
        return GENDER_HASHTAGS["female"]
    return GENDER_HASHTAGS["any"]


def get_city_hashtags(city: str) -> list[str]:
    """Return targeting hashtags for a city."""
    key = city.lower().replace(" ", "").replace("-", "")
    return CITY_HASHTAGS.get(key, CITY_HASHTAGS["default"] + [city.lower().replace(" ", "")])


def get_state_hashtags(state: str) -> list[str]:
    """Return targeting hashtags for a state/region."""
    key = state.lower().replace(" ", "").replace("-", "")
    return STATE_HASHTAGS.get(key, STATE_HASHTAGS["default"] + [key])


def get_business_hashtags(business_type: str) -> list[str]:
    """Return targeting hashtags for a business category."""
    key = business_type.lower().replace(" ", "").replace("-", "")
    for btype, tags in BUSINESS_HASHTAGS.items():
        if key in btype or btype in key:
            return tags
    return BUSINESS_HASHTAGS.get(key, BUSINESS_HASHTAGS["default"])


def build_targeted_hashtags(
    gender:        Optional[str] = None,
    city:          Optional[str] = None,
    state:         Optional[str] = None,
    business_type: Optional[str] = None,
    extra_tags:    Optional[list[str]] = None,
) -> list[str]:
    """
    Combine hashtags from all requested dimensions into a deduplicated list,
    ordered by specificity (most targeted first).
    """
    pool: list[str] = []

    # Most specific first → city > state > business > gender
    if city:
        pool += get_city_hashtags(city)
    if state:
        pool += get_state_hashtags(state)
    if business_type:
        pool += get_business_hashtags(business_type)
    if gender:
        pool += get_gender_hashtags(gender)
    if extra_tags:
        pool += [t.lstrip("#") for t in extra_tags]

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for tag in pool:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)

    return result


def describe_target(
    gender: Optional[str],
    city: Optional[str],
    state: Optional[str],
    business_type: Optional[str],
) -> str:
    """Human-readable description of the targeting criteria."""
    parts = []
    if gender:
        parts.append(f"gender={gender}")
    if city:
        parts.append(f"city={city}")
    if state:
        parts.append(f"state={state}")
    if business_type:
        parts.append(f"business={business_type}")
    return " + ".join(parts) if parts else "general"
