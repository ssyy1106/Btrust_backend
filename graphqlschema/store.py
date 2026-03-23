from helper import getStore, getStoreDescription, getHRStore
from graphqlschema.schema import StoreData, StoreDetail, StoreSearchParameter

def getStores(param:StoreSearchParameter) -> StoreData:
    try:
        if param and param.HR:
            stores = getHRStore()
        else:
            stores = getStore()
        descriptions = getStoreDescription()
        details = []
        for store, desc in zip(stores, descriptions):
            details.append(StoreDetail(ID= store, Description=desc))
        return StoreData(stores=details, items=len(stores))
    except Exception as e:
        return []
    
            