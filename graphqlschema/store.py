from helper import getStore, getStoreDescription
from graphqlschema.schema import StoreData, StoreDetail

def getStores() -> StoreData:
    try:
        stores = getStore()
        descriptions = getStoreDescription()
        details = []
        for store, desc in zip(stores, descriptions):
            details.append(StoreDetail(ID= store, Description=desc))
        return StoreData(stores=details, items=len(stores))
    except Exception as e:
        return []
    
            