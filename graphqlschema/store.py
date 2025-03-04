from helper import getStore
from graphqlschema.schema import StoreData

def getStores() -> StoreData:
    try:
        stores = getStore()
    except Exception as e:
        return []
    return StoreData(stores=stores, items=len(stores))
            