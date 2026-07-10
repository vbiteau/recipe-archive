from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Recipe(db.Model):
    __tablename__ = "recipes"

    id = db.Column(db.Integer, primary_key=True)

    title = db.Column(db.String(300), nullable=False)

    # Country of origin, as inferred by Claude during formatting
    country_name = db.Column(db.String(120), nullable=True, index=True)
    country_code = db.Column(db.String(2), nullable=True, index=True)  # ISO 3166-1 alpha-2

    cuisine_region = db.Column(db.String(150), nullable=True)  # e.g. "Sichuan", "Tuscany" — optional finer detail

    servings = db.Column(db.String(50), nullable=True)
    prep_time = db.Column(db.String(50), nullable=True)
    cook_time = db.Column(db.String(50), nullable=True)
    total_time = db.Column(db.String(50), nullable=True)

    ingredients = db.Column(db.JSON, nullable=False, default=list)  # list of strings
    steps = db.Column(db.JSON, nullable=False, default=list)        # list of strings
    notes = db.Column(db.Text, nullable=True)

    image_url = db.Column(db.String(1000), nullable=True)
    source_url = db.Column(db.String(1000), nullable=False)
    source_domain = db.Column(db.String(300), nullable=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "country_name": self.country_name,
            "country_code": self.country_code,
            "cuisine_region": self.cuisine_region,
            "servings": self.servings,
            "prep_time": self.prep_time,
            "cook_time": self.cook_time,
            "total_time": self.total_time,
            "ingredients": self.ingredients,
            "steps": self.steps,
            "notes": self.notes,
            "image_url": self.image_url,
            "source_url": self.source_url,
            "source_domain": self.source_domain,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
