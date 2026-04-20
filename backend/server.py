from fastapi import FastAPI, APIRouter, HTTPException, Depends, Response, Request
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, EmailStr
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta
import bcrypt
import jwt
import httpx

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]

# JWT Configuration
JWT_SECRET = os.environ.get('JWT_SECRET', 'rasaa-atelier-secret-key-2024')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 168  # 7 days

app = FastAPI(title="RASAA Atelier API")
api_router = APIRouter(prefix="/api")

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==================== MODELS ====================

class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    company: Optional[str] = None
    is_b2b: bool = False

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    user_id: str
    email: str
    name: str
    company: Optional[str] = None
    is_b2b: bool = False
    is_approved: bool = False
    picture: Optional[str] = None
    created_at: datetime

class WholesaleAccessRequest(BaseModel):
    company_name: str
    contact_name: str
    email: EmailStr
    phone: str
    business_type: str
    message: Optional[str] = None

class QuoteRequest(BaseModel):
    material_id: str
    material_name: str
    quantity: str
    specifications: Optional[str] = None
    name: str
    email: EmailStr
    company: Optional[str] = None
    phone: Optional[str] = None

class ContactRequest(BaseModel):
    name: str
    email: EmailStr
    subject: str
    message: str
    product_id: Optional[str] = None

class Material(BaseModel):
    id: str
    name: str
    name_fr: str
    category: str
    subcategory: str
    region: str
    description: str
    description_fr: str
    image: str
    price_range: Optional[str] = None
    min_order: Optional[str] = None
    lead_time: Optional[str] = None

class Product(BaseModel):
    id: str
    name: str
    name_fr: str
    category: str
    price: float
    currency: str = "EUR"
    description: str
    description_fr: str
    image: str
    images: List[str] = []
    region: str
    artisan_cluster: str
    provenance: str
    provenance_fr: str
    in_stock: bool = True

# ==================== AUTH HELPERS ====================

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_token(user_id: str) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

async def get_current_user(request: Request) -> Optional[dict]:
    # Check cookie first
    token = request.cookies.get("session_token")
    # Then check Authorization header
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
    if not token:
        return None
    
    # Check session in database
    session = await db.user_sessions.find_one({"session_token": token}, {"_id": 0})
    if not session:
        return None
    
    # Check expiry
    expires_at = session.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None
    
    user = await db.users.find_one({"user_id": session["user_id"]}, {"_id": 0})
    return user

async def require_auth(request: Request) -> dict:
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user

async def require_b2b(request: Request) -> dict:
    user = await require_auth(request)
    if not user.get("is_b2b") or not user.get("is_approved"):
        raise HTTPException(status_code=403, detail="B2B access required")
    return user

# ==================== AUTH ROUTES ====================

@api_router.post("/auth/register")
async def register(user_data: UserCreate, response: Response):
    existing = await db.users.find_one({"email": user_data.email}, {"_id": 0})
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    user_doc = {
        "user_id": user_id,
        "email": user_data.email,
        "password_hash": hash_password(user_data.password),
        "name": user_data.name,
        "company": user_data.company,
        "is_b2b": user_data.is_b2b,
        "is_approved": False if user_data.is_b2b else True,
        "picture": None,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.users.insert_one(user_doc)
    
    # Create session
    session_token = f"session_{uuid.uuid4().hex}"
    session_doc = {
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.user_sessions.insert_one(session_doc)
    
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=JWT_EXPIRATION_HOURS * 3600
    )
    
    user_doc.pop("password_hash")
    user_doc.pop("_id", None)
    return {"user": user_doc, "token": session_token}

@api_router.post("/auth/login")
async def login(credentials: UserLogin, response: Response):
    user = await db.users.find_one({"email": credentials.email}, {"_id": 0})
    if not user or not verify_password(credentials.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Create session
    session_token = f"session_{uuid.uuid4().hex}"
    session_doc = {
        "user_id": user["user_id"],
        "session_token": session_token,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.user_sessions.insert_one(session_doc)
    
    response.set_cookie(
        key="session_token",
        value=session_token,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
        max_age=JWT_EXPIRATION_HOURS * 3600
    )
    
    user.pop("password_hash", None)
    return {"user": user, "token": session_token}

@api_router.get("/auth/session")
async def exchange_session(session_id: str, response: Response):
    """Exchange Emergent OAuth session_id for user data"""
    # REMINDER: DO NOT HARDCODE THE URL, OR ADD ANY FALLBACKS OR REDIRECT URLS, THIS BREAKS THE AUTH
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data",
                headers={"X-Session-ID": session_id}
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid session")
            
            data = resp.json()
            email = data.get("email")
            name = data.get("name")
            picture = data.get("picture")
            session_token = data.get("session_token")
            
            # Find or create user
            user = await db.users.find_one({"email": email}, {"_id": 0})
            if not user:
                user_id = f"user_{uuid.uuid4().hex[:12]}"
                user = {
                    "user_id": user_id,
                    "email": email,
                    "name": name,
                    "picture": picture,
                    "company": None,
                    "is_b2b": False,
                    "is_approved": True,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                await db.users.insert_one(user)
            else:
                user_id = user["user_id"]
                # Update picture if changed
                if picture and picture != user.get("picture"):
                    await db.users.update_one({"user_id": user_id}, {"$set": {"picture": picture}})
                    user["picture"] = picture
            
            # Store session
            session_doc = {
                "user_id": user_id,
                "session_token": session_token,
                "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            await db.user_sessions.insert_one(session_doc)
            
            response.set_cookie(
                key="session_token",
                value=session_token,
                httponly=True,
                secure=True,
                samesite="none",
                path="/",
                max_age=7 * 24 * 3600
            )
            
            user.pop("_id", None)
            user.pop("password_hash", None)
            return {"user": user, "token": session_token}
            
    except httpx.RequestError as e:
        logger.error(f"OAuth session exchange failed: {e}")
        raise HTTPException(status_code=500, detail="Authentication service unavailable")

@api_router.get("/auth/me")
async def get_me(request: Request):
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user.pop("password_hash", None)
    return user

@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    token = request.cookies.get("session_token")
    if token:
        await db.user_sessions.delete_one({"session_token": token})
    response.delete_cookie(key="session_token", path="/")
    return {"message": "Logged out"}

# ==================== WHOLESALE ACCESS ====================

@api_router.post("/wholesale/request")
async def request_wholesale_access(data: WholesaleAccessRequest):
    request_id = f"ws_{uuid.uuid4().hex[:12]}"
    doc = {
        "request_id": request_id,
        **data.model_dump(),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.wholesale_requests.insert_one(doc)
    return {"message": "Request submitted successfully", "request_id": request_id}

# ==================== MATERIALS (B2B) ====================

# Sample materials data
MATERIALS = [
    {
        "id": "gem_001", "name": "Jaipur Ruby", "name_fr": "Rubis de Jaipur", "category": "gemstones",
        "subcategory": "Precious Stones", "region": "Rajasthan",
        "description": "Hand-cut rubies from the pink city, renowned for their deep crimson hue",
        "description_fr": "Rubis taillés à la main de la ville rose, réputés pour leur teinte cramoisie profonde",
        "image": "https://images.unsplash.com/photo-1599707367072-cd6ada2bc375?auto=format&fit=crop&q=80",
        "price_range": "€500-€5,000/ct", "min_order": "5 carats", "lead_time": "2-4 weeks"
    },
    {
        "id": "gem_002", "name": "Surat Lab Diamonds", "name_fr": "Diamants de Laboratoire Surat", "category": "gemstones",
        "subcategory": "Lab-Grown Diamonds", "region": "Gujarat",
        "description": "CVD diamonds crafted in Surat, the diamond capital of the world",
        "description_fr": "Diamants CVD créés à Surat, capitale mondiale du diamant",
        "image": "https://images.unsplash.com/photo-1615655406736-b37c4fabf923?auto=format&fit=crop&q=80",
        "price_range": "€200-€2,000/ct", "min_order": "10 carats", "lead_time": "1-2 weeks"
    },
    {
        "id": "gem_003", "name": "Kashmir Sapphire", "name_fr": "Saphir du Cachemire", "category": "gemstones",
        "subcategory": "Precious Stones", "region": "Kashmir",
        "description": "Rare cornflower blue sapphires from the Himalayan valleys",
        "description_fr": "Rares saphirs bleu bleuet des vallées himalayennes",
        "image": "https://images.unsplash.com/photo-1761717410058-5a2c296d0893?auto=format&fit=crop&q=80",
        "price_range": "€1,000-€15,000/ct", "min_order": "2 carats", "lead_time": "4-6 weeks"
    },
    {
        "id": "tex_001", "name": "Rajasthan Block Print", "name_fr": "Impression Bloc du Rajasthan", "category": "textiles",
        "subcategory": "Block Prints", "region": "Rajasthan",
        "description": "Hand-stamped cotton using centuries-old wooden blocks from Bagru and Sanganer",
        "description_fr": "Coton imprimé à la main avec des blocs de bois centenaires de Bagru et Sanganer",
        "image": "https://images.pexels.com/photos/6332015/pexels-photo-6332015.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "price_range": "€15-€45/m", "min_order": "50 meters", "lead_time": "3-4 weeks"
    },
    {
        "id": "tex_002", "name": "Chanderi Silk", "name_fr": "Soie de Chanderi", "category": "textiles",
        "subcategory": "Silks", "region": "Madhya Pradesh",
        "description": "Gossamer-light silk woven with gold and silver zari in the ancient town of Chanderi",
        "description_fr": "Soie légère comme une plume tissée avec du zari d'or et d'argent dans l'ancienne ville de Chanderi",
        "image": "https://images.pexels.com/photos/6045235/pexels-photo-6045235.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "price_range": "€80-€200/m", "min_order": "20 meters", "lead_time": "4-6 weeks"
    },
    {
        "id": "tex_003", "name": "Lucknowi Chikankari", "name_fr": "Chikankari de Lucknow", "category": "textiles",
        "subcategory": "Embroidery", "region": "Uttar Pradesh",
        "description": "Delicate white-on-white embroidery, a Mughal-era craft from the city of nawabs",
        "description_fr": "Broderie délicate blanc sur blanc, un artisanat de l'ère moghole de la ville des nawabs",
        "image": "https://images.pexels.com/photos/6044227/pexels-photo-6044227.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "price_range": "€100-€500/piece", "min_order": "10 pieces", "lead_time": "6-8 weeks"
    },
    {
        "id": "tex_004", "name": "Banarasi Brocade", "name_fr": "Brocart de Bénarès", "category": "textiles",
        "subcategory": "Silks", "region": "Uttar Pradesh",
        "description": "Opulent silk brocades with intricate gold thread work from the holy city of Varanasi",
        "description_fr": "Brocarts de soie opulents avec un travail complexe de fil d'or de la ville sainte de Varanasi",
        "image": "https://images.pexels.com/photos/6045237/pexels-photo-6045237.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "price_range": "€150-€400/m", "min_order": "15 meters", "lead_time": "5-7 weeks"
    },
]

@api_router.get("/materials", response_model=List[Material])
async def get_materials(category: Optional[str] = None, region: Optional[str] = None):
    materials = MATERIALS
    if category:
        materials = [m for m in materials if m["category"] == category]
    if region:
        materials = [m for m in materials if m["region"].lower() == region.lower()]
    return materials

@api_router.get("/materials/{material_id}", response_model=Material)
async def get_material(material_id: str):
    for m in MATERIALS:
        if m["id"] == material_id:
            return m
    raise HTTPException(status_code=404, detail="Material not found")

@api_router.post("/quote/request")
async def request_quote(data: QuoteRequest, request: Request):
    quote_id = f"quote_{uuid.uuid4().hex[:12]}"
    user = await get_current_user(request)
    doc = {
        "quote_id": quote_id,
        **data.model_dump(),
        "user_id": user["user_id"] if user else None,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.quote_requests.insert_one(doc)
    return {"message": "Quote request submitted", "quote_id": quote_id}

# ==================== PRODUCTS (B2C) ====================

PRODUCTS = [
    {
        "id": "prod_001", "name": "Kundan Polki Necklace", "name_fr": "Collier Kundan Polki", "category": "jewelry",
        "price": 2800, "currency": "EUR",
        "description": "A regal statement piece featuring uncut diamonds set in 22k gold with enamel work",
        "description_fr": "Une pièce majestueuse avec des diamants bruts sertis dans de l'or 22 carats avec émaillage",
        "image": "https://images.pexels.com/photos/1395306/pexels-photo-1395306.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "images": [], "region": "Rajasthan", "artisan_cluster": "Jaipur Kundan Guild",
        "provenance": "Handcrafted by master artisans in Jaipur's walled city, using techniques passed down through 6 generations",
        "provenance_fr": "Fabriqué à la main par des maîtres artisans dans la vieille ville de Jaipur, utilisant des techniques transmises depuis 6 générations",
        "in_stock": True
    },
    {
        "id": "prod_002", "name": "Temple Earrings", "name_fr": "Boucles d'Oreilles Temple", "category": "jewelry",
        "price": 450, "currency": "EUR",
        "description": "South Indian temple-inspired earrings with ruby drops and gold plating",
        "description_fr": "Boucles d'oreilles inspirées des temples du sud de l'Inde avec gouttes de rubis et plaquage or",
        "image": "https://images.pexels.com/photos/1191531/pexels-photo-1191531.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "images": [], "region": "Tamil Nadu", "artisan_cluster": "Chennai Temple Jewellers",
        "provenance": "Created by third-generation goldsmiths who traditionally adorned temple deities",
        "provenance_fr": "Créé par des orfèvres de troisième génération qui ornaient traditionnellement les divinités des temples",
        "in_stock": True
    },
    {
        "id": "prod_003", "name": "Banarasi Silk Saree", "name_fr": "Saree en Soie de Bénarès", "category": "apparel",
        "price": 1200, "currency": "EUR",
        "description": "A resplendent red and gold Banarasi saree with traditional butis and intricate border",
        "description_fr": "Un magnifique saree rouge et or de Bénarès avec des butis traditionnels et une bordure complexe",
        "image": "https://images.pexels.com/photos/1066171/pexels-photo-1066171.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "images": [], "region": "Uttar Pradesh", "artisan_cluster": "Varanasi Handloom Weavers",
        "provenance": "Woven over 15 days by a family of weavers whose craft dates back to the Mughal era",
        "provenance_fr": "Tissé sur 15 jours par une famille de tisserands dont l'artisanat remonte à l'ère moghole",
        "in_stock": True
    },
    {
        "id": "prod_004", "name": "Pashmina Shawl", "name_fr": "Châle Pashmina", "category": "apparel",
        "price": 890, "currency": "EUR",
        "description": "Hand-embroidered pashmina with sozni needlework depicting chinar leaves",
        "description_fr": "Pashmina brodé à la main avec des broderies sozni représentant des feuilles de chinar",
        "image": "https://images.pexels.com/photos/6311641/pexels-photo-6311641.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "images": [], "region": "Kashmir", "artisan_cluster": "Srinagar Pashmina Artisans",
        "provenance": "Sourced from Changthang plateau goats and embroidered by Kashmiri women over 6 months",
        "provenance_fr": "Provenant des chèvres du plateau de Changthang et brodé par des femmes cachemiries pendant 6 mois",
        "in_stock": True
    },
    {
        "id": "prod_005", "name": "Dhurrie Carpet", "name_fr": "Tapis Dhurrie", "category": "carpets",
        "price": 650, "currency": "EUR",
        "description": "Hand-woven flatweave carpet with geometric patterns in natural dyes",
        "description_fr": "Tapis tissé à plat à la main avec des motifs géométriques en teintures naturelles",
        "image": "https://images.pexels.com/photos/6786956/pexels-photo-6786956.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "images": [], "region": "Rajasthan", "artisan_cluster": "Jodhpur Dhurrie Weavers",
        "provenance": "Woven by nomadic communities using traditional pit looms and vegetable dyes",
        "provenance_fr": "Tissé par des communautés nomades utilisant des métiers à fosses traditionnels et des teintures végétales",
        "in_stock": True
    },
    {
        "id": "prod_006", "name": "Kashmiri Silk Carpet", "name_fr": "Tapis en Soie du Cachemire", "category": "carpets",
        "price": 3500, "currency": "EUR",
        "description": "Hand-knotted silk carpet with 900 knots per square inch, featuring Persian-inspired floral motifs",
        "description_fr": "Tapis en soie noué à la main avec 900 nœuds par pouce carré, présentant des motifs floraux d'inspiration persane",
        "image": "https://images.pexels.com/photos/6786984/pexels-photo-6786984.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=650&w=940",
        "images": [], "region": "Kashmir", "artisan_cluster": "Srinagar Carpet Weavers Guild",
        "provenance": "Each carpet takes 18-24 months to complete by a family of master weavers",
        "provenance_fr": "Chaque tapis prend 18 à 24 mois à réaliser par une famille de maîtres tisserands",
        "in_stock": True
    },
]

@api_router.get("/products", response_model=List[Product])
async def get_products(category: Optional[str] = None, region: Optional[str] = None):
    products = PRODUCTS
    if category:
        products = [p for p in products if p["category"] == category]
    if region:
        products = [p for p in products if p["region"].lower() == region.lower()]
    return products

@api_router.get("/products/{product_id}", response_model=Product)
async def get_product(product_id: str):
    for p in PRODUCTS:
        if p["id"] == product_id:
            return p
    raise HTTPException(status_code=404, detail="Product not found")

# ==================== CONTACT ====================

@api_router.post("/contact")
async def submit_contact(data: ContactRequest):
    contact_id = f"contact_{uuid.uuid4().hex[:12]}"
    doc = {
        "contact_id": contact_id,
        **data.model_dump(),
        "status": "new",
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    await db.contact_messages.insert_one(doc)
    return {"message": "Message sent successfully", "contact_id": contact_id}

# ==================== REGIONS ====================

REGIONS = [
    {"id": "rajasthan", "name": "Rajasthan", "name_fr": "Rajasthan", "crafts": ["Block Prints", "Kundan Jewelry", "Dhurrie Carpets"]},
    {"id": "gujarat", "name": "Gujarat", "name_fr": "Gujarat", "crafts": ["Lab-Grown Diamonds", "Bandhani Textiles", "Patola Silk"]},
    {"id": "kashmir", "name": "Kashmir", "name_fr": "Cachemire", "crafts": ["Pashmina", "Silk Carpets", "Sapphires"]},
    {"id": "uttar_pradesh", "name": "Uttar Pradesh", "name_fr": "Uttar Pradesh", "crafts": ["Banarasi Silk", "Chikankari", "Brassware"]},
    {"id": "madhya_pradesh", "name": "Madhya Pradesh", "name_fr": "Madhya Pradesh", "crafts": ["Chanderi Silk", "Maheshwari Fabric"]},
    {"id": "tamil_nadu", "name": "Tamil Nadu", "name_fr": "Tamil Nadu", "crafts": ["Temple Jewelry", "Kanchipuram Silk", "Bronze Sculptures"]},
    {"id": "west_bengal", "name": "West Bengal", "name_fr": "Bengale-Occidental", "crafts": ["Baluchari Silk", "Dokra Metalwork", "Terracotta"]},
    {"id": "odisha", "name": "Odisha", "name_fr": "Odisha", "crafts": ["Pattachitra", "Sambalpuri Ikat", "Silver Filigree"]},
]

@api_router.get("/regions")
async def get_regions():
    return REGIONS

# ==================== HEALTH CHECK ====================

@api_router.get("/")
async def root():
    return {"message": "RASAA Atelier API", "status": "operational"}

@api_router.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat()}

# Include the router
app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
