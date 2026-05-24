import sys
import os
import random
from datetime import datetime, timezone, timedelta

# Add parent directory to path so imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.db import get_database

DISTRICTS = [
    {"id": 1, "name": "Colombo"},
    {"id": 2, "name": "Gampaha"},
    {"id": 3, "name": "Kalutara"},
    {"id": 4, "name": "Kandy"},
    {"id": 5, "name": "Matale"}
]

DISEASES = [
    {"id": 1, "name": "Dengue"},
    {"id": 2, "name": "Leptospirosis"}
]

def generate_data():
    db = get_database()
    
    current_time = datetime.now(timezone.utc)
    current_week = current_time.isocalendar()[1]
    current_year = current_time.year

    for district in DISTRICTS:
        dist_name_clean = district["name"].replace(' ', '_').lower()
        collection_name = f"ceri_{dist_name_clean}"
        collection = db[collection_name]
        
        # Clear existing mock data if needed? No, let's just upsert
        for disease in DISEASES:
            # Generate past 10 weeks
            for i in range(10):
                week = current_week - i
                year = current_year
                if week <= 0:
                    week += 52
                    year -= 1
                    
                # Create some fake numbers
                base_score = random.uniform(10, 80)
                ceri_score = min(100.0, base_score * random.uniform(0.8, 1.2))
                
                if ceri_score <= 15:
                    risk_level = "low"
                elif ceri_score <= 40:
                    risk_level = "moderate"
                elif ceri_score <= 65:
                    risk_level = "high"
                else:
                    risk_level = "critical"
                    
                query = {
                    "disease_id": disease["id"],
                    "week_number": week,
                    "year": year
                }
                
                doc = {
                    "$set": {
                        "disease_id": disease["id"],
                        "disease_name": disease["name"],
                        "district_id": district["id"],
                        "district_name": district["name"],
                        "week_number": week,
                        "year": year,
                        "ceri_score": round(ceri_score, 2),
                        "risk_level": risk_level,
                        "report_count": random.randint(0, 50),
                        "vote_total": random.randint(0, 100),
                        "components": {
                            "report_density": round(random.uniform(0, 40), 2),
                            "vote_credibility": round(random.uniform(0, 40), 2),
                            "temporal_urgency": round(random.uniform(0, 20), 2),
                            "base_score": round(base_score, 2),
                            "dsm": {
                                "severity_mode": random.choice(["low", "moderate", "severe"]),
                                "severity_weight": 1.0,
                                "avg_confidence": 0.8,
                                "confidence_level": "high",
                                "confidence_boost": 1.1,
                                "dsm": 1.1
                            }
                        },
                        "calculated_at": (current_time - timedelta(weeks=i)).isoformat()
                    }
                }
                
                collection.update_one(query, doc, upsert=True)
                
        print(f"✅ Generated mock CERI data for {district['name']}")

if __name__ == "__main__":
    generate_data()
    print("All mock data generated successfully!")
