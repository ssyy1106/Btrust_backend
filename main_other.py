import ssl
import xmlrpc.client
from typing import Optional, List, Dict
import base64
from io import BytesIO
import os
import urllib3

from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from pydantic import BaseModel
from PIL import Image

# Disable SSL verification for model downloads (fixes certificate errors)
# MUST be set BEFORE importing rembg
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''
os.environ['SSL_CERT_FILE'] = ''
os.environ['SSL_CERT_DIR'] = ''
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from rembg import remove

# ================= ODOO CONFIG ====================

ODOO_URL = "https://bos.btrust.intl"   # no /web at the end
ODOO_DB = "btrust"

# Attributes used
ATTR_BRAND = "Brand"
ATTR_SIZE = "Size"
ATTR_COUNTRY = "Country of Origin"
ATTR_REGULAR_PRICE = "Regular Price"

# ================= JWT CONFIG =====================

SECRET_KEY = "CHANGE_THIS_TO_A_RANDOM_SECRET"  # <--- change in real use
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 120

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login/verify")

# ================= XML-RPC CLIENTS =================

context = ssl._create_unverified_context()

common = xmlrpc.client.ServerProxy(
    f"{ODOO_URL}/xmlrpc/2/common/",
    context=context,
)
models = xmlrpc.client.ServerProxy(
    f"{ODOO_URL}/xmlrpc/2/object/",
    context=context,
)

# ================= FASTAPI APP =====================

app = FastAPI(title="BOS Product Updater API")

def download_model_with_ssl_disabled(model_name="u2net"):
    """Manually download rembg model with SSL verification disabled."""
    import urllib.request
    from pathlib import Path

    # Model URLs and file names
    model_info = {
        "u2net": {
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
            "filename": "u2net.onnx",
            "dir": ".u2net"
        },
        "u2netp": {
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
            "filename": "u2netp.onnx",
            "dir": ".u2net"
        },
        "u2net_human_seg": {
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx",
            "filename": "u2net_human_seg.onnx",
            "dir": ".u2net"
        },
        "isnet-general-use": {
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
            "filename": "isnet-general-use.onnx",
            "dir": ".u2net"
        }
    }

    if model_name not in model_info:
        print(f"Unknown model: {model_name}")
        return False

    info = model_info[model_name]
    model_dir = Path.home() / info["dir"]
    model_path = model_dir / info["filename"]

    # Check if model already exists
    if model_path.exists():
        print(f"Model {model_name} already exists at {model_path}")
        return True

    try:
        print(f"Downloading {model_name} from {info['url']}...")
        print(f"Saving to {model_path}...")

        # Create directory if it doesn't exist
        model_dir.mkdir(parents=True, exist_ok=True)

        # Create SSL context that doesn't verify certificates
        import ssl
        ssl_context = ssl._create_unverified_context()

        # Download the file
        with urllib.request.urlopen(info['url'], context=ssl_context) as response:
            total_size = int(response.headers.get('content-length', 0))
            print(f"Total size: {total_size / (1024*1024):.2f} MB")

            with open(model_path, 'wb') as out_file:
                chunk_size = 8192
                downloaded = 0
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\rDownloaded: {percent:.1f}%", end='', flush=True)

        print(f"\nModel {model_name} downloaded successfully to {model_path}")
        return True

    except Exception as e:
        print(f"Failed to download model {model_name}: {e}")
        return False

@app.on_event("startup")
async def startup_event():
    """Pre-load rembg model on startup to avoid SSL issues during requests."""
    try:
        print("Checking rembg model...")

        # First, try to manually download the model
        if download_model_with_ssl_disabled():
            print("Pre-loading rembg model...")
            from PIL import Image

            # Create a small test image to verify model works
            test_img = Image.new('RGB', (100, 100), color='white')

            # This should use the downloaded model
            remove(test_img)
            print("Rembg model loaded successfully!")
        else:
            print("Warning: Model download failed, will retry on first use")

    except Exception as e:
        print(f"Warning: Failed to pre-load rembg model: {e}")
        print("Model will be loaded on first use")

# ================= CORS MIDDLEWARE =================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://127.0.0.1:5173",  # Alternative localhost
        "http://172.16.10.63:5173",
        "https://localhost:5173",  # Vite dev server HTTPS
        "https://127.0.0.1:5173",  # Alternative localhost HTTPS
        "https://172.16.10.63:5173",  # Network IP HTTPS
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================= Pydantic MODELS =================


class LoginRequest(BaseModel):
    login: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    uid: int
    username: str
    name: Optional[str] = None


class ProductInfo(BaseModel):
    internal_ref: str
    barcode: str
    name_en: str
    name_zh_cn: str
    name_zh_tw: str
    brand_en: str
    brand_zh_cn: str
    brand_zh_tw: str
    size: str
    country_en: str
    country_zh_cn: str
    country_zh_tw: str
    regular_price: str


class ProductByBarcodeRequest(BaseModel):
    barcode: str


class ProductUpdateRequest(BaseModel):
    barcode: str
    internal_ref: Optional[str] = ""
    name_en: Optional[str] = ""
    name_zh_cn: Optional[str] = ""
    name_zh_tw: Optional[str] = ""
    brand_en: Optional[str] = ""
    brand_zh_cn: Optional[str] = ""
    brand_zh_tw: Optional[str] = ""
    size: Optional[str] = ""
    country_en: Optional[str] = ""
    country_zh_cn: Optional[str] = ""
    country_zh_tw: Optional[str] = ""
    regular_price: Optional[str] = ""


class BrandInfo(BaseModel):
    id: int
    name_en: str
    name_zh_cn: str
    name_zh_tw: str


class CountryInfo(BaseModel):
    id: int
    name_en: str
    name_zh_cn: str
    name_zh_tw: str


class UpdateResult(BaseModel):
    ok: bool


class ProductImageResponse(BaseModel):
    barcode: str
    image_base64: str  # Base64 encoded image


class ProductImageUpdateRequest(BaseModel):
    barcode: str
    image_base64: str  # Base64 encoded image (without data:image/... prefix)


class RemoveBackgroundRequest(BaseModel):
    image_base64: str  # Base64 encoded image (can include or exclude data URI prefix)
    model: Optional[str] = "u2net"  # AI model: u2net (default), u2netp (faster), u2net_human_seg (people), isnet-general-use, sam
    alpha_matting: Optional[bool] = True  # Enable alpha matting for detecting subtle edges (essential for light-colored objects)
    alpha_matting_foreground_threshold: Optional[int] = 210  # 0-255, LOWER values capture more subtle edges (good for light objects)
    alpha_matting_background_threshold: Optional[int] = 20  # 0-255, HIGHER values better separate light objects from background
    alpha_matting_erode_size: Optional[int] = 15  # Size of erosion, higher = smoother edges but may lose fine details
    post_process_mask: Optional[bool] = True  # Apply morphological operations to refine mask and sharpen edges


class RemoveBackgroundResponse(BaseModel):
    image_base64: str  # Base64 encoded PNG with transparent background


class BrandListQuery(BaseModel):
    attribute_name: Optional[str] = ATTR_BRAND


# ================= AUTH / JWT HELPERS ==============


def authenticate_odoo(login: str, password: str) -> int:
    """Return uid if login is valid, else 0/False."""
    try:
        uid = common.authenticate(ODOO_DB, login, password, {})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Odoo auth error: {e}")
    return uid or 0


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


class OdooUser(BaseModel):
    uid: int
    username: str
    password: str


def get_current_odoo_user(token: str = Depends(oauth2_scheme)) -> OdooUser:
    """Decode JWT and return Odoo user credentials from token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        password: str = payload.get("pwd")
        uid: int = payload.get("uid") or 0
        if not username or not password or not uid:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        return OdooUser(uid=uid, username=username, password=password)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ================= ODOO HELPERS ====================


def execute_kw(
    user: OdooUser,
    model: str,
    method: str,
    args: List,
    kwargs: Optional[Dict] = None,
):
    if kwargs is None:
        kwargs = {}
    try:
        return models.execute_kw(ODOO_DB, user.uid, user.password, model, method, args, kwargs)
    except xmlrpc.client.Fault as e:
        raise HTTPException(status_code=500, detail=f"Odoo error: {e}")


def get_product_info_by_barcode(user: OdooUser, barcode: str) -> ProductInfo:
    # Helper function to search by barcode
    def search_product(bc: str):
        return execute_kw(
            user,
            "product.template",
            "search_read",
            [[["barcode", "=", bc]]],
            {
                "fields": ["name", "attribute_line_ids", "barcode", "default_code"],
                "limit": 1,
                "context": {"lang": "en_US"},
            },
        )

    # Try 1: Pad with leading zeros to 14 digits
    barcode_padded = barcode.zfill(14)
    print(f"Searching barcode (padded to 14): {barcode_padded}")
    products_en = search_product(barcode_padded)

    # Try 2: If not found, remove last digit (checksum) and pad to 14 digits
    if not products_en:
        barcode_no_checksum = barcode[:-1].zfill(14)
        print(f"Not found. Trying without checksum (padded to 14): {barcode_no_checksum}")
        products_en = search_product(barcode_no_checksum)

    if not products_en:
        raise HTTPException(status_code=404, detail=f"Product not found for barcode: {barcode}")

    p_en = products_en[0]
    pid = p_en["id"]
    print(f"Found product ID: {pid} with barcode: {p_en.get('barcode')}")

    # 2) Get CN/TW names
    p_cn_list = execute_kw(
        user,
        "product.template",
        "search_read",
        [[["id", "=", pid]]],
        {"fields": ["name"], "context": {"lang": "zh_CN"}},
    )
    p_tw_list = execute_kw(
        user,
        "product.template",
        "search_read",
        [[["id", "=", pid]]],
        {"fields": ["name"], "context": {"lang": "zh_TW"}},
    )
    p_cn = p_cn_list[0] if p_cn_list else {}
    p_tw = p_tw_list[0] if p_tw_list else {}

    name_en = p_en.get("name") or ""
    name_zh_cn = p_cn.get("name") or ""
    name_zh_tw = p_tw.get("name") or ""
    internal_ref = p_en.get("default_code") or ""
    barcode_val = p_en.get("barcode") or ""

    # 3) Attributes
    attr_lines = execute_kw(
        user,
        "product.template.attribute.line",
        "search_read",
        [[["product_tmpl_id", "=", pid]]],
        {"fields": ["attribute_id", "value_ids"]},
    )

    if not attr_lines:
        return ProductInfo(
            internal_ref=internal_ref,
            barcode=barcode_val,
            name_en=name_en,
            name_zh_cn=name_zh_cn,
            name_zh_tw=name_zh_tw,
            brand_en="",
            brand_zh_cn="",
            brand_zh_tw="",
            size="",
            country_en="",
            country_zh_cn="",
            country_zh_tw="",
            regular_price="",
        )

    attr_ids = sorted({al["attribute_id"][0] for al in attr_lines if al["attribute_id"]})
    value_ids = sorted({vid for al in attr_lines for vid in al["value_ids"]})

    attributes = execute_kw(
        user,
        "product.attribute",
        "read",
        [attr_ids],
        {"fields": ["name"]},
    )
    attr_name_by_id = {a["id"]: a["name"] for a in attributes}

    vals_en = execute_kw(
        user,
        "product.attribute.value",
        "read",
        [value_ids],
        {"fields": ["name"], "context": {"lang": "en_US"}},
    )
    vals_cn = execute_kw(
        user,
        "product.attribute.value",
        "read",
        [value_ids],
        {"fields": ["name"], "context": {"lang": "zh_CN"}},
    )
    vals_tw = execute_kw(
        user,
        "product.attribute.value",
        "read",
        [value_ids],
        {"fields": ["name"], "context": {"lang": "zh_TW"}},
    )

    val_en_by_id = {v["id"]: v["name"] for v in vals_en}
    val_cn_by_id = {v["id"]: v["name"] for v in vals_cn}
    val_tw_by_id = {v["id"]: v["name"] for v in vals_tw}

    attrs_en = {}
    attrs_cn = {}
    attrs_tw = {}

    for al in attr_lines:
        attr_id = al["attribute_id"][0]
        attr_name = attr_name_by_id.get(attr_id, "")
        vals = al["value_ids"] or []
        if not attr_name:
            continue
        vals_en_str = ", ".join(val_en_by_id.get(v, "") for v in vals)
        vals_cn_str = ", ".join(val_cn_by_id.get(v, "") for v in vals)
        vals_tw_str = ", ".join(val_tw_by_id.get(v, "") for v in vals)

        attrs_en[attr_name] = vals_en_str
        attrs_cn[attr_name] = vals_cn_str
        attrs_tw[attr_name] = vals_tw_str

    return ProductInfo(
        internal_ref=internal_ref,
        barcode=barcode_val,
        name_en=name_en,
        name_zh_cn=name_zh_cn,
        name_zh_tw=name_zh_tw,
        brand_en=attrs_en.get(ATTR_BRAND, ""),
        brand_zh_cn=attrs_cn.get(ATTR_BRAND, ""),
        brand_zh_tw=attrs_tw.get(ATTR_BRAND, ""),
        size=attrs_en.get(ATTR_SIZE, ""),
        country_en=attrs_en.get(ATTR_COUNTRY, ""),
        country_zh_cn=attrs_cn.get(ATTR_COUNTRY, ""),
        country_zh_tw=attrs_tw.get(ATTR_COUNTRY, ""),
        regular_price=attrs_en.get(ATTR_REGULAR_PRICE, ""),
    )


def ensure_attribute(user: OdooUser, attr_name: str) -> int:
    ids = execute_kw(
        user,
        "product.attribute",
        "search",
        [[["name", "=", attr_name]]],
    )
    if ids:
        return ids[0]
    return execute_kw(
        user,
        "product.attribute",
        "create",
        [[{"name": attr_name}]],
    )


def ensure_attribute_value(
    user: OdooUser,
    attr_id: int,
    value_en: str,
    brand_translations: Optional[Dict[str, str]] = None,
) -> Optional[int]:
    if not value_en:
        return None

    ids = execute_kw(
        user,
        "product.attribute.value",
        "search",
        [[["attribute_id", "=", attr_id], ["name", "=", value_en]]],
    )
    if ids:
        val_id = ids[0]
    else:
        val_id = execute_kw(
            user,
            "product.attribute.value",
            "create",
            [[{"name": value_en, "attribute_id": attr_id}]],
        )

    if brand_translations:
        for lang_code, trans_name in brand_translations.items():
            if not trans_name:
                continue
            execute_kw(
                user,
                "product.attribute.value",
                "write",
                [[val_id], {"name": trans_name}],
                {"context": {"lang": lang_code}},
            )

    return val_id


def remove_attribute_line(
    user: OdooUser,
    product_id: int,
    attr_name: str,
):
    """Remove an attribute line from a product (unlink the attribute)."""
    print(f"  -> Attempting to remove attribute '{attr_name}' from product {product_id}")

    attr_ids = execute_kw(
        user,
        "product.attribute",
        "search",
        [[["name", "=", attr_name]]],
    )
    if not attr_ids:
        print(f"  -> Attribute '{attr_name}' not found in Odoo")
        return  # Attribute doesn't exist, nothing to remove

    attr_id = attr_ids[0]
    print(f"  -> Found attribute ID: {attr_id}")

    # Find and delete the attribute line
    line_ids = execute_kw(
        user,
        "product.template.attribute.line",
        "search",
        [[["product_tmpl_id", "=", product_id], ["attribute_id", "=", attr_id]]],
        {"limit": 1},
    )
    print(f"  -> Found attribute line IDs to remove: {line_ids}")

    if line_ids:
        execute_kw(
            user,
            "product.template.attribute.line",
            "unlink",
            [line_ids],
        )
        print(f"  -> Successfully removed attribute line {line_ids}")
    else:
        print(f"  -> No attribute line found to remove")


def set_attribute_line(
    user: OdooUser,
    product_id: int,
    attr_name: str,
    value_en: str,
    value_zh_cn: str = "",
    value_zh_tw: str = "",
):
    if not value_en:
        return

    attr_id = ensure_attribute(user, attr_name)

    # Save translations for Brand and Country attributes
    translations = None
    if attr_name in (ATTR_BRAND, ATTR_COUNTRY):
        translations = {
            "zh_CN": value_zh_cn or "",
            "zh_TW": value_zh_tw or "",
        }

    val_id = ensure_attribute_value(
        user,
        attr_id,
        value_en,
        brand_translations=translations,
    )
    if not val_id:
        return

    line_ids = execute_kw(
        user,
        "product.template.attribute.line",
        "search",
        [[["product_tmpl_id", "=", product_id], ["attribute_id", "=", attr_id]]],
        {"limit": 1},
    )
    if line_ids:
        execute_kw(
            user,
            "product.template.attribute.line",
            "write",
            [[line_ids[0]], {"value_ids": [(6, 0, [val_id])]}],
        )
    else:
        execute_kw(
            user,
            "product.template.attribute.line",
            "create",
            [[
                {
                    "product_tmpl_id": product_id,
                    "attribute_id": attr_id,
                    "value_ids": [(6, 0, [val_id])],
                }
            ]],
        )


# ================= API ENDPOINTS ===================

@app.post("/api/login/verify", response_model=LoginResponse)
def verify_login(req: LoginRequest):
    """
    1) Verify the Odoo login account is valid and return JWT token.
    """
    print(f"=== Login attempt ===")
    print(f"Login: {req.login}")
    print(f"Password length: {len(req.password) if req.password else 0}")

    uid = authenticate_odoo(req.login, req.password)
    print(f"Odoo returned UID: {uid}")

    if not uid:
        raise HTTPException(status_code=401, detail="Invalid Odoo credentials")

    # optional: get user name
    user_data = models.execute_kw(
        ODOO_DB, uid, req.password,
        "res.users", "read",
        [[uid]],
        {"fields": ["name"]},
    )[0]
    name = user_data.get("name", "")

    token_data = {
        "sub": req.login,
        "uid": uid,
        "pwd": req.password,
    }
    access_token = create_access_token(token_data)

    return LoginResponse(
        access_token=access_token,
        uid=uid,
        username=req.login,
        name=name,
    )


@app.post("/api/product/by-barcode", response_model=ProductInfo)
def product_by_barcode(
    body: ProductByBarcodeRequest,
    user: OdooUser = Depends(get_current_odoo_user),
):
    """
    2) Using the barcode to search the item and return:
       Internal Ref, Barcode, Name EN/ZH_CN/ZH_TW,
       Brand EN/ZH_CN/ZH_TW, Size, Country, Regular Price.
    """
    return get_product_info_by_barcode(user, body.barcode)


@app.post("/api/product/update", response_model=UpdateResult)
def update_product(
    body: ProductUpdateRequest,
    user: OdooUser = Depends(get_current_odoo_user),
):
    """
    3) Update fields (found by barcode):
       Internal Ref, Name EN/ZH_CN/ZH_TW,
       Brand EN/ZH_CN/ZH_TW, Size, Country, Regular Price.
    """
    # Debug logging
    print("=== Received Update Request ===")
    print(f"size: '{body.size}' (empty: {not body.size})")
    print(f"country: '{body.country}' (empty: {not body.country})")
    print(f"brand_en: '{body.brand_en}' (empty: {not body.brand_en})")
    print(f"regular_price: '{body.regular_price}' (empty: {not body.regular_price})")

    # Find product by barcode
    products = execute_kw(
        user,
        "product.template",
        "search_read",
        [[["barcode", "=", body.barcode]]],
        {"fields": ["name"], "limit": 1},
    )
    if not products:
        raise HTTPException(status_code=404, detail="Product not found for this barcode")

    pid = products[0]["id"]

    # 1) Basic fields
    vals_basic = {
        "default_code": body.internal_ref or False,
    }
    execute_kw(
        user,
        "product.template",
        "write",
        [[pid], vals_basic],
    )

    # 2) Names in 3 languages
    if body.name_en:
        execute_kw(
            user,
            "product.template",
            "write",
            [[pid], {"name": body.name_en}],
            {"context": {"lang": "en_US"}},
        )
    if body.name_zh_cn:
        execute_kw(
            user,
            "product.template",
            "write",
            [[pid], {"name": body.name_zh_cn}],
            {"context": {"lang": "zh_CN"}},
        )
    if body.name_zh_tw:
        execute_kw(
            user,
            "product.template",
            "write",
            [[pid], {"name": body.name_zh_tw}],
            {"context": {"lang": "zh_TW"}},
        )

    # 3) Attributes - set or remove based on whether value is provided
    if body.brand_en:
        set_attribute_line(
            user,
            pid,
            ATTR_BRAND,
            body.brand_en,
            value_zh_cn=body.brand_zh_cn or "",
            value_zh_tw=body.brand_zh_tw or "",
        )
    else:
        # Remove brand attribute if cleared
        remove_attribute_line(user, pid, ATTR_BRAND)

    if body.size:
        set_attribute_line(
            user,
            pid,
            ATTR_SIZE,
            body.size,
        )
    else:
        # Remove size attribute if cleared
        remove_attribute_line(user, pid, ATTR_SIZE)

    if body.country_en:
        set_attribute_line(
            user,
            pid,
            ATTR_COUNTRY,
            body.country_en,
            value_zh_cn=body.country_zh_cn or "",
            value_zh_tw=body.country_zh_tw or "",
        )
    else:
        # Remove country attribute if cleared
        remove_attribute_line(user, pid, ATTR_COUNTRY)

    if body.regular_price:
        set_attribute_line(
            user,
            pid,
            ATTR_REGULAR_PRICE,
            body.regular_price,
        )
    else:
        # Remove regular_price attribute if cleared
        remove_attribute_line(user, pid, ATTR_REGULAR_PRICE)

    return UpdateResult(ok=True)


@app.get("/api/brands", response_model=List[BrandInfo])
def get_brands(
    attribute_name: str = ATTR_BRAND,
    user: OdooUser = Depends(get_current_odoo_user),
):
    """
    4) Get all Brand names (for dropdown):
       returns id + name in EN, ZH_CN, ZH_TW.
    """
    attr_ids = execute_kw(
        user,
        "product.attribute",
        "search",
        [[["name", "=", attribute_name]]],
    )
    if not attr_ids:
        return []

    attr_id = attr_ids[0]

    vals_en = execute_kw(
        user,
        "product.attribute.value",
        "search_read",
        [[["attribute_id", "=", attr_id]]],
        {"fields": ["name"], "context": {"lang": "en_US"}},
    )
    ids = [v["id"] for v in vals_en]

    vals_cn = execute_kw(
        user,
        "product.attribute.value",
        "read",
        [ids],
        {"fields": ["name"], "context": {"lang": "zh_CN"}},
    )
    vals_tw = execute_kw(
        user,
        "product.attribute.value",
        "read",
        [ids],
        {"fields": ["name"], "context": {"lang": "zh_TW"}},
    )

    by_cn = {v["id"]: v["name"] for v in vals_cn}
    by_tw = {v["id"]: v["name"] for v in vals_tw}

    result: List[BrandInfo] = []
    for v in vals_en:
        vid = v["id"]
        result.append(
            BrandInfo(
                id=vid,
                name_en=v["name"] or "",
                name_zh_cn=by_cn.get(vid, "") or "",
                name_zh_tw=by_tw.get(vid, "") or "",
            )
        )
    return result


@app.get("/api/countries", response_model=List[CountryInfo])
def get_countries(
    user: OdooUser = Depends(get_current_odoo_user),
):
    """
    5) Get all Country of Origin names (for dropdown):
       returns id + name in EN, ZH_CN, ZH_TW.
    """
    attr_ids = execute_kw(
        user,
        "product.attribute",
        "search",
        [[["name", "=", ATTR_COUNTRY]]],
    )
    if not attr_ids:
        return []

    attr_id = attr_ids[0]

    vals_en = execute_kw(
        user,
        "product.attribute.value",
        "search_read",
        [[["attribute_id", "=", attr_id]]],
        {"fields": ["name"], "context": {"lang": "en_US"}},
    )
    ids = [v["id"] for v in vals_en]

    vals_cn = execute_kw(
        user,
        "product.attribute.value",
        "read",
        [ids],
        {"fields": ["name"], "context": {"lang": "zh_CN"}},
    )
    vals_tw = execute_kw(
        user,
        "product.attribute.value",
        "read",
        [ids],
        {"fields": ["name"], "context": {"lang": "zh_TW"}},
    )

    by_cn = {v["id"]: v["name"] for v in vals_cn}
    by_tw = {v["id"]: v["name"] for v in vals_tw}

    result: List[CountryInfo] = []
    for v in vals_en:
        vid = v["id"]
        result.append(
            CountryInfo(
                id=vid,
                name_en=v["name"] or "",
                name_zh_cn=by_cn.get(vid, "") or "",
                name_zh_tw=by_tw.get(vid, "") or "",
            )
        )
    return result


@app.post("/api/product/image", response_model=ProductImageResponse)
def get_product_image(
    body: ProductByBarcodeRequest,
    user: OdooUser = Depends(get_current_odoo_user),
):
    """
    6) Get product image by barcode (returns base64).
    """
    # Use the same fallback logic as product search
    def search_product(bc: str):
        return execute_kw(
            user,
            "product.template",
            "search_read",
            [[["barcode", "=", bc]]],
            {
                "fields": ["barcode", "image_1920"],
                "limit": 1,
            },
        )

    # Try 1: Pad with leading zeros to 14 digits
    barcode_padded = body.barcode.zfill(14)
    products = search_product(barcode_padded)

    # Try 2: If not found, remove last digit (checksum) and pad to 14 digits
    if not products:
        barcode_no_checksum = body.barcode[:-1].zfill(14)
        products = search_product(barcode_no_checksum)

    if not products:
        raise HTTPException(status_code=404, detail="Product not found for this barcode")

    product = products[0]
    image_data = product.get("image_1920") or ""

    return ProductImageResponse(
        barcode=product.get("barcode") or "",
        image_base64=image_data,
    )


@app.post("/api/product/image/update", response_model=UpdateResult)
def update_product_image(
    body: ProductImageUpdateRequest,
    user: OdooUser = Depends(get_current_odoo_user),
):
    """
    7) Update product image by barcode.
    """
    # Find product by barcode (with fallback logic)
    def search_product(bc: str):
        return execute_kw(
            user,
            "product.template",
            "search_read",
            [[["barcode", "=", bc]]],
            {
                "fields": ["id"],
                "limit": 1,
            },
        )

    barcode_padded = body.barcode.zfill(14)
    products = search_product(barcode_padded)

    if not products:
        barcode_no_checksum = body.barcode[:-1].zfill(14)
        products = search_product(barcode_no_checksum)

    if not products:
        raise HTTPException(status_code=404, detail="Product not found for this barcode")

    pid = products[0]["id"]

    # Update the image
    execute_kw(
        user,
        "product.template",
        "write",
        [[pid], {"image_1920": body.image_base64}],
    )

    return UpdateResult(ok=True)


@app.post("/api/image/remove-background", response_model=RemoveBackgroundResponse)
def remove_background_endpoint(
    body: RemoveBackgroundRequest,
    user: OdooUser = Depends(get_current_odoo_user),
):
    """
    8) Remove background from image using rembg AI with customizable parameters.

    Models:
    - u2net: General purpose (default, best quality)
    - u2netp: Faster, smaller model
    - u2net_human_seg: Optimized for people/portraits
    - isnet-general-use: Good for general objects, excellent edge quality

    Optimized for LIGHT-COLORED OBJECTS:
    - Default settings now tuned for white/light products
    - Alpha matting ENABLED (essential for detecting subtle edges on light objects)
    - Foreground threshold LOWERED to 210 (captures more subtle edges)
    - Background threshold RAISED to 20 (better separates light objects)

    Troubleshooting:
    - Light object edges not detected: LOWER foreground_threshold (180-200)
    - Removing too much of light object: INCREASE foreground_threshold (220-240)
    - Background not fully removed: LOWER background_threshold (5-15)
    - Edges too rough: INCREASE alpha_matting_erode_size (20-25)
    - Edges too blurry: DECREASE alpha_matting_erode_size (10-12)
    - Dark objects: INCREASE foreground_threshold (230-250), DECREASE background_threshold (5-10)
    - Try isnet-general-use model for better edge detection on products
    """
    try:
        from rembg import remove, new_session

        # Decode base64 image
        image_data = body.image_base64

        # Remove data URI prefix if present
        if image_data.startswith("data:image"):
            image_data = image_data.split(",")[1]

        # Decode base64 to bytes
        image_bytes = base64.b64decode(image_data)

        # Open image with PIL
        input_image = Image.open(BytesIO(image_bytes))

        # Create session with selected model
        print(f"Removing background with model: {body.model}")
        print(f"Alpha matting: {body.alpha_matting}")
        print(f"Foreground threshold: {body.alpha_matting_foreground_threshold}")
        print(f"Background threshold: {body.alpha_matting_background_threshold}")

        session = new_session(body.model)

        # Remove background with custom parameters
        output_image = remove(
            input_image,
            session=session,
            alpha_matting=body.alpha_matting,
            alpha_matting_foreground_threshold=body.alpha_matting_foreground_threshold,
            alpha_matting_background_threshold=body.alpha_matting_background_threshold,
            alpha_matting_erode_size=body.alpha_matting_erode_size,
            post_process_mask=body.post_process_mask,
        )

        # Convert to bytes (PNG format to preserve transparency)
        output_buffer = BytesIO()
        output_image.save(output_buffer, format="PNG")
        output_bytes = output_buffer.getvalue()

        # Encode to base64
        output_base64 = base64.b64encode(output_bytes).decode("utf-8")

        print("Background removed successfully")
        return RemoveBackgroundResponse(image_base64=output_base64)

    except Exception as e:
        import traceback
        print(f"Error removing background: {e}")
        print(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Background removal failed: {str(e)}")


# ================= SERVER STARTUP ==================

if __name__ == "__main__":
    import uvicorn

    # For HTTPS, you need SSL certificates
    # Generate self-signed certs with:
    # openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        ssl_keyfile="key.pem",      # Path to SSL private key
        ssl_certfile="cert.pem",    # Path to SSL certificate
    )
