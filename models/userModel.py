from pydantic import BaseModel, EmailStr

class User(BaseModel):
    username: str
    email: EmailStr
    password: str
    location: str = None

class UserLogin(BaseModel):
    email: EmailStr
    password: str