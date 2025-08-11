# schemas/product.py
from pydantic import BaseModel
from typing import Optional, List, Dict

# 分类信息
class ProductCategoryBase(BaseModel):
    id: int
    name: str
    parent_id: Optional[int] = None
    parent_name: Optional[str] = None

    class Config:
        orm_mode = True


class ProductCategoryResponse(BaseModel):
    categories: List[ProductCategoryBase]


# 产品信息
class ProductBase(BaseModel):
    id: int
    itemCode: Optional[str] = None
    name: Dict[str, str]  # { "en_US": "...", "zh_CN": "...", "zh_TW": "..." }
    barcode: Optional[str] = None
    categoryId: Optional[int] = None
    categoryName: Optional[str] = None

    class Config:
        orm_mode = True


class ProductListResponse(BaseModel):
    products: List[ProductBase]
