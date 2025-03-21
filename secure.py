import jwt
from datetime import datetime, timedelta
import time
from fastapi import HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from graphqlschema.schema import (
    UserInformation
)
from helper import get_user_db

SECRET_KEY = "1234567890abC"  # Use a secure key in production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Create JWT Token
def create_jwt_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire.timestamp()})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# Verify JWT Token
def verify_jwt_token(token: str):
    try:
        decoded_token = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return decoded_token if decoded_token["exp"] >= datetime.now().timestamp() else None
    except Exception as err:
        print(f"error: {err}")
        return None
    # except jwt.PyJWTError:
    #     print('err')
    #     return None
    
def get_user_information(token: str) -> UserInformation:
    try:
        #print(token)
        decode_token = verify_jwt_token(token)
        if decode_token:
            userid = decode_token["sub"]
            return get_user_db(userid)
        return None
    except Exception as err:
        print(err)
        return None