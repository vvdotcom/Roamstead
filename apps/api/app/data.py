from .models import Candidate, ScoreComponents


CANDIDATES = [
    Candidate(
        id="thu-thiem", name="Thu Thiem", district="Thu Duc City",
        tagline="Riverfront energy with a polished new-city feel",
        image="https://images.unsplash.com/photo-1559592413-7cec4d0cae2b?auto=format&fit=crop&w=900&q=82",
        components=ScoreComponents(budget=84, healthcare=95, remote_work=98, waterfront=95, quiet=42, international_school=82, food_access=88),
        price_from_usd=142000, rent_from_usd=1250, hospital_minutes=14, waterfront_minutes=3, international_school_minutes=18, food_minutes=8, homes=8,
        map_x=60, map_y=37,
        tradeoff="Excellent access, but construction and high-rise density may feel intense.",
    ),
    Candidate(
        id="binh-thanh", name="Binh Thanh", district="Binh Thanh District",
        tagline="Central convenience beside leafy canal pockets",
        image="https://images.unsplash.com/photo-1583417319070-4a69db38a482?auto=format&fit=crop&w=900&q=82",
        components=ScoreComponents(budget=90, healthcare=98, remote_work=96, waterfront=82, quiet=35, international_school=88, food_access=97),
        price_from_usd=118000, rent_from_usd=900, hospital_minutes=9, waterfront_minutes=8, international_school_minutes=15, food_minutes=5, homes=11,
        map_x=51, map_y=29,
        tradeoff="Strong value and healthcare access, with heavy traffic at peak hours.",
    ),
    Candidate(
        id="phu-my-hung", name="Phu My Hung", district="District 7",
        tagline="Walkable, green and family-ready",
        image="https://images.unsplash.com/photo-1593696140826-c58b021acf8b?auto=format&fit=crop&w=900&q=82",
        components=ScoreComponents(budget=88, healthcare=94, remote_work=94, waterfront=78, quiet=82, international_school=98, food_access=95),
        price_from_usd=126000, rent_from_usd=1050, hospital_minutes=11, waterfront_minutes=9, international_school_minutes=8, food_minutes=6, homes=10,
        map_x=49, map_y=63,
        tradeoff="More planned and comfortable, but farther from the historic core.",
    ),
    Candidate(
        id="nha-be", name="Nha Be Riverside", district="Nha Be District",
        tagline="More room, slower streets and riverside calm",
        image="https://images.unsplash.com/photo-1600607687939-ce8a6c25118c?auto=format&fit=crop&w=900&q=82",
        components=ScoreComponents(budget=95, healthcare=85, remote_work=80, waterfront=80, quiet=92, international_school=74, food_access=76),
        price_from_usd=104000, rent_from_usd=720, hospital_minutes=24, waterfront_minutes=5, international_school_minutes=25, food_minutes=12, homes=7,
        map_x=56, map_y=78,
        tradeoff="The quietest fit, with a longer trip to central-city work and culture.",
    ),
]
