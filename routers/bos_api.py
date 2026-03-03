import base64
import os
import ssl
import urllib.request
import urllib3
import xmlrpc.client
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from PIL import Image
from pydantic import BaseModel

from helper import getOdooAccount

# Disable SSL verification for rembg model downloads
ssl._create_default_https_context = ssl._create_unverified_context
os.environ["CURL_CA_BUNDLE"] = ""
os.environ["REQUESTS_CA_BUNDLE"] = ""
os.environ["SSL_CERT_FILE"] = ""
os.environ["SSL_CERT_DIR"] = ""
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

ODOO_URL = ""
ODOO_DB = ""
context = None
common = None
models = None


def init_odoo():
    global ODOO_URL, ODOO_DB, context, common, models
    try:
        _odoo_host, _odoo_user, _odoo_pwd, _odoo_db = getOdooAccount()
        ODOO_URL = _odoo_host.rstrip("/")
        ODOO_DB = _odoo_db
        context = ssl._create_unverified_context()
        common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common/", context=context)
        models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object/", context=context)
    except Exception:
        ODOO_URL = os.getenv("ODOO_XMLRPC_URL", "https://bos.btrust.intl").rstrip("/")
        ODOO_DB = os.getenv("ODOO_DB", "btrust")
        context = ssl._create_unverified_context()
        common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common/", context=context)
        models = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/object/", context=context)

ATTR_BRAND = "Brand"
ATTR_SIZE = "Size"
ATTR_COUNTRY = "Country of Origin"
ATTR_REGULAR_PRICE = "Regular Price"

SECRET_KEY = os.getenv("BOS_API_SECRET_KEY", "CHANGE_THIS_TO_A_RANDOM_SECRET")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("BOS_API_TOKEN_EXPIRE_MINUTES", "120"))

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login/verify")

router = APIRouter(tags=["BOS"])


def download_model_with_ssl_disabled(model_name: str = "u2net") -> bool:
    model_info = {
        "u2net": {
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
            "filename": "u2net.onnx",
            "dir": ".u2net",
        },
        "u2netp": {
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2netp.onnx",
            "filename": "u2netp.onnx",
            "dir": ".u2net",
        },
        "u2net_human_seg": {
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net_human_seg.onnx",
            "filename": "u2net_human_seg.onnx",
            "dir": ".u2net",
        },
        "isnet-general-use": {
            "url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx",
            "filename": "isnet-general-use.onnx",
            "dir": ".u2net",
        },
    }

    if model_name not in model_info:
        return False

    info = model_info[model_name]
    model_dir = Path.home() / info["dir"]
    model_path = model_dir / info["filename"]

    if model_path.exists():
        return True

    try:
        model_dir.mkdir(parents=True, exist_ok=True)
        ssl_context = ssl._create_unverified_context()
        with urllib.request.urlopen(info["url"], context=ssl_context) as response:
            with open(model_path, "wb") as out_file:
                chunk_size = 8192
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    out_file.write(chunk)
        return True
    except Exception:
        return False


@router.on_event("startup")
async def startup_event():
    try:
        if download_model_with_ssl_disabled():
            from rembg import remove

            test_img = Image.new("RGB", (16, 16), color="white")
            remove(test_img)
    except Exception:
        pass


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
    image_base64: str


class ProductImageUpdateRequest(BaseModel):
    barcode: str
    image_base64: str


class RemoveBackgroundRequest(BaseModel):
    image_base64: str
    model: Optional[str] = "u2net"
    alpha_matting: Optional[bool] = True
    alpha_matting_foreground_threshold: Optional[int] = 210
    alpha_matting_background_threshold: Optional[int] = 20
    alpha_matting_erode_size: Optional[int] = 15
    post_process_mask: Optional[bool] = True


class RemoveBackgroundResponse(BaseModel):
    image_base64: str


class BrandListQuery(BaseModel):
    attribute_name: Optional[str] = ATTR_BRAND


class OdooUser(BaseModel):
    uid: int
    username: str
    password: str


def authenticate_odoo(login: str, password: str) -> int:
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


def get_current_odoo_user(token: str = Depends(oauth2_scheme)) -> OdooUser:
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


def execute_kw(user: OdooUser, model: str, method: str, args: List, kwargs: Optional[Dict] = None):
    if kwargs is None:
        kwargs = {}
    try:
        return models.execute_kw(ODOO_DB, user.uid, user.password, model, method, args, kwargs)
    except xmlrpc.client.Fault as e:
        raise HTTPException(status_code=500, detail=f"Odoo error: {e}")


def get_product_info_by_barcode(user: OdooUser, barcode: str) -> ProductInfo:
    def search_product(bc: str):
        return execute_kw(
            user,
            "product.template",
            "search_read",
            [[["barcode", "=", bc]]],
            {"fields": ["name", "attribute_line_ids", "barcode", "default_code"], "limit": 1, "context": {"lang": "en_US"}},
        )

    barcode_padded = barcode.zfill(14)
    products_en = search_product(barcode_padded)

    if not products_en:
        barcode_no_checksum = barcode[:-1].zfill(14)
        products_en = search_product(barcode_no_checksum)

    if not products_en:
        raise HTTPException(status_code=404, detail=f"Product not found for barcode: {barcode}")

    p_en = products_en[0]
    pid = p_en["id"]

    p_cn_list = execute_kw(
        user, "product.template", "search_read", [[["id", "=", pid]]], {"fields": ["name"], "context": {"lang": "zh_CN"}}
    )
    p_tw_list = execute_kw(
        user, "product.template", "search_read", [[["id", "=", pid]]], {"fields": ["name"], "context": {"lang": "zh_TW"}}
    )
    p_cn = p_cn_list[0] if p_cn_list else {}
    p_tw = p_tw_list[0] if p_tw_list else {}

    name_en = p_en.get("name") or ""
    name_zh_cn = p_cn.get("name") or ""
    name_zh_tw = p_tw.get("name") or ""
    internal_ref = p_en.get("default_code") or ""
    barcode_val = p_en.get("barcode") or ""

    attr_lines = execute_kw(
        user, "product.template.attribute.line", "search_read", [[["product_tmpl_id", "=", pid]]], {"fields": ["attribute_id", "value_ids"]}
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

    attributes = execute_kw(user, "product.attribute", "read", [attr_ids], {"fields": ["name"]})
    attr_name_by_id = {a["id"]: a["name"] for a in attributes}

    vals_en = execute_kw(user, "product.attribute.value", "read", [value_ids], {"fields": ["name"], "context": {"lang": "en_US"}})
    vals_cn = execute_kw(user, "product.attribute.value", "read", [value_ids], {"fields": ["name"], "context": {"lang": "zh_CN"}})
    vals_tw = execute_kw(user, "product.attribute.value", "read", [value_ids], {"fields": ["name"], "context": {"lang": "zh_TW"}})

    val_en_by_id = {v["id"]: v["name"] for v in vals_en}
    val_cn_by_id = {v["id"]: v["name"] for v in vals_cn}
    val_tw_by_id = {v["id"]: v["name"] for v in vals_tw}

    attrs_en: Dict[str, str] = {}
    attrs_cn: Dict[str, str] = {}
    attrs_tw: Dict[str, str] = {}

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
    ids = execute_kw(user, "product.attribute", "search", [[["name", "=", attr_name]]])
    if ids:
        return ids[0]
    return execute_kw(user, "product.attribute", "create", [[{"name": attr_name}]])


def ensure_attribute_value(user: OdooUser, attr_id: int, value_en: str, translations: Optional[Dict[str, str]] = None) -> Optional[int]:
    if not value_en:
        return None

    ids = execute_kw(user, "product.attribute.value", "search", [[["attribute_id", "=", attr_id], ["name", "=", value_en]]])
    if ids:
        val_id = ids[0]
    else:
        val_id = execute_kw(user, "product.attribute.value", "create", [[{"name": value_en, "attribute_id": attr_id}]])

    if translations:
        for lang_code, trans_name in translations.items():
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


def remove_attribute_line(user: OdooUser, product_id: int, attr_name: str):
    attr_ids = execute_kw(user, "product.attribute", "search", [[["name", "=", attr_name]]])
    if not attr_ids:
        return

    attr_id = attr_ids[0]
    line_ids = execute_kw(
        user, "product.template.attribute.line", "search", [[["product_tmpl_id", "=", product_id], ["attribute_id", "=", attr_id]]], {"limit": 1}
    )
    if line_ids:
        execute_kw(user, "product.template.attribute.line", "unlink", [line_ids])


def set_attribute_line(user: OdooUser, product_id: int, attr_name: str, value_en: str, value_zh_cn: str = "", value_zh_tw: str = ""):
    if not value_en:
        return

    attr_id = ensure_attribute(user, attr_name)
    translations = None
    if attr_name in (ATTR_BRAND, ATTR_COUNTRY):
        translations = {"zh_CN": value_zh_cn or "", "zh_TW": value_zh_tw or ""}

    val_id = ensure_attribute_value(user, attr_id, value_en, translations=translations)
    if not val_id:
        return

    line_ids = execute_kw(
        user, "product.template.attribute.line", "search", [[["product_tmpl_id", "=", product_id], ["attribute_id", "=", attr_id]]], {"limit": 1}
    )
    if line_ids:
        execute_kw(user, "product.template.attribute.line", "write", [[line_ids[0]], {"value_ids": [(6, 0, [val_id])]}])
    else:
        execute_kw(
            user,
            "product.template.attribute.line",
            "create",
            [[{"product_tmpl_id": product_id, "attribute_id": attr_id, "value_ids": [(6, 0, [val_id])]}]],
        )


@router.post("/api/login/verify", response_model=LoginResponse)
def verify_login(req: LoginRequest):
    uid = authenticate_odoo(req.login, req.password)
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid Odoo credentials")

    user_data = models.execute_kw(
        ODOO_DB, uid, req.password, "res.users", "read", [[uid]], {"fields": ["name"]},
    )[0]
    name = user_data.get("name", "")

    token_data = {"sub": req.login, "uid": uid, "pwd": req.password}
    access_token = create_access_token(token_data)

    return LoginResponse(access_token=access_token, uid=uid, username=req.login, name=name)


@router.post("/api/product/by-barcode", response_model=ProductInfo)
def product_by_barcode(body: ProductByBarcodeRequest, user: OdooUser = Depends(get_current_odoo_user)):
    return get_product_info_by_barcode(user, body.barcode)


@router.post("/api/product/update", response_model=UpdateResult)
def update_product(body: ProductUpdateRequest, user: OdooUser = Depends(get_current_odoo_user)):
    products = execute_kw(user, "product.template", "search_read", [[["barcode", "=", body.barcode]]], {"fields": ["name"], "limit": 1})
    if not products:
        raise HTTPException(status_code=404, detail="Product not found for this barcode")

    pid = products[0]["id"]
    vals_basic = {"default_code": body.internal_ref or False}
    execute_kw(user, "product.template", "write", [[pid], vals_basic])

    if body.name_en:
        execute_kw(user, "product.template", "write", [[pid], {"name": body.name_en}], {"context": {"lang": "en_US"}})
    if body.name_zh_cn:
        execute_kw(user, "product.template", "write", [[pid], {"name": body.name_zh_cn}], {"context": {"lang": "zh_CN"}})
    if body.name_zh_tw:
        execute_kw(user, "product.template", "write", [[pid], {"name": body.name_zh_tw}], {"context": {"lang": "zh_TW"}})

    if body.brand_en:
        set_attribute_line(user, pid, ATTR_BRAND, body.brand_en, value_zh_cn=body.brand_zh_cn or "", value_zh_tw=body.brand_zh_tw or "")
    else:
        remove_attribute_line(user, pid, ATTR_BRAND)

    if body.size:
        set_attribute_line(user, pid, ATTR_SIZE, body.size)
    else:
        remove_attribute_line(user, pid, ATTR_SIZE)

    if body.country_en:
        set_attribute_line(user, pid, ATTR_COUNTRY, body.country_en, value_zh_cn=body.country_zh_cn or "", value_zh_tw=body.country_zh_tw or "")
    else:
        remove_attribute_line(user, pid, ATTR_COUNTRY)

    if body.regular_price:
        set_attribute_line(user, pid, ATTR_REGULAR_PRICE, body.regular_price)
    else:
        remove_attribute_line(user, pid, ATTR_REGULAR_PRICE)

    return UpdateResult(ok=True)


@router.get("/api/brands", response_model=List[BrandInfo])
def get_brands(attribute_name: str = ATTR_BRAND, user: OdooUser = Depends(get_current_odoo_user)):
    attr_ids = execute_kw(user, "product.attribute", "search", [[["name", "=", attribute_name]]])
    if not attr_ids:
        return []

    attr_id = attr_ids[0]
    vals_en = execute_kw(
        user, "product.attribute.value", "search_read", [[["attribute_id", "=", attr_id]]], {"fields": ["name"], "context": {"lang": "en_US"}}
    )
    ids = [v["id"] for v in vals_en]

    vals_cn = execute_kw(user, "product.attribute.value", "read", [ids], {"fields": ["name"], "context": {"lang": "zh_CN"}})
    vals_tw = execute_kw(user, "product.attribute.value", "read", [ids], {"fields": ["name"], "context": {"lang": "zh_TW"}})

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


@router.get("/api/countries", response_model=List[CountryInfo])
def get_countries(user: OdooUser = Depends(get_current_odoo_user)):
    attr_ids = execute_kw(user, "product.attribute", "search", [[["name", "=", ATTR_COUNTRY]]])
    if not attr_ids:
        return []

    attr_id = attr_ids[0]
    vals_en = execute_kw(
        user, "product.attribute.value", "search_read", [[["attribute_id", "=", attr_id]]], {"fields": ["name"], "context": {"lang": "en_US"}}
    )
    ids = [v["id"] for v in vals_en]

    vals_cn = execute_kw(user, "product.attribute.value", "read", [ids], {"fields": ["name"], "context": {"lang": "zh_CN"}})
    vals_tw = execute_kw(user, "product.attribute.value", "read", [ids], {"fields": ["name"], "context": {"lang": "zh_TW"}})

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


@router.post("/api/product/image", response_model=ProductImageResponse)
def get_product_image(body: ProductByBarcodeRequest, user: OdooUser = Depends(get_current_odoo_user)):
    def search_product(bc: str):
        return execute_kw(user, "product.template", "search_read", [[["barcode", "=", bc]]], {"fields": ["barcode", "image_1920"], "limit": 1})

    barcode_padded = body.barcode.zfill(14)
    products = search_product(barcode_padded)

    if not products:
        barcode_no_checksum = body.barcode[:-1].zfill(14)
        products = search_product(barcode_no_checksum)

    if not products:
        raise HTTPException(status_code=404, detail="Product not found for this barcode")

    product = products[0]
    image_data = product.get("image_1920") or ""

    return ProductImageResponse(barcode=product.get("barcode") or "", image_base64=image_data)


@router.post("/api/product/image/update", response_model=UpdateResult)
def update_product_image(body: ProductImageUpdateRequest, user: OdooUser = Depends(get_current_odoo_user)):
    def search_product(bc: str):
        return execute_kw(user, "product.template", "search_read", [[["barcode", "=", bc]]], {"fields": ["id"], "limit": 1})

    barcode_padded = body.barcode.zfill(14)
    products = search_product(barcode_padded)

    if not products:
        barcode_no_checksum = body.barcode[:-1].zfill(14)
        products = search_product(barcode_no_checksum)

    if not products:
        raise HTTPException(status_code=404, detail="Product not found for this barcode")

    pid = products[0]["id"]
    execute_kw(user, "product.template", "write", [[pid], {"image_1920": body.image_base64}])

    return UpdateResult(ok=True)


@router.post("/api/image/remove-background", response_model=RemoveBackgroundResponse)
def remove_background_endpoint(body: RemoveBackgroundRequest, user: OdooUser = Depends(get_current_odoo_user)):
    try:
        from rembg import new_session, remove

        image_data = body.image_base64
        if image_data.startswith("data:image"):
            image_data = image_data.split(",", 1)[1]

        image_bytes = base64.b64decode(image_data)
        input_image = Image.open(BytesIO(image_bytes))

        session = new_session(body.model)
        output_image = remove(
            input_image,
            session=session,
            alpha_matting=body.alpha_matting,
            alpha_matting_foreground_threshold=body.alpha_matting_foreground_threshold,
            alpha_matting_background_threshold=body.alpha_matting_background_threshold,
            alpha_matting_erode_size=body.alpha_matting_erode_size,
            post_process_mask=body.post_process_mask,
        )

        output_buffer = BytesIO()
        output_image.save(output_buffer, format="PNG")
        output_bytes = output_buffer.getvalue()
        output_base64 = base64.b64encode(output_bytes).decode("utf-8")

        return RemoveBackgroundResponse(image_base64=output_base64)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Background removal failed: {str(e)}")

