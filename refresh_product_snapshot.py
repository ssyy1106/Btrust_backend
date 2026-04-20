import argparse
import asyncio
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from pathlib import Path

from database import get_db_stock, get_db_store_sqlserver_factory
from helper import getStore, log_and_save
from models.product import ObjTab
from models.stock import ProductSnapshot, StocktakeItem
from routers.product import _get_product_common
from config_log_env import init_config
from database import init_database

DEFAULT_BATCH_SIZE = 500
BASE_DIR = Path(__file__).resolve().parent  # main.py 所在目录
CONFIG_PATH = BASE_DIR / "config.ini"
config = None


async def upsert_batch(stock_db, batch):
    if not batch:
        return
    stmt = insert(ProductSnapshot).values(batch)
    update_cols = {
        col.name: getattr(stmt.excluded, col.name)
        for col in ProductSnapshot.__table__.columns
        if col.name != "barcode"
    }
    await stock_db.execute(
        stmt.on_conflict_do_update(
            index_elements=[ProductSnapshot.barcode],
            set_=update_cols
        )
    )


async def refresh_product_snapshot(
    batch_size: int = DEFAULT_BATCH_SIZE,
    only_stocktake_barcodes: bool = False
):
    store_list = getStore()
    seen = set()

    async with get_db_stock() as stock_db:
        stocktake_barcodes = None
        if only_stocktake_barcodes:
            stocktake_stmt = select(StocktakeItem.barcode).distinct()
            stocktake_result = await stock_db.execute(stocktake_stmt)
            stocktake_barcodes = {
                str(row[0]).strip().zfill(14)
                for row in stocktake_result.all()
                if row[0]
            }
        for store in store_list:
            store_db_gen = get_db_store_sqlserver_factory(store)
            async with store_db_gen() as store_db:
                result = await store_db.execute(select(ObjTab.F01))
                barcodes = [row[0] for row in result.all()]
                batch = []

                for barcode in barcodes:
                    if not barcode:
                        continue
                    barcode_str = str(barcode).strip()
                    if not barcode_str:
                        continue
                    barcode_padded = barcode_str.zfill(14)
                    if stocktake_barcodes is not None and barcode_padded not in stocktake_barcodes:
                        continue
                    if barcode_padded in seen:
                        continue

                    try:
                        product = await _get_product_common(
                            barcode_str,
                            store,
                            store_db,
                            try_without_checkdigit=True
                        )
                    except HTTPException:
                        continue
                    except Exception as exc:
                        log_and_save("ERROR", f"refresh_product_snapshot error: {exc}")
                        continue

                    snapshot_barcode = (product.get("barcode") or barcode_str).strip()
                    if not snapshot_barcode:
                        continue
                    snapshot_barcode = snapshot_barcode.zfill(14)
                    if snapshot_barcode in seen:
                        continue

                    seen.add(snapshot_barcode)
                    batch.append({
                        "barcode": snapshot_barcode,
                        "name_en": product.get("name_en"),
                        "name_cn": product.get("name_cn"),
                        "name_fr": product.get("name_fr"),
                        "brand": product.get("brand"),
                        "specification": product.get("specification"),
                        "category_code": product.get("category_code"),
                        "category_name": product.get("category_name"),
                        "price_type": product.get("price_type"),
                        "unit_price": product.get("unit_price"),
                        "pack_qty": product.get("pack_qty"),
                        "pack_price": product.get("pack_price"),
                        "valid_from": product.get("valid_from"),
                        "valid_to": product.get("valid_to"),
                        "original_price": product.get("original_price"),
                        "tax": product.get("tax"),
                        "unit_type": product.get("unit_type"),
                        "image_url": product.get("image_url"),
                        "store": store,
                        "update_time": datetime.now()
                    })

                    if len(batch) >= batch_size:
                        await upsert_batch(stock_db, batch)
                        await stock_db.commit()
                        batch = []

                if batch:
                    await upsert_batch(stock_db, batch)
                    await stock_db.commit()
                



def main():
    global config
    config = init_config(CONFIG_PATH)
    init_database()
    parser = argparse.ArgumentParser(description="Refresh product_snapshot table.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Upsert batch size."
    )
    parser.add_argument(
        "--only-stocktake-barcodes",
        action="store_true",
        help="Only sync barcodes that exist in stocktake_item."
    )
    args = parser.parse_args()

    async def run_and_cleanup():
        try:
            await refresh_product_snapshot(
                batch_size=args.batch_size,
                only_stocktake_barcodes=args.only_stocktake_barcodes
            )
        finally:
            # 脚本结束前释放所有数据库连接，解决 Unclosed connection 报错
            from database import dispose_engines
            await dispose_engines()

    asyncio.run(run_and_cleanup())


if __name__ == "__main__":
    main()
