#!/usr/bin/env python3
from pymongo import MongoClient, errors
import bcrypt
from dotenv import load_dotenv
import os

load_dotenv()
client = MongoClient(os.getenv("MONGO_URI"))

db = client["mydatabase"]
users = db["users"]

users.replace_one(
    {"phone": "01757358755"},          # use phone as lookup key
    {
        "name": "SuperAdmin",
        "phone": "01757358755",
        "password": bcrypt.hashpw("123456".encode(), bcrypt.gensalt()),
        "role": "admin"
    },
    upsert=True
)
print("✅ Admin seeded.")